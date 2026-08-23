"""
Proveedor de voz vía fal.ai — ElevenLabs Multilingual v2.

Verificado contra https://fal.ai/models/fal-ai/elevenlabs/tts/multilingual-v2
y https://fal.ai/elevenlabs. A diferencia del video, éste es un endpoint
síncrono (como el de imagen): se manda el texto y se recibe el audio en la
misma llamada — no hace falta cola ni sondeo, un clip de diálogo se genera
en segundos.

Precio verificado: $0.10 por 1.000 caracteres (nov. 2026). La alternativa
Turbo v2.5 cuesta la mitad ($0.05/1k) pero prioriza baja latencia sobre
naturalidad — Multilingual v2 es la elección por defecto porque un anuncio
UGC vive o muere por cuán natural suena la voz.

## Lo que NO está verificado

ElevenLabs no devuelve la duración exacta del audio generado en la
respuesta. Se estima con la misma fórmula que usa `FakeVoiceProvider` y el
prompt del Guionista (2,5 palabras/segundo) — es una aproximación, no la
duración real del archivo. Para la duración exacta habría que descargar el
audio y leer sus metadatos, fuera del alcance de este proveedor.
"""

from __future__ import annotations

import os
import time

from .voice_provider import VoiceRequest, VoiceResponse, voice_price

MODEL_ID = "fal-ai/elevenlabs/tts/multilingual-v2"

# Misma suposición que usa FakeVoiceProvider y el prompt del Agente 4: a
# ritmo natural de habla, unas 2,5 palabras por segundo.
WORDS_PER_SECOND = 2.5

# Nombres de voz de la biblioteca por defecto de ElevenLabs. Se puede pasar
# cualquier voice_id propio de la cuenta en VoiceRequest.voice_id; esto es
# sólo el valor de respaldo si no se especifica ninguno.
VOZ_POR_DEFECTO = "Sarah"


class FalVoiceProviderError(Exception):
    """Fallo de la llamada a fal.ai — de red, de autenticación o de datos."""


class FalVoiceProvider:
    name = "fal_elevenlabs_multilingual_v2"

    def __init__(self, api_key: str | None = None, model_id: str | None = None,
                voz_por_defecto: str | None = None, timeout_s: float = 60.0):
        self._api_key = api_key or os.getenv("FAL_KEY")
        if not self._api_key:
            raise RuntimeError(
                "Falta FAL_KEY. Se obtiene en https://fal.ai/dashboard/keys "
                "y se configura en .env."
            )
        self._model_id = model_id or os.getenv("FAL_MODEL_ID_VOICE", MODEL_ID)
        self._voz_por_defecto = voz_por_defecto or os.getenv(
            "FAL_VOICE_DEFAULT", VOZ_POR_DEFECTO)
        self._timeout_s = timeout_s

    def synthesize(self, request: VoiceRequest) -> VoiceResponse:
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError(
                "Falta la librería 'requests'. `pip install requests`."
            ) from exc

        payload = {
            "text": request.text,
            "voice": request.voice_id or self._voz_por_defecto,
        }

        started = time.perf_counter()
        try:
            resp = requests.post(
                f"https://fal.run/{self._model_id}",
                headers={"Authorization": f"Key {self._api_key}",
                        "Content-Type": "application/json"},
                json=payload, timeout=self._timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise FalVoiceProviderError(f"Fallo llamando a fal.ai: {exc}") from exc
        except ValueError as exc:
            raise FalVoiceProviderError(
                f"fal.ai devolvió una respuesta no JSON: {resp.text[:200]}"
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        audio = data.get("audio")
        if not audio or not audio.get("url"):
            raise FalVoiceProviderError(
                f"fal.ai no devolvió audio. Respuesta cruda: {data}. "
                f"Verifica que '{self._model_id}' siga siendo un model_id "
                f"válido en https://fal.ai/models."
            )

        palabras = len(request.text.split())
        duracion_estimada = round(palabras / (WORDS_PER_SECOND * request.speed), 2)

        return VoiceResponse(
            audio_url=audio["url"], provider=self.name,
            duration_sec=duracion_estimada,
            cost_usd=voice_price(self.name).cost(request.text),
        )
