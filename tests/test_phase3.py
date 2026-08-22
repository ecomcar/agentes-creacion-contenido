"""
Pruebas de la fase 3: agentes 1-4, máquina de estados, enrutamiento de
correcciones, topes de reintento y orquestador.

Todo con FakeProvider: sin red, sin clave, sin gasto.
"""

from __future__ import annotations

import json

import pytest

from app.agents import (
    AGENT_REGISTRY,
    HooksAgent,
    ProductInput,
    PromptNotFound,
    ResearcherAgent,
    ScriptwriterAgent,
    StrategistAgent,
    StrategistWithMemoryAgent,
    available_versions,
    load_prompt,
)
from app.contracts import IssueCategory, Strategy, UGCScript
from app.gateway import (
    AIGateway,
    BudgetLimits,
    CostGuard,
    FakeProvider,
    Quality,
    TaskKind,
)
from app.orchestrator import (
    CORRECTION_CHAINS,
    HUMAN_GATES,
    InvalidTransition,
    Orchestrator,
    ProjectState,
    RetryLimits,
    RetryPolicy,
    Stage,
    StageStatus,
    StateMachine,
    cheapest_first,
    route_correction,
)

# ------------------------------------------------------------ payloads

BRIEF = {
    "artifact": "research_brief", "created_by": "agent_01",
    "product": {"name": "Party Voom", "category": "decoración infantil",
                "core_benefit": "La fiesta queda montada sin organizar nada"},
    "audience_signals": {"age_range": "25-40", "location": "Guayaquil",
                         "known_pain_points": ["falta de tiempo"]},
    "competitors": [{"name": "Otro", "angle_observed": "precio bajo"}],
}

STRATEGY = {
    "artifact": "strategy", "created_by": "agent_02",
    "awareness_level": "problem_aware",
    "primary_pain": "Organizar la fiesta consume semanas",
    "primary_desire": "Que salga bonita sin esfuerzo",
    "objections": ["precio", "confianza"],
    "unique_mechanism": "Montaje llave en mano en tres horas",
    "angles": [
        {"angle_id": "A01", "name": "Mamá sola",
         "premise": "Intenta hacerlo todo sola", "emotion": "alivio",
         "recommended_format": "ugc"},
        {"angle_id": "A02", "name": "Precio oculto",
         "premise": "Nadie cuenta lo que cuesta improvisar",
         "emotion": "sorpresa", "recommended_format": "ugc"},
        {"angle_id": "A03", "name": "Antes y después",
         "premise": "Transformación visible del salón", "emotion": "orgullo",
         "recommended_format": "reel"},
    ],
}

STRATEGY_SIN_MECANISMO = {**STRATEGY, "unique_mechanism": "por definir"}


def _hooks_payload(angle="A01", tipos=None):
    tipos = tipos or ["problema", "confesion", "curiosidad", "contrarian",
                      "testimonial", "demostracion", "visual", "problema"]
    return {
        "artifact": "hooks", "created_by": "agent_03", "angle_id": angle,
        "hooks": [
            {"hook_id": f"H{i+1:02d}", "type": t,
             "text": f"Texto del hook número {i+1} para la campaña",
             "scores": {"curiosidad": 88, "claridad": 85, "pattern_interrupt": 84,
                        "relevancia": 86, "ugc_fit": 90, "visual_ease": 82}}
            for i, t in enumerate(tipos)
        ],
    }


def _script_payload(total=35.0):
    roles = ["hook", "problema", "demostracion", "cta"]
    step = total / len(roles)
    return {
        "artifact": "ugc_script", "created_by": "agent_04", "hook_id": "H02",
        "target_duration_sec": total, "total_duration_sec": total,
        "clips": [{"clip_id": f"C{i+1:02d}", "start": round(i*step, 2),
                   "end": round((i+1)*step, 2), "role": r,
                   "dialogue": f"Diálogo {i+1}"} for i, r in enumerate(roles)],
        "cta": "Escríbenos por WhatsApp",
    }


def _gw(responses, **kw):
    provider = FakeProvider(responses=[json.dumps(r) if isinstance(r, dict) else r
                                       for r in responses])
    return AIGateway(provider=provider, **kw), provider


# ------------------------------------------------------------- prompts


