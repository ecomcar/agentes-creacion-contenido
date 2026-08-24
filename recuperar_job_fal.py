"""
Recuperar un trabajo de video que quedó pendiente por un corte de red.

Un corte de conexión en tu computadora NO detiene la generación en los
servidores de fal.ai — el video puede haberse terminado igual. Este script
consulta el trabajo sin gastar nada (sólo se cobra por generar, no por
consultar) y, si ya terminó, lo guarda en la base de datos como si el demo
hubiera completado ese paso normalmente.

    python recuperar_job_fal.py <request_id> <clip_id>

Ejemplo:
    python recuperar_job_fal.py 01a02ec9-5d2d-7793-b5dc-7845c00831b5 C02
"""

from __future__ import annotations

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if len(sys.argv) < 3:
    sys.exit("Uso: python recuperar_job_fal.py <request_id> <clip_id>")

request_id, clip_id = sys.argv[1], sys.argv[2]

if not os.getenv("FAL_KEY"):
    sys.exit("Falta FAL_KEY en .env")

from app.db import (
    ArtifactRepository,
    AssetRepository,
    ClipRepository,
    ProjectRepository,
    engine_for,
    session_factory,
)
from app.gateway.providers.fal_video_provider import FalVideoProvider
from app.gateway.providers.video_provider import VideoJobState

PROJECT_CODE = "DEMO-MULTICLIP"

print(f"Consultando el trabajo {request_id}...")
provider = FalVideoProvider()

try:
    estado = provider.poll(request_id)
except Exception as exc:
    sys.exit(f"✗ No se pudo consultar: {exc}\n"
             f"  Si vuelve a fallar por red, revisa tu conexión e "
             f"inténtalo de nuevo en un minuto.")

print(f"Estado: {estado.state.value}")

if estado.state is VideoJobState.RUNNING or estado.state is VideoJobState.QUEUED:
    print("\nTodavía está generándose. Espera un minuto y vuelve a correr")
    print("este mismo comando.")
    sys.exit(0)

if estado.state is VideoJobState.FAILED:
    print(f"\n✗ El trabajo terminó fallando: {estado.error_message}")
    print("  No hay nada que recuperar; habrá que generar el video de nuevo")
    print("  cuando sigas con el demo.")
    sys.exit(0)

# SUCCEEDED
print(f"\n✓ El video SÍ se completó — no hace falta pagar de nuevo.")
print(f"  URL: {estado.video_url}")
print(f"  Costo (ya se cobró en fal.ai al generarse): ${estado.cost_usd:.4f}")

respuesta = input("\n¿Guardarlo en la base de datos para el clip "
                  f"{clip_id}? [s/N] ").strip().lower()
if respuesta != "s":
    print("No se guardó nada. La URL de arriba sigue siendo válida si la")
    print("necesitas después.")
    sys.exit(0)

engine = engine_for()
session = session_factory(engine)()

project_repo = ProjectRepository(session)
clip_repo = ClipRepository(session)
artifact_repo = ArtifactRepository(session)
asset_repo = AssetRepository(session)

project = project_repo.by_code(PROJECT_CODE)
if project is None:
    sys.exit(f"No existe el proyecto {PROJECT_CODE} en la base de datos.")

clip_row = clip_repo.by_code(project.id, clip_id)
if clip_row is None:
    sys.exit(f"No existe el clip {clip_id} en el proyecto {PROJECT_CODE}.")

# El video_prompt más reciente de este clip es el que originó este trabajo.
prompt_row = artifact_repo.latest(project.id, "video_prompt", clip_id=clip_row.id)
if prompt_row is not None:
    artifact_repo.approve(prompt_row.id)

asset_repo.create(
    project_id=project.id, clip_id=clip_row.id, kind="video",
    storage_url=estado.video_url, provider=provider.name,
    cost_usd=estado.cost_usd,
    source_artifact_id=prompt_row.id if prompt_row else None,
    is_selected=True,
)
project_repo.add_cost(project.id, estado.cost_usd)
session.commit()
session.close()

print(f"\n✓ Guardado. El clip {clip_id} ya tiene su video en la base de datos.")
print("Puedes seguir con el resto del pipeline sin regenerar este paso.")
