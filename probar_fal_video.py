"""
Verificación de Kling (vía fal.ai) con una llamada real: `python probar_fal_video.py`

Genera UN clip de video corto para confirmar que la clave, el model_id y el
formato de la cola siguen vigentes. Cuesta más que la prueba de imagen —
5 segundos de Kling Standard son unos $0.42— así que pide confirmación
antes de gastar.

Requiere FAL_KEY en el entorno o en .env.
"""

from __future__ import annotations

import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if not os.getenv("FAL_KEY"):
    sys.exit(
        "Falta FAL_KEY.\n\n"
        "  1. Crea una cuenta en https://fal.ai\n"
        "  2. Genera una clave en https://fal.ai/dashboard/keys\n"
        "  3. Agrégala a .env:  FAL_KEY=tu-clave-aqui\n"
    )

from app.gateway.providers.fal_video_provider import (
    FalVideoProvider,
    FalVideoProviderError,
)
from app.gateway.providers.video_provider import VideoJobState, VideoRequest

# Imagen de ejemplo estable. La de la propia documentación de fal.ai
# (storage.googleapis.com/falserverless/...) resultó no ser descargable por
# sus propios servidores al probarla — confirmado con un 422
# "file_download_error". Wikimedia Commons no restringe hotlinking y es
# mucho más estable para este tipo de verificación.
IMAGEN_DE_PRUEBA = (
    "https://upload.wikimedia.org/wikipedia/commons/e/ec/"
    "Mona_Lisa%2C_by_Leonardo_da_Vinci%2C_from_C2RMF_retouched.jpg"
)
DURACION_SEC = 5.0
COSTO_ESTIMADO = 5 * 0.084

print(f"Esta verificación genera un clip de {DURACION_SEC:.0f}s con Kling "
      f"v3 Standard.")
print(f"Costo estimado: ${COSTO_ESTIMADO:.2f}\n")
respuesta = input("¿Continuar? [s/N] ").strip().lower()
if respuesta != "s":
    print("Cancelado. No se hizo ninguna llamada.")
    sys.exit(0)

provider = FalVideoProvider()

print("\nEnviando a la cola de fal.ai...")
try:
    request_id = provider.submit(VideoRequest(
        prompt="the person in the photo waves at the camera and smiles",
        image_url=IMAGEN_DE_PRUEBA, duration_sec=DURACION_SEC,
    ))
except FalVideoProviderError as exc:
    print(f"\n✗ FALLÓ AL ENVIAR: {exc}")
    print("\nSi el error menciona 404, el model_id puede haber cambiado.")
    print("Búscalo en https://fal.ai/models y configúralo en .env como")
    print("FAL_MODEL_ID_VIDEO=el-id-correcto.")
    sys.exit(1)

print(f"✓ Encolado. request_id: {request_id}")
print("\nSondeando (Kling suele tardar 1-3 minutos)...")

intentos = 0
while True:
    intentos += 1
    try:
        estado = provider.poll(request_id)
    except FalVideoProviderError as exc:
        print(f"\n✗ FALLÓ AL SONDEAR: {exc}")
        sys.exit(1)

    print(f"  [{intentos:>3}] {estado.state.value}")

    if estado.state is VideoJobState.SUCCEEDED:
        print(f"\n✓ Video generado.")
        print(f"  URL: {estado.video_url}")
        print(f"  Costo real: ${estado.cost_usd:.4f}")
        print("\nAbre la URL para confirmar visualmente el resultado antes")
        print("de conectar esto al pipeline completo.")
        break

    if estado.state is VideoJobState.FAILED:
        print(f"\n✗ El trabajo falló: {estado.error_message}")
        sys.exit(1)

    if intentos >= 40:  # ~5-6 minutos a 8s por sondeo
        print("\n⚠ Superó el tiempo de espera de esta verificación. El "
              "trabajo puede seguir corriendo en fal.ai — revisa el "
              "dashboard antes de reintentar para no pagar dos veces.")
        sys.exit(1)

    time.sleep(8)