def test_los_cuatro_prompts_existen_como_archivos():
    for n in (1, 2, 3, 4):
        assert len(load_prompt(n)) > 200
        # El Agente 3 tiene v2 (refuerzo del límite de palabras del
        # hook); el resto sigue en v1. Ambas deben existir y ser
        # legibles, no que haya exactamente una.
        assert available_versions(n) == ([1, 2] if n == 3 else [1])


def test_prompt_inexistente_falla_con_mensaje_util():
    with pytest.raises(PromptNotFound, match="v9.md"):
        load_prompt(1, version=9)


def test_el_prompt_del_estratega_advierte_del_fallo_de_angulos():
    """El modo de fallo conocido debe estar nombrado en el prompt."""
    p = load_prompt(2).lower()
    assert "canibalic" in p or "canibalizar" in p or "mismo ángulo" in p


def test_el_prompt_del_investigador_prohibe_rellenar_huecos():
    p = load_prompt(1).lower()
    assert "no la rellenes" in p or "no inventad" in p or "errors" in p


# ------------------------------------------------------------- agentes


def test_el_registro_cubre_exactamente_lo_implementado():
    """
    Invariante en vez de lista fija: hay un agente registrado para cada etapa
    hasta la frontera, y ninguno más allá.

    Escrito así, la prueba no hay que editarla en cada fase — y sigue
    detectando lo que importa: una etapa marcada como implementada sin agente,
    o un agente registrado para una etapa que no lo está.

    El Analista (12) se cuenta aparte: no lo dispara el pipeline sino la
    llegada de métricas, después de publicar.
    """
    from app.orchestrator import OUT_OF_PIPELINE_AGENTS, STAGE_AGENT

    esperados = {STAGE_AGENT[s] for s in StateMachine.stages_before(Stage.PUBLISHED)
                 if StateMachine.is_implemented(s)}
    assert set(AGENT_REGISTRY) == esperados | OUT_OF_PIPELINE_AGENTS


def test_cada_agente_declara_task_spec_no_modelo():
    for cls in AGENT_REGISTRY.values():
        assert isinstance(cls.spec.task, TaskKind)
        assert not hasattr(cls, "model")


def test_el_estratega_usa_sonnet_por_defecto():
    """
    Antes pedía Quality.HIGH (Opus) sin haberlo comparado nunca contra la
    alternativa barata. Con datos reales sobre dos productos, Sonnet
    produjo ángulos igual de distintos y mecanismos igual de sólidos por
    una fracción del costo (~$0.04 vs ~$0.25 por ejecución). El Router
    manda REASONING sin quality=HIGH a Sonnet — ver model_router.py.
    """
    from app.gateway import Quality as Q
    assert StrategistAgent.spec.quality is Q.STANDARD


def test_el_investigador_usa_temperatura_baja():
    """Extracción, no creatividad."""
    assert ResearcherAgent.temperature < 0.5


def test_el_agente_de_hooks_usa_v2_por_defecto():
    """
    v2 se validó con datos reales: sobre el mismo producto (Karol/Seytu),
    v1 dejaba 5 de 10 hooks por encima de 15 palabras y v2 dejó 0. Una vez
    comparadas las dos versiones, la mejor se vuelve el valor por defecto —
    v1 sigue en el archivo por si hace falta revisar la decisión.
    """
    agente_por_defecto = HooksAgent()
    assert agente_por_defecto.prompt_version == 2

    agente_v1 = HooksAgent(prompt_version=1)
    assert agente_v1.prompt_version == 1
    assert agente_v1.system_prompt != agente_por_defecto.system_prompt


def test_el_agente_de_hooks_falla_si_el_angulo_no_existe():
    gw, _ = _gw([])
    strategy = Strategy.model_validate(STRATEGY)
    with pytest.raises(ValueError, match="A09"):
        HooksAgent().run(gw, (strategy, "A09"))


def test_el_guionista_pasa_el_hook_literal():
    gw, provider = _gw([_script_payload()])
    strategy = Strategy.model_validate(STRATEGY)
    from app.contracts import Hooks
    hooks = Hooks.model_validate(_hooks_payload())
    ScriptwriterAgent().run(gw, (strategy, hooks, "H02", 35.0))
    enviado = provider.calls[0].user
    assert hooks.hooks[1].text in enviado
    assert "literal" in enviado.lower()


