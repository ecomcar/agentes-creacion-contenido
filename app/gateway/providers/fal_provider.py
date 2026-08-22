"""
Proveedor de imagen vía fal.ai.

fal.ai expone modelos de terceros —incluido Nano Banana Pro— bajo un patrón
REST único y estable: POST a `https://fal.run/{model_id}` con la clave en el
header `Authorization`. Eso es lo que hace este proveedor.

## Lo que NO está verificado

El `model_id` exacto de Nano Banana Pro en fal.ai, y los nombres precisos de
los campos del payload (`image_size`, `image_urls` para referencias, etc.)
pueden haber cambiado desde el corte de conocimiento de quien escribió esto.
**Antes de usar en producción, confirma en https://fal.ai/models:**

  1. El `model_id` correcto (búscalo en el dashboard de fal.ai, pestaña API).
  2. Los nombres de campo que el modelo específico espera.
  3. El formato de la respuesta (esto asume `{"images": [{"url": ...}]}`,
     el patrón más común en fal.ai, pero varía por modelo).

Todo se configura por variable de entorno, así que si algo cambió no hay que
tocar código — sólo `.env`.
"""

from __future__ import annotations

import os
import time
import uuid

from ...gateway.providers.image_provider import (
    GeneratedImage,
    ImageRequest,
    ImageResponse,
    image_price,
)

DEFAULT_MODEL_ID = "fal-ai/nano-banana/pro"

# Mapeo aproximado de aspect_ratio a dimensiones. fal.ai suele aceptar tanto
# un enum de tamaño como width/height explícitos según el modelo; se manda
# width/height por ser el formato más universal entre modelos de fal.ai.
_ASPECT_TO_SIZE = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1024, 1024),
    "4:5": (1080, 1350),
}


class FalProviderError(Exception):
    """Fallo de la llamada a fal.ai — de red, de autenticación o de datos."""


class FalImageProvider:
    name = "fal_nano_banana_pro"

    def __init__(self, api_key: str | None = None, model_id: str | None = None,
                timeout_s: float = 120.0):
        self._api_key = api_key or os.getenv("FAL_KEY")
        if not self._api_key:
            raise RuntimeError(
                "Falta FAL_KEY. Se obtiene en https://fal.ai/dashboard/keys "
                "y se configura en .env."
            )
        self._model_id = model_id or os.getenv("FAL_MODEL_ID_IMAGE",
                                                DEFAULT_MODEL_ID)
        self._endpoint = f"https://fal.run/{self._model_id}"
        self._timeout_s = timeout_s

    def generate(self, request: ImageRequest) -> ImageResponse:
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError(
                "Falta la librería 'requests'. `pip install requests`."
            ) from exc

        width, height = _ASPECT_TO_SIZE.get(request.aspect_ratio, (1080, 1920))
        payload: dict = {
            "prompt": request.prompt,
            "image_size": {"width": width, "height": height},
            "num_images": request.n_variants,
        }
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            payload["seed"] = request.seed
        if request.reference_urls:
            # Nombre de campo sin confirmar contra la documentación actual
            # del modelo — ver advertencia al inicio del archivo. Es lo que
            # ancla la generación en las referencias del avatar en vez de
            # redescribirlo desde cero.
            payload["image_urls"] = request.reference_urls

        started = time.perf_counter()
        try:
            resp = requests.post(
                self._endpoint,
                headers={"Authorization": f"Key {self._api_key}",
                        "Content-Type": "application/json"},
                json=payload, timeout=self._timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise FalProviderError(f"Fallo llamando a fal.ai: {exc}") from exc
        except ValueError as exc:  # respuesta no es JSON
            raise FalProviderError(
                f"fal.ai devolvió una respuesta no JSON: {resp.text[:200]}"
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        crudas = data.get("images")
        if not crudas:
            raise FalProviderError(
                f"fal.ai no devolvió imágenes. Respuesta cruda: {data}. "
                f"Verifica que '{self._model_id}' sea el model_id correcto "
                f"y que el formato de respuesta asumido siga vigente."
            )

        semilla_base = data.get("seed", request.seed or 0)
        imagenes = [
            GeneratedImage(
                url=img["url"], provider=self.name,
                seed=(semilla_base + i) if semilla_base is not None else None,
                width=img.get("width", width), height=img.get("height", height),
            )
            for i, img in enumerate(crudas)
        ]

        precio_unitario = image_price(self.name).usd_per_image
        return ImageResponse(
            images=imagenes, provider=self.name,
            cost_usd=round(precio_unitario * len(imagenes), 6),
            latency_ms=latency_ms,
        )
