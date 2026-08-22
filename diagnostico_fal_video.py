"""
Diagnóstico de la URL de resultado de fal.ai — sin costo adicional.

Consultar el estado o el resultado de un trabajo YA TERMINADO no cuesta
nada (fal.ai cobra por generar, no por consultar). Este script prueba varias
formas de construir la URL del resultado contra un request_id que ya
completó, para encontrar la correcta sin gastar en una nueva generación.

    python diagnostico_fal_video.py 01a02a93-6172-7db1-9b65-55fc70b2c09a
"""

from __future__ import annotations

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if len(sys.argv) < 2:
    sys.exit("Uso: python diagnostico_fal_video.py <request_id>")

request_id = sys.argv[1]
api_key = os.getenv("FAL_KEY")
if not api_key:
    sys.exit("Falta FAL_KEY en .env")

import requests

from app.gateway.providers.fal_video_provider import MODEL_ID

headers = {"Authorization": f"Key {api_key}"}

candidatas = {
    "model_id completo (con subpath)": f"https://queue.fal.run/{MODEL_ID}/requests/{request_id}",
    "namespace base (sin subpath)":     f"https://queue.fal.run/fal-ai/kling-video/requests/{request_id}",
}

print(f"Probando el resultado de {request_id}\n")
for etiqueta, url in candidatas.items():
    print(f"── {etiqueta}")
    print(f"   {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"   → HTTP {resp.status_code}")
        if resp.status_code == 200:
            print(f"   → ✓ ÉSTA FUNCIONA")
            print(f"   → cuerpo: {resp.text[:300]}")
        else:
            print(f"   → cuerpo: {resp.text[:200]}")
    except requests.RequestException as exc:
        print(f"   → error de red: {exc}")
    print()