def test_la_memoria_creativa_se_marca_como_orientativa():
    """Un aprendizaje de otra campaña no es una orden."""
    gw, provider = _gw([STRATEGY])
    from app.contracts import ResearchBrief
    brief = ResearchBrief.model_validate(BRIEF)
    StrategistWithMemoryAgent().run(
        gw, (brief, ["Los hooks de confesión rinden mejor con mujeres 25-34"]))
    enviado = provider.calls[0].user
    assert "orientativos" in enviado and "no obligatorios" in enviado


def test_sin_memoria_el_prompt_no_cambia():
    gw, provider = _gw([STRATEGY, STRATEGY])
    from app.contracts import ResearchBrief
    brief = ResearchBrief.model_validate(BRIEF)
    StrategistAgent().run(gw, brief)
    StrategistWithMemoryAgent().run(gw, (brief, []))
    assert provider.calls[0].user == provider.calls[1].user


# ------------------------------------------------- máquina de estados


def test_no_se_puede_saltar_etapas():
    with pytest.raises(InvalidTransition, match="storyboard"):
        StateMachine.advance(Stage.SCRIPT, Stage.VIDEO)


def test_el_avance_legitimo_pasa():
    assert StateMachine.advance(Stage.RESEARCH, Stage.STRATEGY) is Stage.STRATEGY


def test_published_es_terminal():
    with pytest.raises(InvalidTransition, match="terminal"):
        StateMachine.advance(Stage.PUBLISHED, Stage.RESEARCH)


def test_las_compuertas_humanas_son_las_decisiones_caras():
    assert Stage.STRATEGY in HUMAN_GATES     # elegir ángulo
    assert Stage.HOOKS in HUMAN_GATES        # elegir hook
    assert Stage.RESEARCH not in HUMAN_GATES # automática


def test_auto_mode_desactiva_las_compuertas():
    assert StateMachine.requires_human(Stage.HOOKS, auto_mode=False)
    assert not StateMachine.requires_human(Stage.HOOKS, auto_mode=True)


def test_la_frontera_de_lo_implementado_es_explicita():
    """
    El sistema sabe hasta dónde llega y lo dice, en vez de fallar raro.
    La frontera es contigua: no hay huecos ni etapas implementadas sueltas.
    """
    from app.orchestrator import IMPLEMENTED_THROUGH

    orden = StateMachine.stages_before(Stage.PUBLISHED)
    corte = orden.index(IMPLEMENTED_THROUGH)
    assert all(StateMachine.is_implemented(s) for s in orden[:corte + 1])
    assert not any(StateMachine.is_implemented(s) for s in orden[corte + 1:])


# ------------------------------------------- enrutamiento de errores


def test_cada_categoria_tiene_cadena_de_correccion():
    assert set(CORRECTION_CHAINS) == set(IssueCategory)


def test_movimiento_solo_regenera_el_video():
    r = route_correction(IssueCategory.MOTION, clip_id="C03")
    assert r.chain == [8]
    assert r.as_path() == "11 → 8 → 11"


def test_identidad_arrastra_imagen_y_video():
    r = route_correction(IssueCategory.IDENTITY, clip_id="C03")
    assert r.as_path() == "11 → 6 → 7 → 8 → 11"


def test_corregir_movimiento_es_mas_barato_que_corregir_identidad():
    """Es la razón de ser de todo el enrutamiento selectivo."""
    motion = route_correction(IssueCategory.MOTION)
    identity = route_correction(IssueCategory.IDENTITY)
    hook = route_correction(IssueCategory.HOOK_VISUAL)
    assert motion.regenerations < identity.regenerations < hook.regenerations


def test_el_ritmo_no_toca_generacion_de_medios():
    """Rehacer el montaje no consume créditos de imagen ni video."""
    r = route_correction(IssueCategory.PACING)
    assert not r.touches_billable


def test_la_identidad_si_consume_creditos():
    assert route_correction(IssueCategory.IDENTITY).touches_billable


def test_las_dos_tablas_de_enrutamiento_son_coherentes():
    """
    ERROR_ROUTING (contrato del Auditor) y CORRECTION_CHAINS (orquestador)
    pueden editarse por separado. Este test detecta si divergen.
    """
    for cat in IssueCategory:
        route_correction(cat)   # el assert interno salta si hay incoherencia


