"""
Proveedores de voz.

Tercer modelo de coste del sistema: por **carácter de texto**, no por token
ni por segundo ni por generación. Con tres modelos distintos conviviendo, la
lección es que cada tipo de proveedor necesita su propia estimación — no hay
una fórmula común.

PRECIOS: ninguno verificado. Todos valen 0 hasta configurarse en `.env`.
"""

from __future__ import annotations

import os
import uuid
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class VoicePrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    usd_per_1k_chars: float
    verified: bool = False
    note: str = ""

    def cost(self, text: str) -> float:
        return round(len(text) / 1000 * self.usd_per_1k_chars, 6)


VOICE_PRICES: dict[str, VoicePrice] = {
    "elevenlabs": VoicePrice(provider="elevenlabs", usd_per_1k_chars=0.0,
                             verified=False,
                             note="SIN VERIFICAR — configurar PRICE_VOICE_ELEVENLABS."),
    "fal_elevenlabs_multilingual_v2": VoicePrice(
        provider="fal_elevenlabs_multilingual_v2", usd_per_1k_chars=0.10,
        verified=True,
        note="Verificado en fal.ai (nov. 2026): ElevenLabs Multilingual v2, "
             "29 idiomas, prioriza estabilidad sobre velocidad. La "
             "alternativa Turbo v2.5 cuesta $0.05/1k pero con menos "
             "idiomas y más énfasis en baja latencia que en naturalidad.",
    ),
    "fake_voice": VoicePrice(provider="fake_voice", usd_per_1k_chars=0.0,
                             verified=True,
                             note="Proveedor de pruebas: no sintetiza nada."),
}


def _load_voice_price_overrides() -> None:
    for name in list(VOICE_PRICES):
        raw = os.getenv("PRICE_VOICE_" + name.upper())
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        VOICE_PRICES[name] = VoicePrice(
            provider=name, usd_per_1k_chars=value, verified=True,
            note=f"Definido en .env (PRICE_VOICE_{name.upper()}).")


_load_voice_price_overrides()


def voice_price(provider: str) -> VoicePrice:
    return VOICE_PRICES.get(provider, VoicePrice(
        provider=provider, usd_per_1k_chars=0.0, verified=False,
        note="PROVEEDOR SIN PRECIO REGISTRADO — el coste reportado será 0."))


def unverified_voice_providers() -> list[str]:
    return sorted(p for p, v in VOICE_PRICES.items() if not v.verified)


class VoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    voice_id: str
    language: str = "es-EC"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    pauses_before: list[str] = Field(default_factory=list)


class VoiceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_url: str
    provider: str
    duration_sec: float
    cost_usd: float


@runtime_checkable
class VoiceProvider(Protocol):
    name: str

    def synthesize(self, request: VoiceRequest) -> VoiceResponse: ...


class FakeVoiceProvider:
    """
    Proveedor determinista. Estima duración a 2,5 palabras por segundo, el
    mismo ritmo que el prompt del guionista usa para dimensionar los clips.
    """

    name = "fake_voice"
    WORDS_PER_SECOND = 2.5

    def __init__(self, fail_times: int = 0):
        self._fail_times = fail_times
        self.calls: list[VoiceRequest] = []

    def synthesize(self, request: VoiceRequest) -> VoiceResponse:
        self.calls.append(request)
        if self._fail_times > 0:
            self._fail_times -= 1
            raise ConnectionError("fallo simulado de síntesis de voz")

        palabras = len(request.text.split())
        duracion = round(palabras / (self.WORDS_PER_SECOND * request.speed), 2)
        return VoiceResponse(
            audio_url=f"https://fake.local/{uuid.uuid4().hex[:12]}.mp3",
            provider=self.name, duration_sec=duracion,
            cost_usd=voice_price(self.name).cost(request.text))


class HTTPVoiceProvider:
    """Plantilla para un proveedor real. Sólo hay que respetar `synthesize`."""

    def __init__(self, provider_name: str = "elevenlabs",
                 api_key: str | None = None):
        self.name = provider_name
        self._api_key = api_key or os.getenv("VOICE_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                f"Falta la clave del proveedor de voz '{provider_name}'. "
                f"Configurar VOICE_API_KEY en .env.")

    def synthesize(self, request: VoiceRequest) -> VoiceResponse:
        raise NotImplementedError("Implementar contra la API real.")
