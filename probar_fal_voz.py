"""
Verificación de ElevenLabs (vía fal.ai) con una llamada real:
`python probar_fal_voz.py`

Genera un audio corto para confirmar que la clave, el model_id y el formato
de respuesta asumidos por FalVoiceProvider siguen vigentes. Es barato: un
saludo corto cuesta centavos.

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

from app.gateway.providers.fal_voice_provider import (
    MODEL_ID,
    FalVoiceProvider,
    FalVoiceProviderError,
)
from app.gateway.providers.voice_provider import VoiceRequest

TEXTO_DE_PRUEBA = "Casi cancelo la fiesta de mi hijo por esto"

print("Conectando con fal.ai (ElevenLabs)...")
print(f"Modelo: {os.getenv('FAL_MODEL_ID_VOICE', f'(por defecto) {MODEL_ID}')}")

provider = FalVoiceProvider()

try:
    resultado = provider.synthesize(VoiceRequest(
        text=TEXTO_DE_PRUEBA, voice_id="", language="es-EC",
    ))
except FalVoiceProviderError as exc:
    print(f"\n✗ FALLÓ: {exc}")
    print("\nSi el error menciona 404 o 'model not found', el model_id puede")
    print("haber cambiado. Búscalo en https://fal.ai/models y configúralo")
    print("en .env como FAL_MODEL_ID_VOICE=el-id-correcto.")
    sys.exit(1)

print(f"\n✓ fal.ai respondió correctamente.")
print(f"  URL del audio: {resultado.audio_url}")
print(f"  Duración estimada: {resultado.duration_sec}s "
      f"(estimación por palabras, no leída del archivo real)")
print(f"  Costo: ${resultado.cost_usd:.4f} "
      f"({len(TEXTO_DE_PRUEBA)} caracteres × $0.10/1000)")
print("\nAbre la URL para escuchar el resultado antes de conectarlo al")
print("pipeline completo. Presta atención especial a si suena natural en")
print("español, no sólo a si el audio se generó.")