def test_se_ataca_primero_lo_barato():
    orden = cheapest_first([IssueCategory.HOOK_VISUAL, IssueCategory.MOTION,
                            IssueCategory.IDENTITY])
    assert orden[0] is IssueCategory.MOTION
    assert orden[-1] is IssueCategory.HOOK_VISUAL


# ----------------------------------------------------- retry policy


def test_los_topes_de_imagen_se_cuentan_por_clip():
    """
    Contados por proyecto, un anuncio de seis clips se bloquearía en el
    segundo clip problemático.
    """
    a = RetryPolicy.retry_key(Stage.IMAGE, "C03")
    b = RetryPolicy.retry_key(Stage.IMAGE, "C04")
    assert a != b


def test_el_tope_de_video_es_tres():
    assert RetryPolicy().limit_for(Stage.VIDEO) == 3


def test_agotar_el_tope_no_permite_mas_intentos():
    p = RetryPolicy(RetryLimits(strategy=2))
    assert p.check(Stage.STRATEGY, 0).allowed
    assert p.check(Stage.STRATEGY, 1).allowed
    d = p.check(Stage.STRATEGY, 2)
    assert d.exhausted and "intervención humana" in d.reason


# ------------------------------------------------------ orquestador


def _orch(responses, **kw):
    gw, provider = _gw(responses, **kw)
    agents = {1: ResearcherAgent(), 2: StrategistAgent(),
              3: HooksAgent(), 4: ScriptwriterAgent()}
    return Orchestrator(gateway=gw, agents=agents), provider, gw


def test_research_es_automatica_y_avanza():
    orch, _, _ = _orch([BRIEF])
    state = ProjectState(project_code="UGC-0001")
    out = orch.run_stage(state, Stage.RESEARCH,
                         ProductInput(product_name="Party Voom",
                                      description="Decoración", brand_name="PV"))
    assert out.status is StageStatus.APPROVED
    assert orch.approve_and_advance(state) is Stage.STRATEGY


def test_strategy_se_detiene_a_esperar_al_humano():
    orch, _, _ = _orch([STRATEGY])
    state = ProjectState(project_code="UGC-0001", current_stage=Stage.STRATEGY)
    from app.contracts import ResearchBrief
    out = orch.run_stage(state, Stage.STRATEGY, ResearchBrief.model_validate(BRIEF))
    assert out.status is StageStatus.PENDING_HUMAN_APPROVAL
    assert out.artifact is not None


def test_auto_mode_no_se_detiene():
    orch, _, _ = _orch([STRATEGY])
    state = ProjectState(project_code="UGC-0001", current_stage=Stage.STRATEGY,
                         auto_mode=True)
    from app.contracts import ResearchBrief
    out = orch.run_stage(state, Stage.STRATEGY, ResearchBrief.model_validate(BRIEF))
    assert out.status is StageStatus.APPROVED


def test_artefacto_valido_pero_no_aprobable_se_reintenta():
    """
    El contrato lo acepta (mecanismo presente) pero los criterios lo rechazan
    (es un placeholder). El orquestador lo marca FAILED y guarda el trabajo.
    """
    orch, _, _ = _orch([STRATEGY_SIN_MECANISMO])
    state = ProjectState(project_code="UGC-0001", current_stage=Stage.STRATEGY)
    from app.contracts import ResearchBrief
    out = orch.run_stage(state, Stage.STRATEGY, ResearchBrief.model_validate(BRIEF))

    assert out.status is StageStatus.FAILED
    assert out.artifact is not None          # el trabajo NO se pierde
    assert "placeholder_field" in {i.code for i in out.issues}
    assert state.retry_counts["strategy"] == 1


def test_el_feedback_del_rechazo_se_le_devuelve_al_agente():
    orch, provider, _ = _orch([STRATEGY_SIN_MECANISMO, STRATEGY])
    state = ProjectState(project_code="UGC-0001", current_stage=Stage.STRATEGY)
    from app.contracts import ResearchBrief
    brief = ResearchBrief.model_validate(BRIEF)

    fallo = orch.run_stage(state, Stage.STRATEGY, brief)
    feedback = Orchestrator.feedback_from(fallo)
    assert "unique_mechanism" in feedback

    ok = orch.run_stage(state, Stage.STRATEGY, brief, feedback=feedback)
    assert ok.status is StageStatus.PENDING_HUMAN_APPROVAL
    assert "CORRECCIÓN SOLICITADA" in provider.calls[1].user
    assert state.retry_counts.get("strategy") is None   # se reinicia al lograrlo


