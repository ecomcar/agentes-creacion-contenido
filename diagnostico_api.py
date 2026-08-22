"""
Diagnóstico mínimo de conexión con Anthropic.

Llama al modelo con una petición trivial y muestra exactamente lo que
responde, sin pasar por contratos ni orquestador. Sirve para separar dos
problemas distintos: "el SDK no conecta bien" vs "el modelo conecta pero el
prompt no produce el JSON esperado".

    python diagnostico_api.py
"""

from __future__ import annotations

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if not os.getenv("ANTHROPIC_API_KEY"):
    sys.exit("Falta ANTHROPIC_API_KEY en el entorno o en .env")

from app.gateway.providers.anthropic_provider import AnthropicProvider
from app.gateway.types import GenerationRequest

print("Conectando con Anthropic...")
provider = AnthropicProvider()

request = GenerationRequest(
    system="Responde únicamente con este JSON exacto, sin explicación ni "
           "markdown: {\"ok\": true, \"mensaje\": \"conexión correcta\"}",
    user="Confirma la conexión.",
    max_tokens=100,
    model="claude-haiku-4-5",
)

try:
    respuesta = provider.generate(request)
except Exception as exc:
    print(f"\n✗ FALLÓ LA LLAMADA: {type(exc).__name__}: {exc}")
    sys.exit(1)

print(f"\n✓ Respondió el modelo: {respuesta.model}")
print(f"  Latencia: {respuesta.latency_ms}ms")
print(f"  Tokens: {respuesta.usage.input_tokens} entrada / "
      f"{respuesta.usage.output_tokens} salida")
print(f"\n  Texto crudo devuelto:")
print(f"  {'-'*60}")
print(f"  {respuesta.text}")
print(f"  {'-'*60}")

if "ok" in respuesta.text.lower() and "true" in respuesta.text.lower():
    print("\n✓ El modelo sigue instrucciones de formato correctamente.")
else:
    print("\n! El texto no parece el JSON esperado. Esto ayuda a ver si el")
    print("  modelo agrega explicaciones o texto extra alrededor del JSON.")
