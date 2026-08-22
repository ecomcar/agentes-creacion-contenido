"""
Pruebas del AI Gateway.

Todo corre con FakeProvider: sin red, sin API key, sin gasto. Lo que se
prueba es la lógica del gateway, no el modelo.
"""

from __future__ import annotations

import json

import pytest

from app.contracts import ArtifactType, ResearchBrief, Strategy
from app.gateway import (
    AIGateway,
    Budget,
    BudgetExceeded,
    BudgetLimits,
    CostGuard,
    FakeProvider,
    GatewayError,
    ModelRouter,
    Quality,
    RepairFailed,
    RunRecord,
    TaskKind,
    TaskSpec,
    estimate_cost,
    extract_json,
    price_for,
    unverified_models,
)
from app.gateway.model_router import (
    CHEAP_TEXT_MODEL,
    DEFAULT_TEXT_MODEL,
    STRONG_TEXT_MODEL,
)

# ---------------------------------------------------------- payloads


VALID_BRIEF = {
    "artifact": "research_brief",
    "created_by": "agent_01",
    "product": {"name": "Decoración infantil", "category": "eventos",
                "core_benefit": "Fiesta lista sin organizar nada"},
    "audience_signals": {"age_range": "25-40", "location": "Guayaquil",
                         "known_pain_points": ["falta de tiempo"]},
}

VALID_STRATEGY = {
    "artifact": "strategy",
    "created_by": "agent_02",
    "awareness_level": "problem_aware",
    "primary_pain": "Organizar la fiesta consume semanas",
    "primary_desire": "Que salga bonita sin esfuerzo",
    "objections": ["precio"],
    "unique_mechanism": "Montaje llave en mano en tres horas",
    "angles": [
        {"angle_id": "A01", "name": "Mamá sola", "premise": "Intenta hacerlo todo sola",
         "emotion": "alivio", "recommended_format": "ugc"},
        {"angle_id": "A02", "name": "Precio oculto", "premise": "Nadie cuenta lo que cuesta improvisar",
         "emotion": "sorpresa", "recommended_format": "ugc"},
        {"angle_id": "A03", "name": "Antes y después", "premise": "Transformación visible del salón",
         "emotion": "orgullo", "recommended_format": "reel"},
    ],
}


def _gw(responses, **kw) -> tuple[AIGateway, FakeProvider]:
    provider = FakeProvider(responses=responses, model=DEFAULT_TEXT_MODEL)
    return AIGateway(provider=provider, **kw), provider


def _call(gw, contract=ResearchBrief, spec=None, **kw):
    return gw.generate_artifact(
        contract=contract,
        spec=spec or TaskSpec(task=TaskKind.STRUCTURED),
        system="Eres el Investigador.", user="Analiza este producto.",
        agent_number=1, agent_name="researcher", **kw,
    )


# ------------------------------------------------------- extract_json


def test_extrae_json_limpio():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extrae_json_dentro_de_vallas_markdown():
    txt = 'Aquí tienes:\n```json\n{"a": 1, "b": "x"}\n```\nEspero que sirva.'
    assert extract_json(txt) == {"a": 1, "b": "x"}


def test_extrae_json_con_preambulo_sin_vallas():
    txt = 'Claro, este es el resultado: {"a": 1, "b": {"c": 2}} — listo.'
    assert extract_json(txt) == {"a": 1, "b": {"c": 2}}


def test_extrae_json_con_llaves_dentro_de_strings():
    """Las llaves dentro de comillas no deben confundir al balanceador."""
    txt = 'texto {"nota": "usa {llaves} y \\"comillas\\"", "n": 1} fin'
    assert extract_json(txt)["n"] == 1


def test_sin_json_lanza_error():
    with pytest.raises(GatewayError):
        extract_json("No pude generar la estrategia, lo siento.")


# ------------------------------------------------------------ router


def test_router_manda_extraccion_al_modelo_barato():
    d = ModelRouter().route(TaskSpec(task=TaskKind.EXTRACTION))
    assert d.model == CHEAP_TEXT_MODEL


def test_router_manda_razonamiento_alto_al_modelo_fuerte():
    d = ModelRouter().route(TaskSpec(task=TaskKind.REASONING, quality=Quality.HIGH))
    assert d.model == STRONG_TEXT_MODEL


