"""
Pruebas de la fase 6: agentes 9-12, bucle de corrección y memoria creativa.

Aquí se prueba el cierre del ciclo: que el Auditor devuelva el trabajo al
agente correcto por la cadena más barata, y que sólo los aprendizajes con
evidencia influyan en campañas futuras.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.agents import (
    AGENT_REGISTRY,
    AnalystAgent,
    AuditorAgent,
    CampaignMetricsInput,
    EditorAgent,
    VoiceDirectorAgent,
    load_prompt,
)
from app.contracts import (
    AuditDecision,
    AuditIssue,
    AuditResult,
    AuditScores,
    CampaignLearnings,
    CharacterBible,
    EditPlan,
    Confidence,
    IssueCategory,
    UGCScript,
)
from app.gateway import AIGateway, FakeProvider, Quality
from app.gateway.providers import (
    FakeVoiceProvider,
    HTTPVoiceProvider,
    VoiceRequest,
    unverified_voice_providers,
    voice_price,
    voice_provider,
)
from app.orchestrator import (
    CorrectionLoop,
    ProjectState,
    RetryLimits,
    RetryPolicy,
    Stage,
    stages_touching_credits,
)
from app.services import CreativeMemory

# ---------------------------------------------------------- payloads

SCRIPT = {
    "artifact": "ugc_script", "created_by": "agent_04", "hook_id": "H02",
    "target_duration_sec": 20.0, "total_duration_sec": 20.0,
    "clips": [
        {"clip_id": "C01", "start": 0, "end": 5, "role": "hook",
         "dialogue": "Casi cancelo el cumpleaños de mi hija"},
        {"clip_id": "C02", "start": 5, "end": 20, "role": "cta",
         "dialogue": "Escríbeles antes de volverte loca"},
    ],
    "cta": "Escríbenos por WhatsApp",
}

BIBLE = {
    "artifact": "character_bible", "created_by": "agent_06",
    "avatar_id": "AV-FEMALE-EC-001", "display_name": "Sofía",
    "physical": {"age_range": "31-34", "origin": "Ecuador / Guayaquil",
                 "face": "ovalado", "hair": "castaño oscuro",
                 "skin": "oliva clara", "build": "normal"},
    "personality": "habla rápido cuando se emociona",
    "speech_style": "frases cortas, muletilla 'o sea'",
    "wardrobe_allowed": ["camiseta blanca"],
    "wardrobe_forbidden": ["branding"],
    "natural_imperfections": ["sonrisa asimétrica", "mechón suelto", "ojeras"],
}

VOICE = {
    "artifact": "voice_direction", "created_by": "agent_09", "clip_id": "C01",
    "profile": {"language": "es-EC", "accent": "ecuatoriano-neutro",
                "age_perception": "27-34", "pace": "medio_rapido",
                "tone": "conversacional con leve entusiasmo"},
    "pauses_before": ["casi", "cumpleaños"],
    "emphasis_words": ["cancelo"],
    "pacing_notes": ("Arranca rápido, frena en 'casi', y el cierre lo dice de "
                     "lado como quien no quiere insistir."),
    "avoid": ["entonación de locutor publicitario"],
}

EDIT = {
    "artifact": "edit_plan", "created_by": "agent_10",
    "clip_order": ["C01", "C02"], "expected_clip_ids": ["C01", "C02"],
    "script_duration_sec": 20.0, "assembled_duration_sec": 20.0,
    "subtitles": True, "music_track": "hook_upbeat_01",
}


def _scores(**over) -> AuditScores:
    base = dict(identity=92, anatomy=88, motion=85, physics=87, lip_sync=90,
                voice=86, product=95, continuity=89, ugc_realism=84,
                hook_visual=81, pacing=83, commercial_clarity=80)
    base.update(over)
    return AuditScores(**base)


def _audit(*, decision=AuditDecision.APPROVED, realism=88, ad=82, cycle=1,
           category=None, clip_id="C03", **score_over) -> AuditResult:
    issue = None
    if category is not None:
        from app.contracts import ERROR_ROUTING
        issue = AuditIssue(category=category, description="problema detectado",
                           route_to_agent=ERROR_ROUTING[category])
    return AuditResult(
        artifact="audit_result", created_by="agent_11", clip_id=clip_id,
        cycle=cycle, scores=_scores(**score_over), realism_score=realism,
        ad_score=ad, decision=decision, issue=issue)


def _gw(responses):
    return AIGateway(provider=FakeProvider(
        responses=[json.dumps(r) for r in responses]))


# ------------------------------------------------------------ prompts


def test_los_doce_prompts_existen():
    for n in range(1, 13):
        assert len(load_prompt(n)) > 200


def test_el_registro_tiene_los_doce_agentes():
    assert set(AGENT_REGISTRY) == set(range(1, 13))


def test_el_prompt_de_voz_ataca_la_entonacion_de_locutor():
    assert "locutor publicitario" in load_prompt(9).lower()


def test_el_prompt_del_auditor_explica_el_coste_de_cada_ruta():
    p = load_prompt(11)
    assert "regeneración" in p and "hook_visual" in p


def test_el_prompt_del_analista_advierte_de_convertir_ruido_en_doctrina():
    p = load_prompt(12).lower()
    assert "una sola campaña" in p or "ruido en doctrina" in p


# ------------------------------------------------------------ agentes


def test_el_director_de_voz_recibe_como_habla_el_avatar():
    gw = _gw([VOICE])
    VoiceDirectorAgent().run(gw, (UGCScript.model_validate(SCRIPT), "C01",
                                  CharacterBible.model_validate(BIBLE)))
    enviado = gw.provider.calls[0].user
    assert "muletilla 'o sea'" in enviado
    assert "no de lo que suene mejor" in enviado


def test_el_editor_declara_los_clips_que_faltan():
    """No se monta en silencio con clips ausentes."""
    gw = _gw([EDIT])
    EditorAgent().run(gw, (UGCScript.model_validate(SCRIPT), ["C01"]))
    enviado = gw.provider.calls[0].user
    assert "ATENCIÓN" in enviado and "C02" in enviado


def test_el_auditor_recuerda_los_ciclos_previos():
    gw = _gw([_audit(category=IssueCategory.MOTION, decision=AuditDecision.REGENERATE,
                     realism=70).model_dump(mode="json")])
    AuditorAgent().run(gw, ("C03", EditPlan.model_validate(EDIT), 3,
                            "la mano se dobla"))
    enviado = gw.provider.calls[0].user
    assert "ciclo 3" in enviado


def test_el_auditor_no_se_abarata():
    """Decide si se gasta más dinero; no es sitio para el modelo barato."""
    assert AuditorAgent.spec.quality is Quality.HIGH


def test_el_analista_avisa_cuando_no_hay_evidencia_para_confianza_alta():
    gw = _gw([{"artifact": "campaign_learnings", "created_by": "agent_12",
               "project_code": "UGC-0001",
               "metrics": {"impressions": 5000, "ctr": 0.02, "hook_rate": 0.3,
                           "spend_usd": 100.0},
               "insights": []}])
    AnalystAgent().run(gw, CampaignMetricsInput(
        project_code="UGC-0001", impressions=5000, ctr=0.02, hook_rate=0.3,
        spend_usd=100.0, historical_projects=["UGC-0001"]))
    enviado = gw.provider.calls[0].user
    assert "NINGÚN insight puede declararse de confianza alta" in enviado


# --------------------------------------------------------------- voz


def test_ningun_precio_de_voz_esta_verificado():
    assert "elevenlabs" in unverified_voice_providers()


def test_el_coste_de_voz_va_por_caracter(monkeypatch):
    """Tercer modelo de coste del sistema: ni token, ni segundo, ni imagen."""
    monkeypatch.setenv("PRICE_VOICE_ELEVENLABS", "0.30")
    voice_provider._load_voice_price_overrides()
    p = voice_provider.voice_price("elevenlabs")
    assert p.cost("x" * 1000) == 0.30


def test_el_proveedor_de_voz_exige_clave(monkeypatch):
    monkeypatch.delenv("VOICE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="VOICE_API_KEY"):
        HTTPVoiceProvider()


def test_la_sintesis_estima_duracion_al_ritmo_del_guionista():
    """2,5 palabras/segundo: el mismo ritmo con el que se dimensionan clips."""
    p = FakeVoiceProvider()
    r = p.synthesize(VoiceRequest(text=" ".join(["palabra"] * 25),
                                  voice_id="v1"))
    assert r.duration_sec == 10.0


# ------------------------------------------------- bucle de corrección


def test_un_clip_aprobado_no_dispara_correccion():
    loop = CorrectionLoop()
    state = ProjectState(project_code="UGC-0001")
    out = loop.decide(state, _audit())
    assert out.approved and out.route is None


def test_un_problema_de_movimiento_regenera_solo_el_video():
    loop = CorrectionLoop()
    state = ProjectState(project_code="UGC-0001")
    out = loop.decide(state, _audit(decision=AuditDecision.REGENERATE,
                                    realism=62, category=IssueCategory.MOTION))
    assert out.decision == "correct"
    assert out.route.as_path() == "11 → 8 → 11"
    assert out.route.regenerations == 1


def test_un_problema_de_identidad_arrastra_imagen_y_video():
    loop = CorrectionLoop()
    state = ProjectState(project_code="UGC-0001")
    out = loop.decide(state, _audit(decision=AuditDecision.REGENERATE,
                                    realism=62, category=IssueCategory.IDENTITY))
    assert out.route.chain == [6, 7, 8]


def test_una_correccion_de_ritmo_no_gasta_creditos():
    loop = CorrectionLoop()
    state = ProjectState(project_code="UGC-0001")
    out = loop.decide(state, _audit(decision=AuditDecision.REGENERATE,
                                    realism=70, ad=60,
                                    category=IssueCategory.PACING))
    assert not out.route.touches_billable
    assert stages_touching_credits(out.route) == []


def test_una_correccion_de_identidad_si_gasta_creditos():
    loop = CorrectionLoop()
    state = ProjectState(project_code="UGC-0001")
    out = loop.decide(state, _audit(decision=AuditDecision.REGENERATE,
                                    realism=62, category=IssueCategory.IDENTITY))
    assert set(stages_touching_credits(out.route)) == {Stage.IMAGE, Stage.VIDEO}


def test_aprobar_por_debajo_del_umbral_va_a_revision_humana():
    """Los umbrales mandan sobre el veredicto del agente."""
    loop = CorrectionLoop()
    state = ProjectState(project_code="UGC-0001")
    out = loop.decide(state, _audit(decision=AuditDecision.APPROVED,
                                    realism=62, ad=70))
    assert out.needs_human
    assert "por debajo de los umbrales" in out.message


def test_el_tope_de_ciclos_deriva_a_humano():
    loop = CorrectionLoop(RetryPolicy(RetryLimits(audit_cycles=2)))
    state = ProjectState(project_code="UGC-0001")
    fallo = dict(decision=AuditDecision.REGENERATE, realism=62,
                 category=IssueCategory.MOTION)

    assert loop.decide(state, _audit(cycle=1, **fallo)).decision == "correct"
    assert loop.decide(state, _audit(cycle=2, **fallo)).decision == "correct"
    tercero = loop.decide(state, _audit(cycle=3, **fallo))
    assert tercero.needs_human
    assert "agotó sus 2 intentos" in tercero.message


def test_los_topes_de_auditoria_son_por_clip():
    """Un clip problemático no puede bloquear los demás."""
    loop = CorrectionLoop(RetryPolicy(RetryLimits(audit_cycles=1)))
    state = ProjectState(project_code="UGC-0001")
    fallo = dict(decision=AuditDecision.REGENERATE, realism=62,
                 category=IssueCategory.MOTION)

    loop.decide(state, _audit(clip_id="C03", **fallo))
    agotado = loop.decide(state, _audit(clip_id="C03", **fallo))
    otro = loop.decide(state, _audit(clip_id="C04", **fallo))

    assert agotado.needs_human
    assert otro.decision == "correct"      # C04 conserva sus intentos


def test_el_desperdicio_por_correcciones_queda_medido():
    """
    Cuántas reejecuciones costó la calidad, y qué las causó. Es el dato que
    dice qué prompt hay que mejorar.
    """
    loop = CorrectionLoop(RetryPolicy(RetryLimits(audit_cycles=9)))
    state = ProjectState(project_code="UGC-0001")
    for cat in (IssueCategory.IDENTITY, IssueCategory.MOTION,
                IssueCategory.IDENTITY, IssueCategory.PACING):
        loop.decide(state, _audit(decision=AuditDecision.REGENERATE, realism=62,
                                  category=cat, clip_id=f"C{cat.value[:2]}"))

    assert loop.wasted_regenerations() == 3 + 1 + 3 + 1
    assert loop.billable_corrections() == 3      # pacing no gasta créditos
    assert list(loop.by_category())[0] is IssueCategory.IDENTITY


# ------------------------------------------------- memoria creativa


def _learnings(confidence=Confidence.ALTA, projects=3, impressions=50_000):
    return CampaignLearnings.model_validate({
        "artifact": "campaign_learnings", "created_by": "agent_12",
        "project_code": "UGC-0001",
        "metrics": {"impressions": 52_000, "ctr": 0.021, "hook_rate": 0.34,
                    "spend_usd": 900.0},
        "insights": [{
            "text": "Los hooks de confesión rinden mejor con mujeres 25-34",
            "confidence": confidence.value, "applies_to": ["hook_type"],
            "scope": "category", "scope_value": "eventos_infantiles",
            "evidence": {
                "project_codes": [f"UGC-{i:04d}" for i in range(1, projects + 1)],
                "total_impressions": impressions, "total_spend_usd": 900.0},
        }],
    })


def test_solo_la_confianza_alta_llega_a_la_memoria():
    mem = CreativeMemory()
    escritas = mem.write(_learnings(Confidence.MEDIA, projects=1,
                                    impressions=500))
    assert escritas == []
    assert mem.stats()["total"] == 0


def test_un_insight_con_evidencia_se_escribe():
    mem = CreativeMemory()
    escritas = mem.write(_learnings())
    assert len(escritas) == 1
    assert escritas[0].evidence_impressions == 50_000


def test_la_memoria_se_consulta_por_variable_afectada():
    mem = CreativeMemory()
    mem.write(_learnings())
    assert len(mem.query(applies_to="hook_type")) == 1
    assert mem.query(applies_to="avatar_id") == []


def test_la_memoria_se_filtra_por_categoria():
    mem = CreativeMemory()
    mem.write(_learnings())
    assert len(mem.query(scope_value="eventos_infantiles")) == 1
    assert mem.query(scope_value="software_b2b") == []


def test_un_aprendizaje_viejo_deja_de_influir():
    """En publicidad digital, un insight de hace un año es arqueología."""
    mem = CreativeMemory(ttl_days=180)
    mem.write(_learnings())
    futuro = datetime.now(timezone.utc) + timedelta(days=200)
    assert mem.query(now=futuro) == []
    assert mem.stats(now=futuro)["caducadas"] == 1


def test_un_aprendizaje_se_desactiva_no_se_borra():
    """El histórico explica decisiones pasadas."""
    mem = CreativeMemory()
    entrada = mem.write(_learnings())[0]
    mem.deactivate(entrada.id)
    assert mem.query() == []
    assert mem.stats()["total"] == 1


def test_la_memoria_ordena_por_peso_de_evidencia():
    """Si dos aprendizajes se contradicen, primero el que tiene más datos."""
    mem = CreativeMemory()
    mem.write(_learnings(impressions=12_000))
    mem.write(_learnings(impressions=90_000))
    resultados = mem.query()
    assert resultados[0].evidence_impressions == 90_000


def test_el_formato_para_el_agente_incluye_la_evidencia():
    """El Estratega debe poder juzgar cuánto pesa lo que le pasan."""
    mem = CreativeMemory()
    mem.write(_learnings())
    linea = mem.as_prompt_lines()[0]
    assert "3 campañas" in linea and "50,000 impresiones" in linea
