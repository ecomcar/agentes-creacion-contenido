"""
Proveedor de imagen vía fal.ai — Nano Banana Pro (Gemini 3 Pro Image).

Verificado contra la documentación de fal.ai (https://fal.ai/models/fal-ai/
nano-banana-pro/api y .../edit/api). Dos endpoints distintos según si hay
imágenes de referencia:

  Sin referencias  → fal-ai/nano-banana-pro        (texto a imagen)
  Con referencias  → fal-ai/nano-banana-pro/edit    (hasta 14 imágenes)

Esto importa porque es justo el mecanismo que ancla la identidad del avatar:
sin referencias, el modelo no tiene de dónde partir y cada generación
reinventa el rostro.

Precio verificado: $0.15 por imagen a resolución 1K/2K, $0.30 a 4K
(fal.ai/nano-banana-pro, noviembre 2026).

## Lo que puede cambiar sin avisar

fal.ai no versiona sus endpoints de forma explícita. Si `probar_fal.py`
empieza a fallar, lo primero es revisar https://fal.ai/models/fal-ai/
nano-banana-pro/api por si el esquema de entrada cambió.
"""

from __future__ import annotations

import os
import time

from ...gateway.providers.image_provider import (
    GeneratedImage,
    ImageRequest,
    ImageResponse,
    image_price,
)

MODEL_TEXT_TO_IMAGE = "fal-ai/nano-banana-pro"
MODEL_EDIT = "fal-ai/nano-banana-pro/edit"

# Valores válidos documentados por fal.ai. Cualquier otro se manda como
# "auto" y que el modelo decida, en vez de fallar por un valor no soportado.
ASPECT_RATIOS_VALIDOS = {"auto", "21:9", "16:9", "3:2", "4:3", "5:4", "1:1",
                         "4:5", "3:4", "2:3", "9:16"}


class FalProviderError(Exception):
    """Fallo de la llamada a fal.ai — de red, de autenticación o de datos."""


class FalImageProvider:
    name = "fal_nano_banana_pro"

    def __init__(self, api_key: str | None = None,
                model_id_t2i: str | None = None,
                model_id_edit: str | None = None,
                resolution: str | None = None,
                timeout_s: float = 120.0):
        self._api_key = api_key or os.getenv("FAL_KEY")
        if not self._api_key:
            raise RuntimeError(
                "Falta FAL_KEY. Se obtiene en https://fal.ai/dashboard/keys "
                "y se configura en .env."
            )
        self._model_t2i = model_id_t2i or os.getenv(
            "FAL_MODEL_ID_IMAGE", MODEL_TEXT_TO_IMAGE)
        self._model_edit = model_id_edit or os.getenv(
            "FAL_MODEL_ID_IMAGE_EDIT", MODEL_EDIT)
        # 1K y 2K cuestan igual ($0.15); 4K cuesta el doble. Por defecto 1K,
        # suficiente para revisar en pantalla antes de animar con video.
        self._resolution = resolution or os.getenv("FAL_IMAGE_RESOLUTION", "1K")
        self._timeout_s = timeout_s

    def generate(self, request: ImageRequest) -> ImageResponse:
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError(
                "Falta la librería 'requests'. `pip install requests`."
            ) from exc

        con_referencias = bool(request.reference_urls)
        model_id = self._model_edit if con_referencias else self._model_t2i
        endpoint = f"https://fal.run/{model_id}"

        aspecto = (request.aspect_ratio if request.aspect_ratio
                                          in ASPECT_RATIOS_VALIDOS else "auto")

        prompt = request.prompt
        if request.negative_prompt:
            # Nano Banana Pro (basado en Gemini) interpreta lenguaje natural
            # de forma holística y no tiene un campo separado de prompt
            # negativo como los modelos de difusión clásicos — se pliega
            # como instrucción dentro del propio prompt.
            prompt = f"{prompt}\n\nEvita expresamente: {request.negative_prompt}."

        payload: dict = {
            "prompt": prompt,
            "num_images": request.n_variants,
            "aspect_ratio": aspecto,
            "resolution": self._resolution,
            "output_format": "png",
        }
        if request.seed is not None:
            payload["seed"] = request.seed
        if con_referencias:
            payload["image_urls"] = request.reference_urls

        started = time.perf_counter()
        try:
            resp = requests.post(
                endpoint,
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
                f"Verifica que '{model_id}' siga siendo un model_id válido "
                f"en https://fal.ai/models."
            )

        imagenes = [
            GeneratedImage(
                url=img["url"], provider=self.name, seed=request.seed,
                width=img.get("width") or 0, height=img.get("height") or 0,
            )
            for img in crudas
        ]

        precio_unitario = image_price(self.name).usd_per_image
        if self._resolution == "4K":
            precio_unitario *= 2
        return ImageResponse(
            images=imagenes, provider=self.name,
            cost_usd=round(precio_unitario * len(imagenes), 6),
            latency_ms=latency_ms,
        )