def test_router_respeta_presupuesto_bajo_en_razonamiento():
    d = ModelRouter().route(TaskSpec(task=TaskKind.REASONING, budget=Budget.LOW))
    assert d.model == CHEAP_TEXT_MODEL


def test_router_nunca_abarata_lo_creativo():
    """Hooks y guion con modelo barato salen planos; la regla lo impide."""
    for budget in Budget:
        d = ModelRouter().route(TaskSpec(task=TaskKind.CREATIVE, budget=budget))
        assert d.model == DEFAULT_TEXT_MODEL


def test_router_siempre_explica_su_decision():
    for task in (TaskKind.REASONING, TaskKind.CREATIVE, TaskKind.STRUCTURED,
                 TaskKind.EXTRACTION):
        assert ModelRouter().route(TaskSpec(task=task)).reason


def test_router_falla_claro_en_modalidades_no_conectadas():
    with pytest.raises(NotImplementedError, match="fase 4-5"):
        ModelRouter().route(TaskSpec(task=TaskKind.VIDEO_GENERATION))


def test_force_model_gana_sobre_las_reglas(monkeypatch):
    monkeypatch.setenv("FORCE_MODEL", "modelo-de-prueba")
    d = ModelRouter().route(TaskSpec(task=TaskKind.REASONING, quality=Quality.HIGH))
    assert d.model == "modelo-de-prueba"


# --------------------------------------------------------- pricing


def test_precio_de_sonnet_esta_verificado():
    p = price_for("claude-sonnet-5")
    assert p.verified and (p.input_per_mtok, p.output_per_mtok) == (2.0, 10.0)


def test_modelos_sin_verificar_estan_declarados():
    """Preferimos declarar la incertidumbre a fingir precisión."""
    assert "claude-opus-5" in unverified_models()


def test_modelo_desconocido_no_inventa_precio():
    p = price_for("modelo-que-no-existe")
    assert p.cost(1_000_000, 1_000_000) == 0.0
    assert "SIN PRECIO" in p.note


def test_calculo_de_coste():
    # 1M entrada + 1M salida con sonnet = 2 + 10
    assert estimate_cost("claude-sonnet-5", 1_000_000, 1_000_000) == 12.0


# ------------------------------------------------------- cost guard


def test_tope_por_llamada_corta_antes_de_gastar():
    guard = CostGuard(BudgetLimits(max_cost_per_call_usd=0.01))
    with pytest.raises(BudgetExceeded, match="tope por llamada"):
        guard.check(model="claude-sonnet-5", input_tokens=1000,
                    max_output_tokens=100_000)
    assert guard.session_spent == 0.0   # no se gastó nada


def test_tope_usa_el_peor_caso_no_el_esperado():
    """
    El peor caso asume que el modelo agota max_tokens. Un tope calculado
    sobre la salida 'esperada' se supera en cuanto el modelo se extiende.
    """
    guard = CostGuard()
    barato = guard.estimate_worst_case("claude-sonnet-5", 1000, 500)
    caro = guard.estimate_worst_case("claude-sonnet-5", 1000, 8000)
    assert caro > barato


def test_tope_por_proyecto_es_independiente_del_de_sesion():
    guard = CostGuard(BudgetLimits(max_cost_per_call_usd=10,
                                   max_cost_per_project_usd=0.05,
                                   max_cost_per_session_usd=100))
    guard.record(0.04, project_code="UGC-0001")
    guard.check(model="claude-sonnet-5", input_tokens=100,
                max_output_tokens=100, project_code="UGC-0002")   # otro proyecto: pasa
    with pytest.raises(BudgetExceeded, match="UGC-0001"):
        guard.check(model="claude-sonnet-5", input_tokens=10_000,
                    max_output_tokens=4000, project_code="UGC-0001")


def test_gasto_real_se_registra_no_el_peor_caso():
    guard = CostGuard()
    guard.check(model="claude-sonnet-5", input_tokens=1000, max_output_tokens=4000)
    assert guard.session_spent == 0.0        # check no gasta
    guard.record(0.002)
    assert guard.session_spent == 0.002


# -------------------------------------------------- gateway completo


def test_devuelve_contrato_validado_no_texto():
    gw, _ = _gw([json.dumps(VALID_BRIEF)])
    art = _call(gw)
    assert isinstance(art, ResearchBrief)
    assert art.artifact is ArtifactType.RESEARCH_BRIEF
    assert art.product.core_benefit.startswith("Fiesta")


