"""
Proveedores de imagen.

**Aquí cambia la naturaleza del coste.** Hasta la fase 3 todo se pagaba por
token; a partir de aquí se paga por generación. Eso tiene dos consecuencias:

1. El Cost Guard no puede estimar con `max_tokens`. Necesita otro camino:
   `n_variantes × precio_por_imagen`, comprobado antes de generar.
2. Un fallo cuesta lo mismo que un acierto. Por eso las compuertas del
   Agente 7 rechazan el prompt **antes** de llegar aquí.

PRECIOS: no tengo cifras verificadas de ningún proveedor de imagen. Todas las
entradas están marcadas `verified=False` y valen 0 hasta que se configuren en
`.env`. Preferimos una estimación que dice "no lo sé" a una que parece precisa
y presupuesta mal.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ImagePrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    usd_per_image: float
    verified: bool = False
    note: str = ""


IMAGE_PRICES: dict[str, ImagePrice] = {
    "nano_banana": ImagePrice(
        provider="nano_banana", usd_per_image=0.0, verified=False,
        note="SIN VERIFICAR — configurar PRICE_IMAGE_NANO_BANANA en .env.",
    ),
    "nano_banana_pro": ImagePrice(
        provider="nano_banana_pro", usd_per_image=0.0, verified=False,
        note="SIN VERIFICAR — configurar PRICE_IMAGE_NANO_BANANA_PRO en .env.",
    ),
    "fal_nano_banana_pro": ImagePrice(
        provider="fal_nano_banana_pro", usd_per_image=0.15, verified=True,
        note="Verificado en la documentación de fal.ai (nov. 2026): $0.15 "
             "por imagen a 1K/2K de resolución, $0.30 a 4K. Este precio "
             "asume 1K/2K; si se usa FAL_IMAGE_RESOLUTION=4K, duplicar a "
             "mano con PRICE_IMAGE_FAL_NANO_BANANA_PRO=0.30.",
    ),
    "fake_image": ImagePrice(
        provider="fake_image", usd_per_image=0.0, verified=True,
        note="Proveedor de pruebas: no cuesta nada porque no genera nada.",
    ),
}


def _load_image_price_overrides() -> None:
    for name in list(IMAGE_PRICES):
        raw = os.getenv("PRICE_IMAGE_" + name.upper())
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        IMAGE_PRICES[name] = ImagePrice(
            provider=name, usd_per_image=value, verified=True,
            note=f"Definido en .env (PRICE_IMAGE_{name.upper()}).",
        )


_load_image_price_overrides()


def image_price(provider: str) -> ImagePrice:
    return IMAGE_PRICES.get(provider, ImagePrice(
        provider=provider, usd_per_image=0.0, verified=False,
        note="PROVEEDOR SIN PRECIO REGISTRADO — el coste reportado será 0.",
    ))


def unverified_image_providers() -> list[str]:
    return sorted(p for p, v in IMAGE_PRICES.items() if not v.verified)


# ----------------------------------------------------------- protocolo


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    negative_prompt: str = ""
    reference_urls: list[str] = Field(default_factory=list)
    aspect_ratio: str = "9:16"          # vertical, el formato del UGC
    n_variants: int = Field(default=3, ge=1, le=8)
    seed: int | None = None


class GeneratedImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    provider: str
    seed: int | None = None
    width: int = 1080
    height: int = 1920


class ImageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    images: list[GeneratedImage]
    provider: str
    cost_usd: float
    latency_ms: int


@runtime_checkable
class ImageProvider(Protocol):
    name: str

    def generate(self, request: ImageRequest) -> ImageResponse: ...


class FakeImageProvider:
    """
    Proveedor determinista para desarrollo y tests.

    No genera imágenes: devuelve URLs sintéticas y registra qué se le pidió.
    Permite probar el servicio completo —topes, variantes, selección,
    reintentos— sin red ni créditos.
    """

    name = "fake_image"

    def __init__(self, fail_times: int = 0):
        self._fail_times = fail_times
        self.calls: list[ImageRequest] = []

    def generate(self, request: ImageRequest) -> ImageResponse:
        self.calls.append(request)
        if self._fail_times > 0:
            self._fail_times -= 1
            raise ConnectionError("fallo simulado del generador de imagen")

        price = image_price(self.name).usd_per_image
        images = [
            GeneratedImage(
                url=f"https://fake.local/{uuid.uuid4().hex[:12]}.png",
                provider=self.name, seed=(request.seed or 0) + i,
            )
            for i in range(request.n_variants)
        ]
        return ImageResponse(images=images, provider=self.name,
                             cost_usd=round(price * request.n_variants, 6),
                             latency_ms=1)


class HTTPImageProvider:
    """
    Plantilla para un proveedor real (Nano Banana Pro u otro).

    Deliberadamente incompleta: el endpoint y la forma del payload varían por
    proveedor y no los tengo verificados. Al implementarla, lo único que debe
    respetarse es el protocolo `ImageProvider` — nada más del sistema cambia.
    """

    def __init__(self, provider_name: str = "nano_banana_pro",
                 api_key: str | None = None):
        self.name = provider_name
        self._api_key = api_key or os.getenv("NANO_BANANA_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                f"Falta la clave del proveedor de imagen '{provider_name}'. "
                f"Configurar NANO_BANANA_API_KEY en .env."
            )

    def generate(self, request: ImageRequest) -> ImageResponse:
        raise NotImplementedError(
            "Implementar contra la API real del proveedor. El contrato de "
            "entrada/salida ya está fijado por ImageRequest/ImageResponse; "
            "no hace falta tocar agentes, contratos ni orquestador."
        )
