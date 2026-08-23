"""
Demo con proveedores reales: pipeline de dos clips, regeneración selectiva.

Genera imagen + video + voz de dos clips reales, luego simula que el
Auditor (Agente 11, llamada real a Claude) encuentra un defecto en UNO de
los clips y demuestra que **sólo ese clip se regenera** — la regla central
del sistema: no se rehace el video completo por un fallo puntual.

Costo estimado total: ~$1.75 (1 imagen de referencia + 2 clips completos +
1 regeneración de video). Pide confirmación antes de gastar.

    python demo_pipeline_multiclip.py

Requiere ANTHROPIC_API_KEY y FAL_KEY en .env.
"""

from __future__ import annotations

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

faltan = [k for k in ("ANTHROPIC_API_KEY", "FAL_KEY") if not os.getenv(k)]
if faltan:
    sys.exit(f"Falta configurar en .env: {', '.join(faltan)}")

from app.agents import AuditorAgent
from app.contracts import (
    AuditDecision,
    CharacterBible,
    EditPlan,
    ImagePrompt,
    IssueCategory,
    Pace,
    PhysicalTraits,
    PromptBlocks,
    SceneTemplate,
    VideoPrompt,
    VoiceDirection,
    VoiceProfile,
)
from app.gateway import AIGateway
from app.gateway.providers.anthropic_provider import AnthropicProvider
from app.gateway.providers.fal_provider import FalImageProvider
from app.gateway.providers.fal_video_provider import FalVideoProvider
from app.gateway.providers.fal_voice_provider import FalVoiceProvider
from app.orchestrator import route_correction
from app.services import (
    AudioGenerationService,
    AvatarLibrary,
    ImageGenerationService,
    JobQueue,
    VideoGenerationService,
    get_by_name,
)

LINE = "─" * 72
PROJECT_CODE = "DEMO-MULTICLIP"

COSTO_ESTIMADO = 0.15 + (0.15 + 0.42 + 0.01) * 2 + 0.02 + 0.42
print(f"{LINE}\nDemo de pipeline con proveedores reales — 2 clips\n{LINE}")
print(f"Costo estimado total: ${COSTO_ESTIMADO:.2f}")
print("(1 imagen de referencia + 2 clips completos con imagen/video/voz +")
print(" 1 llamada al Auditor + 1 regeneración selectiva de video)\n")
if input("¿Continuar? [s/N] ").strip().lower() != "s":
    print("Cancelado. No se hizo ninguna llamada.")
    sys.exit(0)

# ── Servicios ──────────────────────────────────────────────────────────
gw = AIGateway(provider=AnthropicProvider())
avatar_lib = AvatarLibrary()
img_svc = ImageGenerationService(provider=FalImageProvider())
video_svc = VideoGenerationService(queue=JobQueue(provider=FalVideoProvider()))
audio_svc = AudioGenerationService(provider=FalVoiceProvider())

DANIELA = get_by_name("Daniela")

# ── Personaje (construido a mano en este demo — normalmente lo produce el
# Agente 6; se omite esa llamada aquí para mantener el costo enfocado en la
# generación de medios, que es lo que este demo quiere probar) ──────────
bible = CharacterBible(
    artifact="character_bible", created_by="demo", avatar_id="AV-DEMO-EC-001",
    display_name="Karol — asesora Seytu",
    physical=PhysicalTraits(
        age_range="30-34", origin="Ecuador / Guayaquil",
        face="ovalado, pómulos marcados, mentón suave",
        hair="castaño oscuro, media melena, raya al lado",
        skin="oliva clara, textura y poros visibles", build="normal",
    ),
    personality="cercana, habla como recomendando a una amiga",
    speech_style="frases cortas, conversacional",
    wardrobe_allowed=["camiseta blanca", "cárdigan gris"],
    wardrobe_forbidden=["branding visible", "ropa de pasarela"],
    natural_imperfections=["sonrisa ligeramente asimétrica",
                           "mechón que se sale", "ojeras leves"],
)
avatar_lib.save(bible)

