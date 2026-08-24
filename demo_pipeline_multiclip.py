"""
Demo con proveedores reales y persistencia: pipeline de dos clips.

Genera imagen + video + voz de dos clips reales, simula que el Auditor
(Agente 11, llamada real a Claude) encuentra un defecto en UNO de los
clips, regenera SÓLO ese clip — y guarda cada paso en Postgres: proyecto,
clips, artefactos versionados, assets, la traza de cada llamada al modelo
y la auditoría estructurada.

Se hace `commit()` después de cada paso, no al final: si algo real ya se
generó y se pagó, no debe perderse de la base sólo porque un paso
posterior falla.

Costo estimado total: ~$1.75. Pide confirmación antes de gastar.

    python demo_pipeline_multiclip.py

Requiere ANTHROPIC_API_KEY, FAL_KEY y DATABASE_URL (o el valor por
defecto del docker-compose) en .env.
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
    Pace,
    PhysicalTraits,
    PromptBlocks,
    SceneTemplate,
    VideoPrompt,
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
    create_all,
    engine_for,
    session_factory,
)
from app.gateway import AIGateway
from app.gateway.providers.anthropic_provider import AnthropicProvider
from app.gateway.providers.fal_provider import FalImageProvider
from app.gateway.providers.fal_video_provider import FalVideoProvider
from app.gateway.providers.fal_voice_provider import FalVoiceProvider
from app.orchestrator import route_correction
from app.services import Asset as ServiceAsset
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
print(" 1 llamada al Auditor + 1 regeneración selectiva de video)")
print("Esta vez, además, cada paso se guarda en la base de datos.\n")
if input("¿Continuar? [s/N] ").strip().lower() != "s":
    print("Cancelado. No se hizo ninguna llamada.")
    sys.exit(0)

# ── Base de datos ─────────────────────────────────────────────────────
# create_all() es idempotente: si las tablas ya existen (por alembic),
# no hace nada; sirve de red de seguridad si se corre contra una base
# nueva sin haber migrado.
engine = engine_for()
create_all(engine)
session = session_factory(engine)()

project_repo = ProjectRepository(session)
clip_repo = ClipRepository(session)
artifact_repo = ArtifactRepository(session)
asset_repo = AssetRepository(session)
audit_repo = ClipAuditRepository(session)
run_repo = RunRepository(session)

project = project_repo.by_code(PROJECT_CODE)
if project is None:
    project = project_repo.create(code=PROJECT_CODE, brand_name="Karol Salud y Cosmética",
                                  product_name="Seytu")
session.commit()
print(f"Proyecto en base de datos: {project.code} (id {project.id})")

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
bible_row = artifact_repo.create_version(project.id, bible)
artifact_repo.approve(bible_row.id)
session.commit()

print(f"\n{LINE}\n1 · Imagen de referencia (ancla la identidad)\n{LINE}")

# Reanudable: si esta base de datos ya tiene una referencia guardada para
# este avatar (de una corrida anterior), se reutiliza en vez de pagar por
# generar otra igual. Es lo mismo que continuar_demo_c02.py hace a mano,
# aplicado aquí a todo el pipeline.
ref_row_existente = asset_repo.selected_for(project.id, None, "image")
if ref_row_existente is not None:
    ref_url = ref_row_existente.storage_url
    avatar_lib.add_reference(bible.avatar_id, "frontal", ref_url)
    print(f"  ✓ Referencia ya existía, reutilizada: {ref_url}")
    print(f"  Costo: $0.0000 (reutilizada, no se generó de nuevo)")
else:
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
    ref_prompt_row = artifact_repo.create_version(project.id, ref_prompt,
                                                  input_ref=bible_row.id)

    ref_assets = img_svc.generate(ref_prompt, project_code=PROJECT_CODE, n_variants=1)
    ref_url = ref_assets[0].storage_url
    img_svc.select(ref_assets[0].id)
    avatar_lib.add_reference(bible.avatar_id, "frontal", ref_url)

    artifact_repo.approve(ref_prompt_row.id)
    asset_repo.create(project_id=project.id, clip_id=None, kind="image",
                      storage_url=ref_url, provider=ref_assets[0].provider,
                      cost_usd=ref_assets[0].cost_usd,
                      source_artifact_id=ref_prompt_row.id, is_selected=True)
    session.commit()
    print(f"  ✓ Referencia generada: {ref_url}")
    print(f"  Costo: ${ref_assets[0].cost_usd:.4f}")


def generar_clip(clip_row, dialogo: str, accion: str) -> dict:
    """
    Imagen anclada en la referencia → video → voz, persistiendo cada paso.

    Reanudable: antes de cada sub-paso (imagen, video, voz) revisa si este
    clip ya tiene un asset seleccionado de ese tipo en la base de datos. Si
    lo tiene, lo reutiliza y no gasta de nuevo — así una corrida repetida
    del demo (por pruebas, por un corte de red, etc.) sólo paga por lo que
    de verdad falta.
    """
    clip_id = clip_row.code
    print(f"\n{LINE}\nClip {clip_id}\n{LINE}")

    # -- imagen --
    img_row_existente = asset_repo.selected_for(project.id, clip_row.id, "image")
    if img_row_existente is not None:
        img_asset = ServiceAsset(
            project_code=PROJECT_CODE, clip_id=clip_id, kind="image",
            version=img_row_existente.version,
            storage_url=img_row_existente.storage_url,
            provider=img_row_existente.provider or "fal_nano_banana_pro",
            is_selected=True)
        print(f"  ✓ Imagen ya existía, reutilizada: {img_asset.storage_url}  ($0.0000)")
    else:
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
        img_prompt_row = artifact_repo.create_version(project.id, img_prompt,
                                                      clip_id=clip_row.id)
        img_assets = img_svc.generate(
            img_prompt, project_code=PROJECT_CODE,
            reference_urls=avatar_lib.references(bible.avatar_id), n_variants=1)
        img_svc.select(img_assets[0].id)
        img_asset = img_assets[0]

        artifact_repo.approve(img_prompt_row.id)
        asset_repo.create(
            project_id=project.id, clip_id=clip_row.id, kind="image",
            storage_url=img_asset.storage_url, provider=img_asset.provider,
            cost_usd=img_asset.cost_usd, source_artifact_id=img_prompt_row.id,
            is_selected=True)
        session.commit()
        print(f"  ✓ Imagen: {img_asset.storage_url}  (${img_asset.cost_usd:.4f})")

    # -- video --
    video_row_existente = asset_repo.selected_for(project.id, clip_row.id, "video")
    video_prompt = VideoPrompt(
        artifact="video_prompt", created_by="demo", clip_id=clip_id,
        image_asset_id=img_asset.id, pattern_code="KL_TALKING_SELFIE",
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
    if video_row_existente is not None:
        video_asset = ServiceAsset(
            project_code=PROJECT_CODE, clip_id=clip_id, kind="video",
            version=video_row_existente.version,
            storage_url=video_row_existente.storage_url,
            provider=video_row_existente.provider or "fal_kling_v3_standard",
            duration_sec=video_row_existente.duration_sec, is_selected=True)
        print(f"  ✓ Video ya existía, reutilizado: {video_asset.storage_url}  ($0.0000)")
    else:
        video_prompt_row = artifact_repo.create_version(
            project.id, video_prompt, clip_id=clip_row.id,
            input_ref=None)

        job = video_svc.submit(video_prompt, project_code=PROJECT_CODE,
                               image_asset=img_asset)
        print(f"  Video encolado, esperando (~1-3 min)...")
        video_asset = video_svc.wait_and_collect(job)

        if video_asset is None:
            job_final = video_svc.queue.wait(job.id)
            print(f"  ✗ Video falló: {job_final.error_message}")
            artifact_repo.reject(video_prompt_row.id)
        else:
            video_svc.select(video_asset.id)
            artifact_repo.approve(video_prompt_row.id)
            asset_repo.create(
                project_id=project.id, clip_id=clip_row.id, kind="video",
                storage_url=video_asset.storage_url, provider=video_asset.provider,
                cost_usd=video_asset.cost_usd, duration_sec=video_asset.duration_sec,
                source_artifact_id=video_prompt_row.id, is_selected=True)
            print(f"  ✓ Video: {video_asset.storage_url}  (${video_asset.cost_usd:.4f})")
        session.commit()

    # -- voz --
    audio_row_existente = asset_repo.selected_for(project.id, clip_row.id, "audio")
    if audio_row_existente is not None:
        audio_asset = ServiceAsset(
            project_code=PROJECT_CODE, clip_id=clip_id, kind="audio",
            version=audio_row_existente.version,
            storage_url=audio_row_existente.storage_url,
            provider=audio_row_existente.provider or "fal_elevenlabs_multilingual_v2",
            duration_sec=audio_row_existente.duration_sec, is_selected=True)
        print(f"  ✓ Voz ya existía, reutilizada: {audio_asset.storage_url}  ($0.0000)")
    else:
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
        direction_row = artifact_repo.create_version(project.id, direction,
                                                     clip_id=clip_row.id)
        audio_asset = audio_svc.generate(direction, text=dialogo,
                                         project_code=PROJECT_CODE)

        artifact_repo.approve(direction_row.id)
        asset_repo.create(
            project_id=project.id, clip_id=clip_row.id, kind="audio",
            storage_url=audio_asset.storage_url, provider=audio_asset.provider,
            cost_usd=audio_asset.cost_usd, duration_sec=audio_asset.duration_sec,
            source_artifact_id=direction_row.id, is_selected=True)
        session.commit()
        print(f"  ✓ Voz: {audio_asset.storage_url}  (${audio_asset.cost_usd:.4f})")

    return {"clip_id": clip_id, "clip_row": clip_row, "image": img_asset,
           "video": video_asset, "audio": audio_asset,
           "video_prompt": video_prompt, "dialogo": dialogo}


clip_c01_row = clip_repo.get_or_create(
    project.id, "C01", sequence_order=1, role="hook",
    dialogue="Tengo un cajón entero de bases que nunca usé")
clip_c02_row = clip_repo.get_or_create(
    project.id, "C02", sequence_order=2, role="cta",
    dialogue="Escríbele a Karol por WhatsApp")
session.commit()

clip_c01 = generar_clip(clip_c01_row, clip_c01_row.dialogue,
                        "holding up a makeup drawer to show it to the camera")
clip_c02 = generar_clip(clip_c02_row, clip_c02_row.dialogue,
                        "smiling and waving at the camera")

# ── Auditoría real de C02 ────────────────────────────────────────────
print(f"\n{LINE}\n3 · El Auditor revisa el clip C02 (llamada real)\n{LINE}")
edit_plan = EditPlan(
    artifact="edit_plan", created_by="demo",
    clip_order=["C01", "C02"], expected_clip_ids=["C01", "C02"],
    script_duration_sec=10.0, assembled_duration_sec=10.0, subtitles=True,
)
edit_plan_row = artifact_repo.create_version(project.id, edit_plan)
artifact_repo.approve(edit_plan_row.id)

antes_de_auditar = len(gw.runs)
auditor = AuditorAgent()
audit = auditor.run(gw, ("C02", edit_plan, 1,
    "En este clip, la mano derecha del personaje hace un gesto que parece "
    "atravesar brevemente el propio brazo, un movimiento poco natural. El "
    "resto del clip — identidad, voz, producto — se ve correcto."))

# La traza de la llamada al Auditor, atribuida al clip que evaluó.
for r in gw.runs[antes_de_auditar:]:
    run_repo.record(project.id, r, clip_id=clip_c02_row.id)

audit_row = artifact_repo.create_version(project.id, audit,
                                         clip_id=clip_c02_row.id,
                                         input_ref=edit_plan_row.id)
artifact_repo.approve(audit_row.id)
audit_repo.record(clip_c02_row.id, audit)
session.commit()

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
        # El video_prompt anterior de C02 (ya sea de esta corrida o de una
        # previa reutilizada) es el padre de linaje de la regeneración.
        video_prompt_previo = artifact_repo.latest(project.id, "video_prompt",
                                                    clip_id=clip_c02_row.id)
        nuevo_prompt_row = artifact_repo.create_version(
            project.id, clip_c02["video_prompt"], clip_id=clip_c02_row.id,
            input_ref=video_prompt_previo.id if video_prompt_previo else None)

        nuevo_job = video_svc.submit(clip_c02["video_prompt"],
                                     project_code=PROJECT_CODE,
                                     image_asset=clip_c02["image"], seed=99)
        nuevo_video = video_svc.wait_and_collect(nuevo_job)
        if nuevo_video:
            video_svc.select(nuevo_video.id)
            artifact_repo.approve(nuevo_prompt_row.id)
            asset_repo.create(
                project_id=project.id, clip_id=clip_c02_row.id, kind="video",
                storage_url=nuevo_video.storage_url, provider=nuevo_video.provider,
                cost_usd=nuevo_video.cost_usd, duration_sec=nuevo_video.duration_sec,
                source_artifact_id=nuevo_prompt_row.id, is_selected=True)
            print(f"  ✓ Video de C02 regenerado: {nuevo_video.storage_url}")
            print(f"  Costo de la regeneración: ${nuevo_video.cost_usd:.4f}")
        else:
            artifact_repo.reject(nuevo_prompt_row.id)
        session.commit()

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

# ── Trazas del gateway restantes (antes del Auditor no hubo llamadas en
# este demo, ya que el guion/estrategia se construyeron a mano) ─────────
run_repo.record_all(project.id, [r for r in gw.runs[:antes_de_auditar]])
project_repo.add_cost(project.id, gw.total_cost())
session.commit()

print(f"\n{LINE}")
total = (img_svc.spent_by_project.get(PROJECT_CODE, 0)
        + video_svc.cost_report(PROJECT_CODE)["project_usd"]
        + audio_svc.cost_report(PROJECT_CODE)["project_usd"])
print(f"COSTO TOTAL DE ESTA DEMO: ${total:.4f}")
print(f"\nGuardado en la base de datos bajo el proyecto '{PROJECT_CODE}'.")
print("Revísalo en Adminer: http://localhost:8080 "
     "(sistema: PostgreSQL, servidor: db, usuario: ugc, clave: ugc, base: ugc)")
print(LINE)

session.close()
