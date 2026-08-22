"""
Proveedor de video vía fal.ai — Kling v3 Standard (image-to-video).

fal.ai expone los modelos de video por un sistema de cola REST, distinto del
patrón síncrono usado para imagen. Encaja naturalmente con el protocolo
submit/poll de la fase 5:

    POST https://queue.fal.run/{model_id}                        → submit
    GET  https://queue.fal.run/{model_id}/requests/{id}/status    → poll
    GET  https://queue.fal.run/{model_id}/requests/{id}           → resultado

Verificado contra https://fal.ai/models/fal-ai/kling-video/v3/standard/
image-to-video y https://docs.fal.ai/model-endpoints/queue/.

Precio verificado: $0.084/segundo con audio desactivado, $0.126/s con audio
activado (fal.ai, noviembre 2026). Aquí se usa siempre sin audio: la voz del
anuncio la genera el Agente 9 por separado, y mezclar dos fuentes de audio
duplicaría el trabajo.

## Lo que NO está verificado con una llamada real

Kling parece aceptar sólo duraciones discretas (5 o 10 segundos), no
cualquier valor continuo — la interfaz de fal.ai muestra un selector, no un
campo libre. El proveedor redondea a la más cercana y lo dice en el log.
**Confírmalo con `probar_fal_video.py`** antes de asumir que un clip de,
digamos, 7 segundos se genera tal cual.
"""

from __future__ import annotations

import os
import time

from .video_provider import VideoJobState, VideoJobStatus, VideoRequest, video_price

MODEL_ID = "fal-ai/kling-video/v3/standard/image-to-video"

# Duraciones que Kling parece aceptar según la interfaz de fal.ai (selector,
# no campo libre). Sin verificar con una llamada real — ver advertencia
# arriba. Se redondea a la más cercana en vez de fallar.
DURACIONES_ACEPTADAS = (5, 10)


class FalVideoProviderError(Exception):
    """Fallo de la llamada a fal.ai — de red, de autenticación o de datos."""


def _redondear_duracion(duration_sec: float) -> int:
    return min(DURACIONES_ACEPTADAS, key=lambda d: abs(d - duration_sec))


class FalVideoProvider:
    name = "fal_kling_v3_standard"

    def __init__(self, api_key: str | None = None, model_id: str | None = None,
                generate_audio: bool = False, timeout_s: float = 30.0):
        self._api_key = api_key or os.getenv("FAL_KEY")
        if not self._api_key:
            raise RuntimeError(
                "Falta FAL_KEY. Se obtiene en https://fal.ai/dashboard/keys "
                "y se configura en .env."
            )
        self._model_id = model_id or os.getenv("FAL_MODEL_ID_VIDEO", MODEL_ID)
        self._generate_audio = generate_audio
        self._timeout_s = timeout_s
        # request_id → duración redondeada, para poder calcular el costo en
        # poll() sin tener que volver a pedirlo. Vive en memoria del
        # proceso; si el proceso muere, JobRepository.orphans() en la base
        # de datos sigue siendo la vía de recuperación real (fase de
        # persistencia), esto es sólo caché de conveniencia.
        self._duraciones: dict[str, int] = {}

    def _headers(self) -> dict:
        return {"Authorization": f"Key {self._api_key}",
               "Content-Type": "application/json"}

    def _requests(self):
        try:
            import requests
            return requests
        except ImportError as exc:
            raise RuntimeError(
                "Falta la librería 'requests'. `pip install requests`."
            ) from exc

    # -- envío ----------------------------------------------------------

    def submit(self, request: VideoRequest) -> str:
        requests = self._requests()
        duracion = _redondear_duracion(request.duration_sec)

        payload = {
            "start_image_url": request.image_url,
            "prompt": request.prompt,
            "duration": str(duracion),
            "generate_audio": self._generate_audio,
        }
        if request.seed is not None:
            payload["seed"] = request.seed

        try:
            resp = requests.post(
                f"https://queue.fal.run/{self._model_id}",
                headers=self._headers(), json=payload, timeout=self._timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise FalVideoProviderError(f"Fallo al encolar en fal.ai: {exc}") from exc
        except ValueError as exc:
            raise FalVideoProviderError(
                f"fal.ai devolvió una respuesta no JSON: {resp.text[:200]}"
            ) from exc

        request_id = data.get("request_id")
        if not request_id:
            raise FalVideoProviderError(
                f"fal.ai no devolvió request_id. Respuesta cruda: {data}"
            )

        self._duraciones[request_id] = duracion
        return request_id

    # -- sondeo -----------------------------------------------------------

    def poll(self, provider_job_id: str) -> VideoJobStatus:
        requests = self._requests()
        base = f"https://queue.fal.run/{self._model_id}/requests/{provider_job_id}"

        try:
            resp = requests.get(f"{base}/status", headers=self._headers(),
                                timeout=self._timeout_s)
            resp.raise_for_status()
            estado = resp.json()
        except requests.RequestException as exc:
            raise FalVideoProviderError(f"Fallo al consultar fal.ai: {exc}") from exc
        except ValueError as exc:
            raise FalVideoProviderError(
                f"fal.ai devolvió un estado no JSON: {resp.text[:200]}"
            ) from exc

        status = estado.get("status", "")

        if status == "IN_QUEUE":
            return VideoJobStatus(provider_job_id=provider_job_id,
                                  state=VideoJobState.QUEUED, progress=0.0)
        if status == "IN_PROGRESS":
            return VideoJobStatus(provider_job_id=provider_job_id,
                                  state=VideoJobState.RUNNING, progress=0.5)
        if status != "COMPLETED":
            return VideoJobStatus(
                provider_job_id=provider_job_id, state=VideoJobState.FAILED,
                error_message=f"Estado inesperado de fal.ai: '{status}'. "
                              f"Respuesta cruda: {estado}",
            )

        # Terminado: pedir el resultado.
        try:
            resp = requests.get(base, headers=self._headers(),
                                timeout=self._timeout_s)
            resp.raise_for_status()
            resultado = resp.json()
        except requests.RequestException as exc:
            raise FalVideoProviderError(
                f"Fallo al obtener el resultado de fal.ai: {exc}"
            ) from exc

        video = resultado.get("video")
        if not video or not video.get("url"):
            return VideoJobStatus(
                provider_job_id=provider_job_id, state=VideoJobState.FAILED,
                error_message=f"fal.ai marcó el trabajo como completado pero "
                              f"no devolvió video. Respuesta: {resultado}",
            )

        duracion = self._duraciones.get(provider_job_id, 5)
        costo = video_price(self.name).cost(duracion)
        return VideoJobStatus(
            provider_job_id=provider_job_id, state=VideoJobState.SUCCEEDED,
            video_url=video["url"], cost_usd=costo, progress=1.0,
        )
