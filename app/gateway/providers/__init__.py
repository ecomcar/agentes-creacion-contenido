"""
Proveedores.

`Provider` es la única interfaz que el gateway conoce. Añadir Kling, Nano
Banana o un proveedor de voz en las fases 4-5 consiste en implementar este
protocolo — sin tocar agentes, contratos ni orquestador.
"""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable

from ..pricing import estimate_cost
from ..types import GenerationRequest, GenerationResponse, Usage


@runtime_checkable
class Provider(Protocol):
    name: str

    def generate(self, request: GenerationRequest) -> GenerationResponse: ...


class FakeProvider:
    """
    Proveedor determinista para tests y desarrollo sin gastar.

    No imita a un modelo: devuelve las respuestas que se le programan, en
    orden. Sirve para probar el gateway completo —routing, topes, reparación
    de JSON inválido, trazas— sin red ni API key.
    """

    name = "fake"

    def __init__(self, responses: list[str] | None = None,
                 model: str = "fake-model", fail_times: int = 0):
        self._responses = list(responses or [])
        self._model = model
        self._fail_times = fail_times
        self.calls: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.calls.append(request)

        if self._fail_times > 0:
            self._fail_times -= 1
            raise ConnectionError("fallo simulado del proveedor")

        text = self._responses.pop(0) if self._responses else "{}"
        model = request.model or self._model
        in_tok = max(1, len(request.system + request.user) // 4)
        out_tok = max(1, len(text) // 4)

        return GenerationResponse(
            text=text, model=model,
            usage=Usage(input_tokens=in_tok, output_tokens=out_tok,
                        cost_usd=estimate_cost(model, in_tok, out_tok)),
            latency_ms=1, stop_reason="end_turn",
        )


from .image_provider import (  # noqa: E402
    FakeImageProvider,
    GeneratedImage,
    HTTPImageProvider,
    ImagePrice,
    ImageProvider,
    ImageRequest,
    ImageResponse,
    image_price,
    unverified_image_providers,
)

from .video_provider import (  # noqa: E402
    FakeVideoProvider,
    HTTPVideoProvider,
    VideoJobState,
    VideoJobStatus,
    VideoPrice,
    VideoProvider,
    VideoRequest,
    unverified_video_providers,
    video_price,
)

from .voice_provider import (  # noqa: E402
    FakeVoiceProvider,
    HTTPVoiceProvider,
    VoicePrice,
    VoiceProvider,
    VoiceRequest,
    VoiceResponse,
    unverified_voice_providers,
    voice_price,
)

from .fal_provider import FalImageProvider, FalProviderError  # noqa: E402
from .fal_video_provider import (  # noqa: E402
    FalVideoProvider,
    FalVideoProviderError,
)
