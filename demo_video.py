"""
Demostración de la fase 5: `python demo_video.py`

Generación asíncrona de video con proveedor falso. Muestra las cuatro
conductas que aparecen cuando una operación deja de ser instantánea.
"""

from __future__ import annotations

from app.contracts import VideoPrompt
from app.gateway import BudgetExceeded
from app.gateway.providers import (
    FakeVideoProvider,
    VideoRequest,
    unverified_video_providers,
    video_provider,
)
from app.services import (
    Asset,
    ClipProgress,
    JobQueue,
    JobStatus,
    VideoBlocked,
    VideoGenerationService,
)

LINE = "─" * 72

BLOCKS = {
    "camera": "front smartphone camera, slight handheld movement, no stabilization",
    "subject_action": ("looks into the lens while speaking, briefly looks away "
                       "while thinking, then looks back"),
    "microgestures": ("natural blinking, small eyebrow movement, subtle "
                      "breathing, slight weight shift"),
    "performance": "casual, unscripted feeling, not presenter-like",
    "physics": "natural gravity on hair and cardigan",
    "product_constraint": "",
    "negative_behavior": ("avoid perfect posture, continuous eye contact, "
                          "exaggerated gestures, cinematic camera movement, "
                          "slow motion"),
}

PROMPT = {
    "artifact": "video_prompt", "created_by": "agent_08", "clip_id": "C01",
    "image_asset_id": "img_c01_v3", "pattern_code": "KL_TALKING_SELFIE",
    "pattern_version": 2, "duration_sec": 6.0, "blocks": BLOCKS,
}
PROMPT_ROTO = {**PROMPT, "blocks": {**BLOCKS, "microgestures": "",
                                    "negative_behavior": ""}}

video_provider.VIDEO_PRICES["fake_video"].usd_per_second = 0.05  # simulado


def imagen(clip_id="C01", selected=True) -> Asset:
    return Asset(project_code="UGC-0001", clip_id=clip_id, kind="image",
                 version=3, storage_url=f"https://fake/img_{clip_id}_v3.png",
                 provider="fake_image", is_selected=selected)


# ══ 1 · El envío vuelve enseguida ═══════════════════════════════════════
print(f"{LINE}\n1 · Enviar no es esperar\n{LINE}")
provider = FakeVideoProvider(polls_until_done=4)
queue = JobQueue(provider=provider)
svc = VideoGenerationService(queue=queue, max_cost_per_clip_usd=1.00)

job = svc.submit(VideoPrompt.model_validate(PROMPT), project_code="UGC-0001",
                 image_asset=imagen(), seed=1)
print(f"  Trabajo {job.id[:12]} encolado en el proveedor "
      f"({job.provider_job_id})")
print(f"  Estado: {job.status.value} · resultado: {job.result_url}")
print("  La API HTTP puede responder aquí mismo. Un clip de Kling tarda")
print("  minutos y no cabe dentro de un request.\n")

print("  Sondeos del frontend:")
while not job.terminal:
    job = queue.poll(job.id)
    barra = "█" * int(job.progress * 20)
    print(f"    {job.status.value:10} {barra:<20} {job.progress:.0%}")

asset = svc.collect(job)
print(f"\n  Resultado: {asset.storage_url}")
print(f"  Coste: ${asset.cost_usd:.4f}  ({PROMPT['duration_sec']}s × "
      f"$0.05/s — el video se cobra por segundo, no por generación)")


# ══ 2 · Idempotencia ════════════════════════════════════════════════════
print(f"\n{LINE}\n2 · Dos clics en 'generar' no son dos generaciones\n{LINE}")
provider = FakeVideoProvider(polls_until_done=1)
queue = JobQueue(provider=provider)
r = VideoRequest(prompt="p", image_url="https://fake/i.png", duration_sec=6.0,
                 seed=1)
j1 = queue.submit(project_code="UGC-0001", clip_id="C01", request=r)
j2 = queue.submit(project_code="UGC-0001", clip_id="C01", request=r)
print(f"  Envío 1: {j1.id[:12]}")
print(f"  Envío 2: {j2.id[:12]}  {'← el mismo' if j1.id == j2.id else ''}")
print(f"  Trabajos realmente enviados al proveedor: {len(provider.submissions)}")

r2 = VideoRequest(prompt="p", image_url="https://fake/i.png", duration_sec=6.0,
                  seed=2)
