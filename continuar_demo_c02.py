"""
Continúa el demo desde donde quedó, sin repetir lo ya pagado.

Usa esto cuando `demo_pipeline_multiclip.py` se interrumpió (por ejemplo,
por un corte de red) después de generar el video de C02 pero antes de
terminar: genera la voz de C02 si falta, corre el Auditor, y regenera
selectivamente si hace falta — sin volver a tocar C01 ni la referencia,
que ya están guardados en la base de datos.

    python continuar_demo_c02.py

Requiere que ya exista el proyecto 'DEMO-MULTICLIP' en la base de datos
(creado por una corrida anterior de demo_pipeline_multiclip.py).
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
    EditPlan,
    Pace,
    VoiceDirection,
    VoiceProfile,
)
from app.db import (
    ArtifactRepository,
    AssetRepository,
    ClipAuditRepository,
    ClipRepository,
    ProjectRepository,
    RunRepository,
    engine_for,
    session_factory,
)
from app.gateway import AIGateway
from app.gateway.providers.anthropic_provider import AnthropicProvider
from app.gateway.providers.fal_video_provider import FalVideoProvider
from app.gateway.providers.fal_voice_provider import FalVoiceProvider
from app.orchestrator import route_correction
from app.services import Asset as ServiceAsset
from app.services import AudioGenerationService, JobQueue, VideoGenerationService, get_by_name

LINE = "─" * 72
PROJECT_CODE = "DEMO-MULTICLIP"

print(f"{LINE}\nContinuando el demo — sólo C02, sin tocar C01\n{LINE}")
print("Costo estimado: ~$0.02 (voz + Auditor). Si el Auditor pide")
print("regenerar el video, se preguntará por separado (~$0.42 más).\n")
if input("¿Continuar? [s/N] ").strip().lower() != "s":
    sys.exit("Cancelado.")

engine = engine_for()
session = session_factory(engine)()
project_repo = ProjectRepository(session)
clip_repo = ClipRepository(session)
artifact_repo = ArtifactRepository(session)
asset_repo = AssetRepository(session)
audit_repo = ClipAuditRepository(session)
run_repo = RunRepository(session)

project = project_repo.by_code(PROJECT_CODE)
if project is None:
    sys.exit(f"No existe el proyecto {PROJECT_CODE}. Corre primero "
             f"demo_pipeline_multiclip.py.")
clip_c02_row = clip_repo.by_code(project.id, "C02")
if clip_c02_row is None:
    sys.exit("No existe el clip C02 en este proyecto.")

img_row = asset_repo.selected_for(project.id, clip_c02_row.id, "image")
if img_row is None:
    sys.exit("C02 no tiene imagen guardada — hay que correr el demo completo "
             "desde el principio.")

# Puente entre lo guardado en la base y el objeto en memoria que los
# servicios de generación esperan (mismo patrón que usan internamente,
# reconstruido aquí a partir de lo ya persistido).
image_asset = ServiceAsset(
    project_code=PROJECT_CODE, clip_id="C02", kind="image",
    version=img_row.version, storage_url=img_row.storage_url,
    provider=img_row.provider or "fal_nano_banana_pro", is_selected=True,
)

gw = AIGateway(provider=AnthropicProvider())
video_svc = VideoGenerationService(queue=JobQueue(provider=FalVideoProvider()))
audio_svc = AudioGenerationService(provider=FalVoiceProvider())
DANIELA = get_by_name("Daniela")

# ── Voz de C02, si falta ──────────────────────────────────────────────
audio_row = asset_repo.selected_for(project.id, clip_c02_row.id, "audio")
if audio_row is not None:
    print(f"\n  La voz de C02 ya estaba guardada: {audio_row.storage_url}")
else:
    print(f"\n{LINE}\nVoz de C02\n{LINE}")
    direction = VoiceDirection(
        artifact="voice_direction", created_by="demo", clip_id="C02",
        profile=VoiceProfile(language="es-419", accent="latinoamericano-neutro",
                             age_perception="30-34", pace=Pace.MEDIO_RAPIDO,
                             tone="conversacional, cercana",
                             voice_id=DANIELA.voice_id),
        pauses_before=["cajón"], emphasis_words=[],
        pacing_notes=("Ritmo natural, pausa breve antes de la palabra clave, "
                     "sin entonación de anuncio."),
        avoid=["entonación de locutor publicitario"],
    )
    direction_row = artifact_repo.create_version(project.id, direction,
                                                 clip_id=clip_c02_row.id)
    audio_asset = audio_svc.generate(direction, text=clip_c02_row.dialogue,
                                     project_code=PROJECT_CODE)
    artifact_repo.approve(direction_row.id)
    asset_repo.create(project_id=project.id, clip_id=clip_c02_row.id,
                      kind="audio", storage_url=audio_asset.storage_url,
                      provider=audio_asset.provider, cost_usd=audio_asset.cost_usd,
                      duration_sec=audio_asset.duration_sec,
                      source_artifact_id=direction_row.id, is_selected=True)
    session.commit()
    print(f"  ✓ Voz: {audio_asset.storage_url}  (${audio_asset.cost_usd:.4f})")

# ── Auditoría real de C02 ────────────────────────────────────────────
print(f"\n{LINE}\nEl Auditor revisa el clip C02 (llamada real)\n{LINE}")
edit_plan = EditPlan(
    artifact="edit_plan", created_by="demo",
    clip_order=["C01", "C02"], expected_clip_ids=["C01", "C02"],
    script_duration_sec=10.0, assembled_duration_sec=10.0, subtitles=True,
)
antes = len(gw.runs)
auditor = AuditorAgent()
audit = auditor.run(gw, ("C02", edit_plan, 1,
    "En este clip, la mano derecha del personaje hace un gesto que parece "
    "atravesar brevemente el propio brazo, un movimiento poco natural. El "
    "resto del clip — identidad, voz, producto — se ve correcto."))

for r in gw.runs[antes:]:
    run_repo.record(project.id, r, clip_id=clip_c02_row.id)
audit_row = artifact_repo.create_version(project.id, audit, clip_id=clip_c02_row.id)
artifact_repo.approve(audit_row.id)
audit_repo.record(clip_c02_row.id, audit)
project_repo.add_cost(project.id, gw.total_cost())
session.commit()

print(f"  Decisión: {audit.decision.value}")
print(f"  Realismo: {audit.realism_score}  ·  Anuncio: {audit.ad_score}")

if audit.decision == AuditDecision.APPROVED:
    print("\n  El Auditor aprobó el clip. El video recuperado se queda como está.")
else:
    ruta = route_correction(audit.issue.category, clip_id="C02",
                            description=audit.issue.description)
    print(f"\n  Problema: {audit.issue.category.value}")
    print(f"  Ruta de corrección: {ruta.as_path()}")

    if 8 in ruta.chain:
        video_row = asset_repo.selected_for(project.id, clip_c02_row.id, "video")
        print(f"\n  El video actual de C02 (recuperado tras el corte de red)")
        print(f"  costó $0.4200. Regenerarlo cuesta otros ~$0.42.")
        if input("  ¿Regenerar de todas formas? [s/N] ").strip().lower() == "s":
            from app.contracts import PromptBlocks, VideoPrompt
            video_prompt = VideoPrompt(
                artifact="video_prompt", created_by="demo", clip_id="C02",
                image_asset_id=img_row.id, pattern_code="KL_TALKING_SELFIE",
                pattern_version=1, duration_sec=5.0,
                blocks=PromptBlocks(
                    camera="front smartphone camera, slight handheld movement",
                    subject_action="smiling and waving at the camera, briefly "
                                   "looks away then back",
                    microgestures="natural blinking, small eyebrow movement",
                    performance="casual, unscripted feeling",
                    physics="natural gravity on hair and clothing",
                    product_constraint="",
                    negative_behavior=("avoid perfect posture, continuous eye "
                                      "contact, exaggerated gestures, "
                                      "cinematic camera movement"),
                ),
            )
            prompt_row = artifact_repo.create_version(project.id, video_prompt,
                                                       clip_id=clip_c02_row.id)
            job = video_svc.submit(video_prompt, project_code=PROJECT_CODE,
                                   image_asset=image_asset, seed=99)
            print("  Video encolado, esperando (~1-3 min)...")
            nuevo_video = video_svc.wait_and_collect(job)
            if nuevo_video:
                artifact_repo.approve(prompt_row.id)
                asset_repo.create(
                    project_id=project.id, clip_id=clip_c02_row.id, kind="video",
                    storage_url=nuevo_video.storage_url, provider=nuevo_video.provider,
                    cost_usd=nuevo_video.cost_usd, duration_sec=nuevo_video.duration_sec,
                    source_artifact_id=prompt_row.id, is_selected=True)
                project_repo.add_cost(project.id, nuevo_video.cost_usd)
                print(f"  ✓ Video regenerado: {nuevo_video.storage_url}")
            else:
                artifact_repo.reject(prompt_row.id)
                print("  ✗ La regeneración también falló; el video recuperado sigue")
                print("    siendo el seleccionado.")
            session.commit()
        else:
            print("  Se mantiene el video ya recuperado.")

print(f"\n{LINE}")
project = project_repo.by_code(PROJECT_CODE)
print(f"Costo total acumulado del proyecto: ${project.total_cost_usd:.4f}")
print(LINE)
session.close()