print(f"\n{LINE}\n1 · Imagen de referencia (ancla la identidad)\n{LINE}")
ref_prompt = ImagePrompt(
    artifact="image_prompt", created_by="demo", avatar_id=bible.avatar_id,
    template_code="NB_CHARACTER_CREATION", template_version=1,
    scene=SceneTemplate.CHARACTER_CREATION,
    prompt_text=("Vertical smartphone photo of a Latin American woman in "
                "her early 30s, front-facing, neutral living room "
                "background, natural window light, casual expression"),
    identity_reference_used=False,   # es la primera imagen; no hay a qué anclar
    imperfections_included=["visible skin texture", "flyaway hair strand"],
    negative_constraints=["studio lighting", "empty background"],
)
ref_assets = img_svc.generate(ref_prompt, project_code=PROJECT_CODE, n_variants=1)
ref_url = ref_assets[0].storage_url
img_svc.select(ref_assets[0].id)
avatar_lib.add_reference(bible.avatar_id, "frontal", ref_url)
print(f"  ✓ Referencia generada: {ref_url}")
print(f"  Costo: ${ref_assets[0].cost_usd:.4f}")


def generar_clip(clip_id: str, dialogo: str, accion: str) -> dict:
    """Imagen anclada en la referencia → video → voz, para un clip."""
    print(f"\n{LINE}\nClip {clip_id}\n{LINE}")

    img_prompt = ImagePrompt(
        artifact="image_prompt", created_by="demo", clip_id=clip_id,
        avatar_id=bible.avatar_id, template_code="NB_SELFIE_UGC",
        template_version=1, scene=SceneTemplate.SELFIE,
        prompt_text=(f"The reference woman, {accion}, vertical smartphone "
                    f"selfie framing, natural light"),
        identity_reference_used=True,
        imperfections_included=["visible skin texture", "flyaway hair strand"],
        negative_constraints=["studio setup", "empty background"],
    )
    img_assets = img_svc.generate(
        img_prompt, project_code=PROJECT_CODE,
        reference_urls=avatar_lib.references(bible.avatar_id), n_variants=1)
    img_svc.select(img_assets[0].id)
    print(f"  ✓ Imagen: {img_assets[0].storage_url}  (${img_assets[0].cost_usd:.4f})")

    video_prompt = VideoPrompt(
        artifact="video_prompt", created_by="demo", clip_id=clip_id,
        image_asset_id=img_assets[0].id, pattern_code="KL_TALKING_SELFIE",
        pattern_version=1, duration_sec=5.0,
        blocks=PromptBlocks(
            camera="front smartphone camera, slight handheld movement",
            subject_action=f"{accion}, briefly looks away then back",
            microgestures="natural blinking, small eyebrow movement",
            performance="casual, unscripted feeling",
            physics="natural gravity on hair and clothing",
            product_constraint="",
            negative_behavior=("avoid perfect posture, continuous eye "
                              "contact, exaggerated gestures, cinematic "
                              "camera movement"),
        ),
    )
    job = video_svc.submit(video_prompt, project_code=PROJECT_CODE,
                           image_asset=img_assets[0])
    print(f"  Video encolado, esperando (~1-3 min)...")
    video_asset = video_svc.wait_and_collect(job)
    if video_asset is None:
        job_final = video_svc.queue.wait(job.id)
        print(f"  ✗ Video falló: {job_final.error_message}")
        video_asset = None
    else:
        video_svc.select(video_asset.id)
        print(f"  ✓ Video: {video_asset.storage_url}  (${video_asset.cost_usd:.4f})")

    direction = VoiceDirection(
        artifact="voice_direction", created_by="demo", clip_id=clip_id,
        profile=VoiceProfile(language="es-419", accent="latinoamericano-neutro",
                             age_perception="30-34", pace=Pace.MEDIO_RAPIDO,
                             tone="conversacional, cercana",
                             voice_id=DANIELA.voice_id),
        pauses_before=["cajón"], emphasis_words=[],
        pacing_notes=("Ritmo natural, pausa breve antes de la palabra clave, "
                     "sin entonación de anuncio."),
        avoid=["entonación de locutor publicitario"],
    )
    audio_asset = audio_svc.generate(direction, text=dialogo,
                                     project_code=PROJECT_CODE)
    print(f"  ✓ Voz: {audio_asset.storage_url}  (${audio_asset.cost_usd:.4f})")

    return {"clip_id": clip_id, "image": img_assets[0], "video": video_asset,
           "audio": audio_asset, "video_prompt": video_prompt,
           "dialogo": dialogo}


