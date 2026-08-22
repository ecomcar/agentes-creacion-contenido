"""
Pruebas de los 12 contratos.

Cada prueba verifica una de dos cosas:
  1. Que el esquema RECHAZA lo estructuralmente imposible (ValidationError).
  2. Que approval_check() DETECTA lo editorialmente flojo sin tirar excepción.

La distinción importa: el nivel 1 pierde el trabajo del agente, el nivel 2 lo
conserva para que decida el Orquestador o el humano.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.contracts import (
    AGENT_OUTPUT,
    CONTRACT_REGISTRY,
    ERROR_ROUTING,
    Angle,
    ArtifactStatus,
    ArtifactType,
    AudienceSignals,
    AuditDecision,
    AuditIssue,
    AuditResult,
    AuditScores,
    AwarenessLevel,
    CampaignLearnings,
    CharacterBible,
    ClipRole,
    Competitor,
    Confidence,
    EditPlan,
    Evidence,
    Hook,
    Hooks,
    HookScores,
    HookType,
    ImagePrompt,
    Insight,
    IssueCategory,
    Metrics,
    Pace,
    PhysicalTraits,
    Product,
    PromptBlocks,
    ResearchBrief,
    SceneTemplate,
    ScriptClip,
    ShotType,
    Storyboard,
    StoryboardClip,
    Strategy,
    UGCScript,
    VideoPrompt,
    VoiceDirection,
    VoiceProfile,
    parse_artifact,
)

# --------------------------------------------------------------- fixtures


def _scores(**over) -> HookScores:
    base = dict(curiosidad=88, claridad=85, pattern_interrupt=84,
                relevancia=86, ugc_fit=90, visual_ease=82)
    base.update(over)
    return HookScores(**base)


def _hook(n: int, t: HookType = HookType.PROBLEMA, avg_high=True) -> Hook:
    s = _scores() if avg_high else _scores(curiosidad=40, claridad=45,
                                          pattern_interrupt=40, relevancia=42,
                                          ugc_fit=44, visual_ease=41)
    return Hook(hook_id=f"H{n:02d}", type=t, text=f"Texto del hook número {n}", scores=s)


def _audit_scores(**over) -> AuditScores:
    base = dict(identity=92, anatomy=88, motion=85, physics=87, lip_sync=90,
                voice=86, product=95, continuity=89, ugc_realism=84,
                hook_visual=81, pacing=83, commercial_clarity=80)
    base.update(over)
    return AuditScores(**base)


# ------------------------------------------------- registro y utilidades


def test_registro_cubre_los_doce_agentes():
    assert len(AGENT_OUTPUT) == 12
    assert len(CONTRACT_REGISTRY) == 12
    assert set(AGENT_OUTPUT.values()) == set(CONTRACT_REGISTRY)


def test_parse_artifact_valida_contra_el_contrato_correcto():
    payload = {
        "artifact": "research_brief",
        "created_by": "agent_01",
        "product": {"name": "Decoración infantil", "category": "eventos",
                    "core_benefit": "Fiesta lista sin organizar nada"},
        "audience_signals": {"age_range": "25-40", "location": "Guayaquil",
                             "known_pain_points": ["falta de tiempo"]},
    }
    art = parse_artifact(ArtifactType.RESEARCH_BRIEF, payload)
    assert isinstance(art, ResearchBrief)
    assert art.status is ArtifactStatus.DRAFT


def test_campo_extra_es_rechazado():
    """Un campo de más suele ser el agente inventando estructura."""
    with pytest.raises(ValidationError):
        ResearchBrief(
            artifact=ArtifactType.RESEARCH_BRIEF, created_by="agent_01",
            product=Product(name="X", category="y", core_benefit="z"),
            audience_signals=AudienceSignals(age_range="25-40"),
            campo_inventado="hola",
        )


def test_next_version_no_muta_el_original():
    brief = ResearchBrief(
        artifact=ArtifactType.RESEARCH_BRIEF, created_by="agent_01",
        product=Product(name="X", category="y", core_benefit="z"),
        audience_signals=AudienceSignals(age_range="25-40"),
        status=ArtifactStatus.APPROVED,
    )
    v2 = brief.next_version()
    assert brief.version == 1 and brief.status is ArtifactStatus.APPROVED
    assert v2.version == 2 and v2.status is ArtifactStatus.DRAFT


# ------------------------------------------------------- Agente 1 · brief


def test_brief_sin_senales_de_audiencia_bloquea():
    brief = ResearchBrief(
        artifact=ArtifactType.RESEARCH_BRIEF, created_by="agent_01",
        product=Product(name="X", category="y", core_benefit="beneficio real"),
        audience_signals=AudienceSignals(),
    )
    codes = {i.code for i in brief.blocking_issues()}
    assert "no_audience_data" in codes


def test_brief_con_beneficio_placeholder_bloquea():
    brief = ResearchBrief(
        artifact=ArtifactType.RESEARCH_BRIEF, created_by="agent_01",
        product=Product(name="X", category="y", core_benefit="por definir"),
        audience_signals=AudienceSignals(location="Guayaquil"),
    )
    assert "missing_core_benefit" in {i.code for i in brief.blocking_issues()}


def test_brief_sin_competencia_advierte_pero_no_bloquea():
    brief = ResearchBrief(
        artifact=ArtifactType.RESEARCH_BRIEF, created_by="agent_01",
        product=Product(name="X", category="y", core_benefit="beneficio real"),
        audience_signals=AudienceSignals(location="Guayaquil"),
    )
    codes = {i.code for i in brief.approval_check()}
    assert "no_competitors" in codes
    assert brief.can_be_approved()


# --------------------------------------------------- Agente 2 · estrategia


def _strategy(premisas: list[str]) -> Strategy:
    return Strategy(
        artifact=ArtifactType.STRATEGY, created_by="agent_02",
        awareness_level=AwarenessLevel.PROBLEM_AWARE,
        primary_pain="Organizar la fiesta consume semanas",
        primary_desire="Que salga bonita sin esfuerzo",
        objections=["precio", "confianza"],
        unique_mechanism="Montaje llave en mano en 3 horas",
        angles=[Angle(angle_id=f"A0{i+1}", name=f"Ángulo {i+1}", premise=p,
                      emotion="alivio", recommended_format="ugc")
                for i, p in enumerate(premisas)],
    )


def test_estrategia_exige_exactamente_tres_angulos():
    with pytest.raises(ValidationError):
        _strategy(["premisa uno diferente", "premisa dos diferente"])


def test_estrategia_detecta_angulos_disfrazados():
    """
    Tres ángulos que son el mismo con otras palabras: el fallo clásico.
    Se reporta como advertencia porque la similitud léxica es un indicio,
    y el humano elige el ángulo justo en este paso.
    """
    s = _strategy([
        "La mamá agotada que intenta organizar la fiesta completamente sola",
        "La mamá cansada que intenta organizar la fiesta totalmente sola",
        "Transformación visible del espacio antes y después del montaje",
    ])
    assert "angles_not_distinct" in {i.code for i in s.approval_check()}
    assert s.can_be_approved()   # no bloquea el pipeline


def test_estrategia_con_angulos_distintos_aprueba():
    s = _strategy([
        "La mamá agotada que intenta organizarlo todo sola",
        "Lo que nadie cuenta sobre contratar decoración barata",
        "Transformación visible del espacio antes y después",
    ])
    assert s.can_be_approved()


# ------------------------------------------------------- Agente 3 · hooks


def test_hooks_exige_minimo_ocho():
    with pytest.raises(ValidationError):
        Hooks(artifact=ArtifactType.HOOKS, created_by="agent_03",
              angle_id="A01", hooks=[_hook(i) for i in range(1, 5)])


def test_hooks_score_fuera_de_rango_es_rechazado():
    with pytest.raises(ValidationError):
        _scores(curiosidad=130)


def test_hooks_sin_tres_calificados_bloquea():
    hooks = Hooks(
        artifact=ArtifactType.HOOKS, created_by="agent_03", angle_id="A01",
        hooks=[_hook(1), _hook(2)] + [_hook(i, avg_high=False) for i in range(3, 11)],
    )
    assert "insufficient_quality_hooks" in {i.code for i in hooks.blocking_issues()}


def test_hooks_top3_del_mismo_tipo_bloquea():
    hooks = Hooks(
        artifact=ArtifactType.HOOKS, created_by="agent_03", angle_id="A01",
        hooks=[_hook(i, HookType.PROBLEMA) for i in range(1, 11)],
    )
    assert "top_hooks_same_type" in {i.code for i in hooks.blocking_issues()}


def test_hooks_variados_aprueban_y_se_ordenan():
    tipos = [HookType.PROBLEMA, HookType.CONFESION, HookType.CURIOSIDAD,
             HookType.CONTRARIAN, HookType.TESTIMONIAL, HookType.DEMOSTRACION,
             HookType.VISUAL, HookType.PROBLEMA]
    hooks = Hooks(
        artifact=ArtifactType.HOOKS, created_by="agent_03", angle_id="A01",
        hooks=[_hook(i + 1, t) for i, t in enumerate(tipos)],
    )
    assert hooks.can_be_approved()
    assert len(hooks.ranked()) == 8


# ------------------------------------------------------ Agente 4 · guion


def _script(total=35.0, target=35.0, roles=None) -> UGCScript:
    roles = roles or [ClipRole.HOOK, ClipRole.PROBLEMA, ClipRole.DEMOSTRACION,
                      ClipRole.CTA]
    step = total / len(roles)
    clips = [
        ScriptClip(clip_id=f"C{i+1:02d}", start=round(i * step, 2),
                   end=round((i + 1) * step, 2), role=r,
                   dialogue=f"Diálogo del clip {i+1}")
        for i, r in enumerate(roles)
    ]
    return UGCScript(
        artifact=ArtifactType.UGC_SCRIPT, created_by="agent_04", hook_id="H03",
        target_duration_sec=target, total_duration_sec=total, clips=clips,
        cta="Escríbenos por WhatsApp",
    )


def test_guion_rechaza_clips_discontinuos():
    with pytest.raises(ValidationError):
        UGCScript(
            artifact=ArtifactType.UGC_SCRIPT, created_by="agent_04", hook_id="H01",
            target_duration_sec=20, total_duration_sec=20,
            clips=[
                ScriptClip(clip_id="C01", start=0, end=5, role=ClipRole.HOOK,
                           dialogue="hola"),
                ScriptClip(clip_id="C02", start=9, end=20, role=ClipRole.CTA,
                           dialogue="chao"),   # hueco de 4 segundos
            ],
            cta="chao",
        )


def test_guion_rechaza_clip_con_tiempos_invertidos():
    with pytest.raises(ValidationError):
        ScriptClip(clip_id="C01", start=10, end=5, role=ClipRole.HOOK, dialogue="x")


def test_guion_fuera_de_tolerancia_bloquea():
    s = _script(total=50.0, target=35.0)
    assert "duration_out_of_range" in {i.code for i in s.blocking_issues()}


def test_guion_sin_cta_bloquea():
    s = _script(roles=[ClipRole.HOOK, ClipRole.PROBLEMA, ClipRole.RESULTADO])
    assert "missing_cta_clip" in {i.code for i in s.blocking_issues()}


def test_guion_valido_aprueba():
    assert _script().can_be_approved()


# ------------------------------------------------- Agente 5 · storyboard


def _storyboard(ids, script_ids=None, scenarios=None, product=True) -> Storyboard:
    scenarios = scenarios or ["sala de casa"] * len(ids)
    return Storyboard(
        artifact=ArtifactType.STORYBOARD, created_by="agent_05",
        script_clip_ids=script_ids or ids,
        clips=[StoryboardClip(clip_id=c, shot_type=ShotType.SELFIE,
                              scenario=s, action_summary="habla a cámara",
                              product_visible=(product and i == 0))
               for i, (c, s) in enumerate(zip(ids, scenarios))],
    )


def test_storyboard_detecta_clips_sin_cubrir():
    sb = _storyboard(["C01", "C02"], script_ids=["C01", "C02", "C03"])
    assert "clips_not_covered" in {i.code for i in sb.blocking_issues()}


def test_storyboard_detecta_clips_inventados():
    sb = _storyboard(["C01", "C02", "C09"], script_ids=["C01", "C02"])
    assert "clips_not_in_script" in {i.code for i in sb.blocking_issues()}


def test_storyboard_sin_producto_visible_bloquea():
    sb = _storyboard(["C01", "C02"], product=False)
    assert "product_never_visible" in {i.code for i in sb.blocking_issues()}


# --------------------------------------------- Agente 6 · character bible


def _bible(imperfections=None, face="ovalado, pómulos marcados") -> CharacterBible:
    return CharacterBible(
        artifact=ArtifactType.CHARACTER_BIBLE, created_by="agent_06",
        avatar_id="AV-FEMALE-EC-001", display_name="Sofía — mamá joven",
        physical=PhysicalTraits(age_range="31-34", origin="Ecuador", face=face,
                                hair="castaño oscuro, media melena",
                                skin="oliva clara", build="normal"),
        personality="amigable, ligeramente extrovertida",
        speech_style="conversacional, frases cortas",
        wardrobe_allowed=["camiseta blanca", "jeans"],
        wardrobe_forbidden=["ropa con branding visible"],
        natural_imperfections=imperfections if imperfections is not None else [
            "sonrisa asimétrica", "cejas naturales sin depilar", "ojeras leves",
        ],
    )


def test_bible_rechaza_avatar_id_mal_formado():
    with pytest.raises(ValidationError):
        CharacterBible(
            artifact=ArtifactType.CHARACTER_BIBLE, created_by="agent_06",
            avatar_id="sofia", display_name="Sofía",
            physical=PhysicalTraits(age_range="31", origin="EC", face="x",
                                    hair="y", skin="z", build="w"),
            personality="a", speech_style="b", wardrobe_allowed=["c"],
        )


def test_bible_con_rasgo_vago_bloquea():
    b = _bible(face="...")
    codes = {i.code for i in b.blocking_issues()}
    assert "vague_physical_trait" in codes


def test_bible_con_pocas_imperfecciones_bloquea():
    b = _bible(imperfections=["sonrisa asimétrica"])
    assert "insufficient_imperfections" in {i.code for i in b.blocking_issues()}


def test_bible_completa_aprueba():
    assert _bible().can_be_approved()


# ------------------------------------------- Agente 7 · prompt de imagen


def _image_prompt(anchored=True, text=None, imperfections=None) -> ImagePrompt:
    return ImagePrompt(
        artifact=ArtifactType.IMAGE_PROMPT, created_by="agent_07", clip_id="C01",
        avatar_id="AV-FEMALE-EC-001", template_code="NB_SELFIE_UGC",
        template_version=3, scene=SceneTemplate.SELFIE,
        prompt_text=text or ("Vertical smartphone selfie of the reference woman "
                             "in a living room, natural window light, casual"),
        identity_reference_used=anchored,
        imperfections_included=imperfections if imperfections is not None
        else ["slight asymmetric smile", "natural skin texture"],
        negative_constraints=["studio setup"],
    )


def test_prompt_imagen_sin_anclaje_de_identidad_bloquea():
    p = _image_prompt(anchored=False)
    assert "identity_not_anchored" in {i.code for i in p.blocking_issues()}


def test_prompt_imagen_con_lenguaje_de_comercial_bloquea():
    p = _image_prompt(text="Beautiful woman with perfect skin, cinematic "
                           "lighting, professional model, 8k masterpiece")
    assert "commercial_language" in {i.code for i in p.blocking_issues()}


def test_prompt_imagen_template_id_se_compone():
    assert _image_prompt().template_id == "NB_SELFIE_UGC_V3"


def test_prompt_imagen_valido_aprueba():
    assert _image_prompt().can_be_approved()


# -------------------------------------------- Agente 8 · prompt de video


def _blocks(**over) -> PromptBlocks:
    base = dict(
        camera="front smartphone camera, slight handheld movement",
        subject_action="looks into the lens while speaking casually",
        microgestures="natural blinking, small eyebrow movement, weight shift",
        performance="casual, unscripted feeling",
        physics="natural gravity on hair and clothing",
        product_constraint="product stays in frame, label readable",
        negative_behavior="avoid perfect posture, continuous eye contact, "
                          "exaggerated gestures, cinematic camera movement",
    )
    base.update(over)
    return PromptBlocks(**base)


def _video_prompt(**over) -> VideoPrompt:
    return VideoPrompt(
        artifact=ArtifactType.VIDEO_PROMPT, created_by="agent_08", clip_id="C01",
        image_asset_id="img_c01_v2", pattern_code="KL_TALKING_SELFIE",
        pattern_version=2, duration_sec=6.5, blocks=_blocks(**over),
    )


def test_prompt_video_bloque_vacio_bloquea():
    v = _video_prompt(microgestures="")
    assert "empty_block" in {i.code for i in v.blocking_issues()}


def test_prompt_video_restricciones_negativas_debiles_advierten():
    v = _video_prompt(negative_behavior="nada raro")
    codes = {i.code for i in v.approval_check()}
    assert "weak_negative_behavior" in codes
    assert v.can_be_approved()   # advertencia, no bloqueo


def test_prompt_video_rechaza_duracion_imposible():
    with pytest.raises(ValidationError):
        _video_prompt_duration = VideoPrompt(
            artifact=ArtifactType.VIDEO_PROMPT, created_by="agent_08",
            clip_id="C01", image_asset_id="x", pattern_code="KL_X",
            pattern_version=1, duration_sec=45, blocks=_blocks(),
        )


def test_prompt_video_se_renderiza_por_bloques():
    txt = _video_prompt().blocks.as_prompt()
    assert "[CAMERA]" in txt and "[AVOID]" in txt


# ------------------------------------------------------- Agente 9 · voz


def _voice(**over) -> VoiceDirection:
    base = dict(
        profile=VoiceProfile(language="es-EC", accent="ecuatoriano-neutro",
                             age_perception="27-34", pace=Pace.MEDIO_RAPIDO,
                             tone="conversacional con leve entusiasmo"),
        pauses_before=["nunca", "hasta que"],
        emphasis_words=["tres horas"],
        pacing_notes="Pausa breve antes del giro; acelera en la demostración "
                     "y frena en el cierre.",
        avoid=["entonación de locutor publicitario"],
    )
    base.update(over)
    return VoiceDirection(artifact=ArtifactType.VOICE_DIRECTION,
                          created_by="agent_09", clip_id="C01", **base)


def test_voz_sin_prohibir_locutor_bloquea():
    v = _voice(avoid=["gritar"])
    assert "no_announcer_guard" in {i.code for i in v.blocking_issues()}


def test_voz_con_notas_genericas_bloquea():
    v = _voice(pacing_notes="normal")
    assert "generic_pacing" in {i.code for i in v.blocking_issues()}


def test_voz_valida_aprueba():
    assert _voice().can_be_approved()


# ---------------------------------------------------- Agente 10 · edición


def _edit(order=None, expected=None, assembled=35.0) -> EditPlan:
    order = order or ["C01", "C02", "C03", "C04"]
    return EditPlan(
        artifact=ArtifactType.EDIT_PLAN, created_by="agent_10",
        clip_order=order, expected_clip_ids=expected or order,
        script_duration_sec=35.0, assembled_duration_sec=assembled,
        subtitles=True,
    )


def test_edicion_rechaza_clip_repetido():
    with pytest.raises(ValidationError):
        _edit(order=["C01", "C01", "C02"])


def test_edicion_detecta_clip_omitido():
    e = _edit(order=["C01", "C02"], expected=["C01", "C02", "C03"])
    assert "clips_missing_in_edit" in {i.code for i in e.blocking_issues()}


def test_edicion_detecta_deriva_de_duracion():
    e = _edit(assembled=50.0)
    assert "assembled_duration_drift" in {i.code for i in e.blocking_issues()}


# --------------------------------------------------- Agente 11 · auditor


def test_auditor_no_puede_rechazar_sin_ruta():
    """La regla central: rechazo sin responsable = regenerar todo."""
    with pytest.raises(ValidationError):
        AuditResult(
            artifact=ArtifactType.AUDIT_RESULT, created_by="agent_11",
            clip_id="C03", scores=_audit_scores(motion=40),
            realism_score=62, ad_score=70,
            decision=AuditDecision.REGENERATE, issue=None,
        )


def test_auditor_no_puede_enrutar_a_agente_equivocado():
    """Un problema de movimiento va al 8, no al guionista."""
    with pytest.raises(ValidationError):
        AuditIssue(category=IssueCategory.MOTION,
                   description="mano imposible", route_to_agent=4)


def test_tabla_de_enrutamiento_cubre_todas_las_categorias():
    assert set(ERROR_ROUTING) == set(IssueCategory)
    assert all(1 <= a <= 12 for a in ERROR_ROUTING.values())


def test_enrutamiento_identidad_va_al_arquitecto():
    issue = AuditIssue(category=IssueCategory.IDENTITY,
                       description="el rostro cambia entre C03 y C04",
                       route_to_agent=6)
    assert issue.route_to_agent == 6


def test_auditor_aprobado_bajo_umbral_es_bloqueado():
    """Los umbrales deterministas mandan sobre el juicio del agente."""
    a = AuditResult(
        artifact=ArtifactType.AUDIT_RESULT, created_by="agent_11", clip_id="C03",
        scores=_audit_scores(ugc_realism=50), realism_score=62, ad_score=70,
        decision=AuditDecision.APPROVED,
    )
    assert "approved_below_threshold" in {i.code for i in a.blocking_issues()}
    assert not a.can_be_approved()


def test_auditor_detecta_incoherencia_entre_eje_y_problema():
    a = AuditResult(
        artifact=ArtifactType.AUDIT_RESULT, created_by="agent_11", clip_id="C03",
        scores=_audit_scores(motion=45), realism_score=70, ad_score=70,
        decision=AuditDecision.REGENERATE,
        issue=AuditIssue(category=IssueCategory.VOICE,
                         description="voz publicitaria", route_to_agent=9),
    )
    assert "issue_axis_mismatch" in {i.code for i in a.approval_check()}


def test_auditor_supera_tope_de_ciclos():
    a = AuditResult(
        artifact=ArtifactType.AUDIT_RESULT, created_by="agent_11", clip_id="C03",
        cycle=4, scores=_audit_scores(motion=50), realism_score=68, ad_score=70,
        decision=AuditDecision.REGENERATE,
        issue=AuditIssue(category=IssueCategory.MOTION,
                         description="gesto imposible", route_to_agent=8),
    )
    assert "max_cycles_exceeded" in {i.code for i in a.blocking_issues()}


def test_auditor_aprobado_sobre_umbral_pasa():
    a = AuditResult(
        artifact=ArtifactType.AUDIT_RESULT, created_by="agent_11", clip_id="C03",
        scores=_audit_scores(), realism_score=88, ad_score=82,
        decision=AuditDecision.APPROVED,
    )
    assert a.meets_thresholds and a.can_be_approved()


# -------------------------------------------------- Agente 12 · analista


def _evidence(projects=3, impressions=50_000) -> Evidence:
    return Evidence(project_codes=[f"UGC-{i:04d}" for i in range(1, projects + 1)],
                    total_impressions=impressions, total_spend_usd=900.0)


def test_insight_alta_confianza_exige_evidencia_suficiente():
    with pytest.raises(ValidationError):
        Insight(text="Los hooks de confesión rinden mejor con mujeres 25-34",
                confidence=Confidence.ALTA, applies_to=["hook_type"],
                evidence=_evidence(projects=1, impressions=800))


def test_insight_baja_confianza_no_exige_evidencia():
    i = Insight(text="Parece que los primeros planos retienen mejor",
                confidence=Confidence.BAJA, applies_to=["shot_type"],
                evidence=_evidence(projects=1, impressions=500))
    assert i.confidence is Confidence.BAJA


def test_solo_insights_de_alta_confianza_llegan_a_memoria():
    learnings = CampaignLearnings(
        artifact=ArtifactType.CAMPAIGN_LEARNINGS, created_by="agent_12",
        project_code="UGC-0001",
        metrics=Metrics(impressions=52_000, ctr=0.021, hook_rate=0.34,
                        cpa=4.10, roas=3.2, spend_usd=900.0),
        insights=[
            Insight(text="Los hooks de confesión rinden mejor con mujeres 25-34",
                    confidence=Confidence.ALTA, applies_to=["hook_type"],
                    evidence=_evidence()),
            Insight(text="El avatar Sofía parece superar a Andrea",
                    confidence=Confidence.MEDIA, applies_to=["avatar_id"],
                    evidence=_evidence(projects=1, impressions=900)),
        ],
    )
    assert len(learnings.writable_to_memory()) == 1
    assert learnings.can_be_approved()


def test_muestra_pequena_bloquea_conclusiones():
    learnings = CampaignLearnings(
        artifact=ArtifactType.CAMPAIGN_LEARNINGS, created_by="agent_12",
        project_code="UGC-0002",
        metrics=Metrics(impressions=300, ctr=0.05, hook_rate=0.5, spend_usd=12.0),
        insights=[Insight(text="Este ángulo funciona muy bien siempre",
                          confidence=Confidence.MEDIA, applies_to=["angle_id"],
                          evidence=_evidence(projects=1, impressions=300))],
    )
    assert "sample_too_small" in {i.code for i in learnings.blocking_issues()}