def test_tolera_vallas_de_markdown_del_modelo():
    gw, _ = _gw([f"Claro:\n```json\n{json.dumps(VALID_BRIEF)}\n```"])
    assert isinstance(_call(gw), ResearchBrief)


def test_repara_json_invalido_con_los_errores_exactos():
    roto = dict(VALID_STRATEGY)
    roto["angles"] = roto["angles"][:2]        # el contrato exige 3
    gw, provider = _gw([json.dumps(roto), json.dumps(VALID_STRATEGY)])

    art = gw.generate_artifact(
        contract=Strategy, spec=TaskSpec(task=TaskKind.REASONING),
        system="Eres el Estratega.", user="Define ángulos.",
        agent_number=2, agent_name="strategist",
    )

    assert isinstance(art, Strategy)
    assert len(provider.calls) == 2
    # El segundo intento incluye el error de Pydantic, no un "reintenta".
    correccion = provider.calls[1].user
    assert "CORRECCIÓN REQUERIDA" in correccion
    assert "angles" in correccion


def test_bucle_de_reparacion_tiene_tope_duro():
    roto = json.dumps({"artifact": "strategy", "created_by": "agent_02"})
    gw, provider = _gw([roto, roto, roto, roto, roto])

    with pytest.raises(RepairFailed) as exc:
        gw.generate_artifact(
            contract=Strategy, spec=TaskSpec(task=TaskKind.REASONING),
            system="s", user="u", agent_number=2, agent_name="strategist",
        )

    assert exc.value.attempts == 3          # 1 intento + 2 reparaciones
    assert len(provider.calls) == 3         # no sigue quemando llamadas


def test_presupuesto_bloquea_antes_de_llamar_al_proveedor():
    guard = CostGuard(BudgetLimits(max_cost_per_call_usd=0.0000001))
    gw, provider = _gw([json.dumps(VALID_BRIEF)], cost_guard=guard)

    with pytest.raises(BudgetExceeded):
        _call(gw)

    assert provider.calls == []             # el proveedor nunca se invocó
    assert gw.runs[-1].status == "blocked"


def test_cada_llamada_deja_traza_con_forma_de_agent_runs():
    gw, _ = _gw([json.dumps(VALID_BRIEF)])
    _call(gw, project_code="UGC-0001")

    run = gw.runs[-1]
    assert isinstance(run, RunRecord)
    assert (run.agent_number, run.agent_name, run.status) == (1, "researcher", "success")
    assert run.model_used == DEFAULT_TEXT_MODEL
    assert run.input_tokens > 0 and run.output_tokens > 0


def test_los_intentos_fallidos_tambien_dejan_traza():
    roto = dict(VALID_STRATEGY)
    roto["angles"] = []
    gw, _ = _gw([json.dumps(roto), json.dumps(VALID_STRATEGY)])
    gw.generate_artifact(contract=Strategy, spec=TaskSpec(task=TaskKind.REASONING),
                         system="s", user="u", agent_number=2,
                         agent_name="strategist")

    assert len(gw.runs) == 2
    assert [r.status for r in gw.runs] == ["failed", "success"]
    assert gw.failed_runs()[0].error_message   # el error queda registrado


def test_fallo_del_proveedor_se_registra_y_se_propaga():
    provider = FakeProvider(responses=[json.dumps(VALID_BRIEF)], fail_times=1)
    gw = AIGateway(provider=provider)
    with pytest.raises(GatewayError, match="proveedor"):
        _call(gw)
    assert gw.runs[-1].status == "failed"


def test_el_coste_se_acumula_por_proyecto():
    gw, _ = _gw([json.dumps(VALID_BRIEF), json.dumps(VALID_BRIEF)])
    _call(gw, project_code="UGC-0001")
    _call(gw, project_code="UGC-0001")
    assert gw.cost_guard.project_spent["UGC-0001"] == gw.total_cost()


def test_el_agente_nunca_nombra_el_modelo():
    """
    El agente pasa un TaskSpec, no un nombre de modelo. Si esto cambiara,
    cambiar de proveedor obligaría a tocar los 12 agentes.
    """
    import inspect
    sig = inspect.signature(AIGateway.generate_artifact)
    assert "model" not in sig.parameters
    assert "spec" in sig.parameters
