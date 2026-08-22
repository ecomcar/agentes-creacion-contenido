"""
Verificación de fal.ai con una llamada real: `python probar_fal.py`

Genera UNA imagen de prueba (barata) para confirmar que la clave, el
model_id y el formato de respuesta asumidos por FalImageProvider siguen
vigentes. Corre esto antes de usar fal.ai dentro del pipeline completo.

Requiere FAL_KEY en el entorno o en .env.
"""

from __future__ import annotations

import os
import sys

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

from app.gateway.providers.fal_provider import FalImageProvider, FalProviderError
from app.gateway.providers.image_provider import ImageRequest

print("Conectando con fal.ai...")
print(f"Modelo: {os.getenv('FAL_MODEL_ID_IMAGE', '(por defecto) fal-ai/nano-banana-pro')}")

provider = FalImageProvider()

try:
    resultado = provider.generate(ImageRequest(
        prompt="a simple photo of a red apple on a wooden table, natural light",
        n_variants=1,
        aspect_ratio="1:1",
    ))
except FalProviderError as exc:
    print(f"\n✗ FALLÓ: {exc}")
    print("\nSi el error menciona 404 o 'model not found', el model_id por")
    print("defecto puede haber cambiado. Búscalo en https://fal.ai/models y")
    print("configúralo en .env como FAL_MODEL_ID_IMAGE=el-id-correcto.")
    sys.exit(1)

print(f"\n✓ fal.ai respondió correctamente.")
print(f"  Latencia: {resultado.latency_ms}ms")
print(f"  Imágenes generadas: {len(resultado.images)}")
for img in resultado.images:
    print(f"  URL: {img.url}")
print(f"\n  Costo reportado: ${resultado.cost_usd:.4f}")
print("  (será $0.0000 hasta que configures PRICE_IMAGE_FAL_NANO_BANANA_PRO")
print("   en .env con la cifra real de tu cuenta de fal.ai)")
print("\nAbre la URL en el navegador para confirmar visualmente que la")
print("imagen es razonable antes de conectar esto al pipeline completo.")