j3 = queue.submit(project_code="UGC-0001", clip_id="C01", request=r2)
print(f"\n  Con otra semilla: {j3.id[:12]}  ← trabajo nuevo")
print(f"  Trabajos enviados: {len(provider.submissions)}")
print("  Pedir otra variante es lo normal cuando la primera no convence;")
print("  por eso la semilla entra en la clave de idempotencia.")


# ══ 3 · Trabajos huérfanos ══════════════════════════════════════════════
print(f"\n{LINE}\n3 · Si el proceso muere, el proveedor sigue cobrando\n{LINE}")
provider = FakeVideoProvider(polls_until_done=1)
queue = JobQueue(provider=provider)
for clip in ("C01", "C02", "C03"):
    queue.submit(project_code="UGC-0001", clip_id=clip,
                 request=VideoRequest(prompt=f"p{clip}",
                                      image_url=f"https://fake/{clip}.png",
                                      duration_sec=6.0))
print(f"  Tres clips enviados. Ahora el proceso se reinicia.\n")
print(f"  Huérfanos detectados al arrancar: {len(queue.orphans())}")
for j in queue.orphans():
    print(f"    {j.clip_id}  proveedor: {j.provider_job_id}")
recuperados = queue.reconcile()
print(f"\n  Recuperados: {sum(1 for j in recuperados if j.status is JobStatus.SUCCEEDED)}")
print(f"  Huérfanos restantes: {len(queue.orphans())}")
print("  El id del proveedor se guarda ANTES de nada más, justo para esto.")


# ══ 4 · Compuertas y topes ══════════════════════════════════════════════
print(f"\n{LINE}\n4 · Lo que no llega a encolarse\n{LINE}")
provider = FakeVideoProvider(polls_until_done=1)
svc = VideoGenerationService(queue=JobQueue(provider=provider),
                             max_cost_per_clip_usd=0.50)

for etiqueta, accion in [
    ("Imagen no seleccionada",
     lambda: svc.submit(VideoPrompt.model_validate(PROMPT),
                        project_code="UGC-0001",
                        image_asset=imagen(selected=False))),
    ("Imagen de otro clip",
     lambda: svc.submit(VideoPrompt.model_validate(PROMPT),
                        project_code="UGC-0001",
                        image_asset=imagen(clip_id="C02"))),
    ("Bloques vacíos en el prompt",
     lambda: svc.submit(VideoPrompt.model_validate(PROMPT_ROTO),
                        project_code="UGC-0001", image_asset=imagen())),
]:
    try:
        accion()
        print(f"  {etiqueta:32} → pasó")
    except VideoBlocked as exc:
        print(f"  ✗ {etiqueta:30} → {str(exc)[:60]}")

job = svc.submit(VideoPrompt.model_validate(PROMPT), project_code="UGC-0001",
                 image_asset=imagen(), seed=1)
svc.wait_and_collect(job)
try:
    svc.submit(VideoPrompt.model_validate(PROMPT), project_code="UGC-0001",
               image_asset=imagen(), seed=2)
except BudgetExceeded as exc:
    print(f"  ⛔ {str(exc)[:80]}")

print(f"\n  Trabajos enviados al proveedor: {len(provider.submissions)} de 5 intentos.")


# ══ 5 · Estado del storyboard ═══════════════════════════════════════════
print(f"\n{LINE}\n5 · Lo que vería el storyboard del dashboard\n{LINE}")
estados = [
    ClipProgress(clip_id="C01", has_image=True, has_selected_image=True,
                 video_status="succeeded", video_progress=1.0, audit_score=91),
    ClipProgress(clip_id="C02", has_image=True, has_selected_image=True,
                 video_status="running", video_progress=0.6),
    ClipProgress(clip_id="C03", has_image=True, has_selected_image=False),
    ClipProgress(clip_id="C04", has_image=True, has_selected_image=True,
                 video_status="failed"),
]
print(f"  {'clip':6} {'imagen':10} {'video':12} {'progreso':>9} {'auditor':>8}")
for c in estados:
    img = "✓ elegida" if c.has_selected_image else ("○ sin elegir"
                                                    if c.has_image else "—")
    score = f"{c.audit_score}/100" if c.audit_score else "—"
    print(f"  {c.icon} {c.clip_id:4} {img:10} {c.video_status:12} "
          f"{c.video_progress:>8.0%} {score:>8}")

print(f"\n  Proveedores de video sin precio verificado: "
      f"{', '.join(unverified_video_providers())}")
print("  Los $0.05/s de esta demo son inventados. Configurar PRICE_VIDEO_*")
print("  en .env con las cifras reales antes de presupuestar.")