clip_c01 = generar_clip("C01", "Tengo un cajón entero de bases que nunca usé",
                        "holding up a makeup drawer to show it to the camera")
clip_c02 = generar_clip("C02", "Escríbele a Karol por WhatsApp",
                        "smiling and waving at the camera")

# ── Auditoría real de C02 ────────────────────────────────────────────
print(f"\n{LINE}\n3 · El Auditor revisa el clip C02 (llamada real)\n{LINE}")
edit_plan = EditPlan(
    artifact="edit_plan", created_by="demo",
    clip_order=["C01", "C02"], expected_clip_ids=["C01", "C02"],
    script_duration_sec=10.0, assembled_duration_sec=10.0, subtitles=True,
)
auditor = AuditorAgent()
audit = auditor.run(gw, ("C02", edit_plan, 1,
    "En este clip, la mano derecha del personaje hace un gesto que parece "
    "atravesar brevemente el propio brazo, un movimiento poco natural. El "
    "resto del clip — identidad, voz, producto — se ve correcto."))

print(f"  Decisión: {audit.decision.value}")
print(f"  Realismo: {audit.realism_score}  ·  Anuncio: {audit.ad_score}")

if audit.decision == AuditDecision.APPROVED:
    print("\n  El Auditor aprobó el clip pese a la descripción del defecto.")
    print("  No hay nada que regenerar — el demo termina aquí.")
else:
    ruta = route_correction(audit.issue.category, clip_id="C02",
                            description=audit.issue.description)
    print(f"\n  Problema: {audit.issue.category.value}")
    print(f"  Ruta de corrección: {ruta.as_path()}")
    print(f"  Etapas a regenerar: {ruta.regenerations} de 12 posibles")

    print(f"\n{LINE}\n4 · Regenerando SÓLO lo que la ruta indica\n{LINE}")
    costo_antes = sum(a.cost_usd for a in video_svc.assets)

    if 8 in ruta.chain:   # el video es la única etapa con crédito en este caso
        nuevo_job = video_svc.submit(clip_c02["video_prompt"],
                                     project_code=PROJECT_CODE,
                                     image_asset=clip_c02["image"], seed=99)
        nuevo_video = video_svc.wait_and_collect(nuevo_job)
        if nuevo_video:
            video_svc.select(nuevo_video.id)
            print(f"  ✓ Video de C02 regenerado: {nuevo_video.storage_url}")
            print(f"  Costo de la regeneración: ${nuevo_video.cost_usd:.4f}")

    costo_regeneracion = sum(a.cost_usd for a in video_svc.assets) - costo_antes

    print(f"\n{LINE}\nCOMPARACIÓN DE COSTO\n{LINE}")
    costo_c01_completo = (clip_c01["image"].cost_usd
                          + (clip_c01["video"].cost_usd if clip_c01["video"] else 0)
                          + clip_c01["audio"].cost_usd)
    costo_c02_completo = (clip_c02["image"].cost_usd
                          + (clip_c02["video"].cost_usd if clip_c02["video"] else 0)
                          + clip_c02["audio"].cost_usd)
    costo_regenerar_todo = costo_c01_completo + costo_c02_completo
    print(f"  Costo de rehacer AMBOS clips completos: ${costo_regenerar_todo:.4f}")
    print(f"  Costo de regenerar SÓLO el video de C02: ${costo_regeneracion:.4f}")
    ahorro = costo_regenerar_todo - costo_regeneracion
    if costo_regenerar_todo > 0:
        print(f"  Ahorro real de esta corrección: ${ahorro:.4f} "
             f"({ahorro / costo_regenerar_todo * 100:.0f}% menos)")
    else:
        print(f"  Ahorro real de esta corrección: ${ahorro:.4f}")

print(f"\n{LINE}")
total = (img_svc.spent_by_project.get(PROJECT_CODE, 0)
        + video_svc.cost_report(PROJECT_CODE)["project_usd"]
        + audio_svc.cost_report(PROJECT_CODE)["project_usd"])
print(f"COSTO TOTAL DE ESTA DEMO: ${total:.4f}")
print(LINE)