def test_agotar_reintentos_bloquea_en_vez_de_seguir_gastando():
    orch, provider, _ = _orch([STRATEGY_SIN_MECANISMO] * 5)
    orch.retry = RetryPolicy(RetryLimits(strategy=2))
    state = ProjectState(project_code="UGC-0001", current_stage=Stage.STRATEGY)
    from app.contracts import ResearchBrief
    brief = ResearchBrief.model_validate(BRIEF)

    orch.run_stage(state, Stage.STRATEGY, brief)
    orch.run_stage(state, Stage.STRATEGY, brief)
    tercero = orch.run_stage(state, Stage.STRATEGY, brief)

    assert tercero.status is StageStatus.BLOCKED
    assert len(provider.calls) == 2          # el tercero no llegó al modelo


def test_el_tope_de_presupuesto_bloquea_la_etapa():
    guard = CostGuard(BudgetLimits(max_cost_per_call_usd=0.0000001))
    orch, provider, _ = _orch([BRIEF], cost_guard=guard)
    state = ProjectState(project_code="UGC-0001")
    out = orch.run_stage(state, Stage.RESEARCH,
                         ProductInput(product_name="X", description="y",
                                      brand_name="z"))
    assert out.status is StageStatus.BLOCKED
    assert provider.calls == []


def test_una_etapa_no_implementada_lo_dice_claramente():
    orch, _, _ = _orch([])
    from app.orchestrator import FORWARD, IMPLEMENTED_THROUGH

    siguiente = FORWARD[IMPLEMENTED_THROUGH]      # la primera no implementada
    state = ProjectState(project_code="UGC-0001", current_stage=siguiente)
    with pytest.raises(Exception, match="no está implementada"):
        orch.run_stage(state, siguiente, None)


def test_el_coste_se_acumula_en_el_estado_del_proyecto():
    orch, _, gw = _orch([BRIEF, STRATEGY])
    state = ProjectState(project_code="UGC-0001")
    from app.contracts import ResearchBrief
    orch.run_stage(state, Stage.RESEARCH,
                   ProductInput(product_name="X", description="y", brand_name="z"))
    orch.approve_and_advance(state)
    orch.run_stage(state, Stage.STRATEGY, ResearchBrief.model_validate(BRIEF))
    assert state.total_cost_usd == gw.total_cost() > 0


def test_pipeline_completo_de_la_fase_3():
    """Brief → estrategia → hooks → guion, con las compuertas humanas."""
    orch, _, gw = _orch([BRIEF, STRATEGY, _hooks_payload(), _script_payload()])
    state = ProjectState(project_code="UGC-0001")
    from app.contracts import Hooks, ResearchBrief

    r1 = orch.run_stage(state, Stage.RESEARCH,
                        ProductInput(product_name="Party Voom",
                                     description="Decoración infantil",
                                     brand_name="Party Voom"))
    assert r1.status is StageStatus.APPROVED
    orch.approve_and_advance(state)

    r2 = orch.run_stage(state, Stage.STRATEGY, r1.artifact)
    assert r2.status is StageStatus.PENDING_HUMAN_APPROVAL
    orch.approve_and_advance(state)          # el humano elige A01

    r3 = orch.run_stage(state, Stage.HOOKS, (r2.artifact, "A01"))
    assert r3.status is StageStatus.PENDING_HUMAN_APPROVAL
    orch.approve_and_advance(state)          # el humano elige H02

    r4 = orch.run_stage(state, Stage.SCRIPT,
                        (r2.artifact, r3.artifact, "H02", 35.0))
    assert r4.status is StageStatus.PENDING_HUMAN_APPROVAL
    assert isinstance(r4.artifact, UGCScript)
    assert state.current_stage is Stage.SCRIPT
    assert state.total_cost_usd > 0
    assert len(gw.runs) == 4
