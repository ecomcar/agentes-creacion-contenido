"""
Proveedores de video.

**Primera pieza asíncrona del sistema.** Un clip de Kling tarda minutos. Eso
rompe el patrón de todas las fases anteriores, donde llamar y recibir ocurría
en la misma función.

Por eso el protocolo no es `generate()` sino dos operaciones:

    submit(request) → provider_job_id     (vuelve enseguida)
    poll(job_id)    → VideoJobStatus      (se consulta hasta terminar)

Esto no es una complicación gratuita: es lo que permite que la API HTTP
responda al instante mientras el trabajo corre por detrás, y que un reinicio
del proceso no pierda un clip que ya se está pagando.

PRECIOS: por **segundo de video**, no por generación. Ninguno verificado;
todos valen 0 hasta configurarse en `.env`.
"""

from __future__ import annotations

import os
import uuid
from enum import Enum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class VideoPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    usd_per_second: float
    verified: bool = False
    note: str = ""

    def cost(self, seconds: float) -> float:
        return round(self.usd_per_second * seconds, 6)


VIDEO_PRICES: dict[str, VideoPrice] = {
    "kling": VideoPrice(provider="kling", usd_per_second=0.0, verified=False,
                        note="SIN VERIFICAR — configurar PRICE_VIDEO_KLING."),
    "kling_3": VideoPrice(provider="kling_3", usd_per_second=0.0, verified=False,
                          note="SIN VERIFICAR — configurar PRICE_VIDEO_KLING_3."),
    "fake_video": VideoPrice(provider="fake_video", usd_per_second=0.0,
                             verified=True,
                             note="Proveedor de pruebas: no genera nada."),
}


def _load_video_price_overrides() -> None:
    for name in list(VIDEO_PRICES):
        raw = os.getenv("PRICE_VIDEO_" + name.upper())
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue
        VIDEO_PRICES[name] = VideoPrice(
            provider=name, usd_per_second=value, verified=True,
            note=f"Definido en .env (PRICE_VIDEO_{name.upper()}).")


_load_video_price_overrides()


def video_price(provider: str) -> VideoPrice:
    return VIDEO_PRICES.get(provider, VideoPrice(
        provider=provider, usd_per_second=0.0, verified=False,
        note="PROVEEDOR SIN PRECIO REGISTRADO — el coste reportado será 0."))


def unverified_video_providers() -> list[str]:
    return sorted(p for p, v in VIDEO_PRICES.items() if not v.verified)


# ----------------------------------------------------------- protocolo


class VideoJobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class VideoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    negative_prompt: str = ""
    image_url: str                        # la imagen base aprobada
    duration_sec: float = Field(gt=0, le=15)
    aspect_ratio: str = "9:16"
    seed: int | None = None


class VideoJobStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_job_id: str
    state: VideoJobState
    video_url: str | None = None
    cost_usd: float = 0.0
    error_message: str | None = None
    progress: float = Field(default=0.0, ge=0, le=1)


@runtime_checkable
class VideoProvider(Protocol):
    name: str

    def submit(self, request: VideoRequest) -> str: ...
    def poll(self, provider_job_id: str) -> VideoJobStatus: ...


class FakeVideoProvider:
    """
    Proveedor determinista para desarrollo y tests.

    Simula latencia con un contador de sondeos en vez de con relojes: los
    tests corren en milisegundos y son reproducibles. `polls_until_done`
    controla cuántas consultas hacen falta antes de que el trabajo termine.
    """

    name = "fake_video"

    def __init__(self, polls_until_done: int = 2, fail_job: bool = False,
                 fail_submit: bool = False):
        self._polls_until_done = polls_until_done
        self._fail_job = fail_job
        self._fail_submit = fail_submit
        self._jobs: dict[str, dict] = {}
        self.submissions: list[VideoRequest] = []

    def submit(self, request: VideoRequest) -> str:
        if self._fail_submit:
            raise ConnectionError("fallo simulado al enviar el trabajo")
        self.submissions.append(request)
        job_id = f"fakejob_{uuid.uuid4().hex[:10]}"
        self._jobs[job_id] = {"polls": 0, "duration": request.duration_sec}
        return job_id

    def poll(self, provider_job_id: str) -> VideoJobStatus:
        job = self._jobs.get(provider_job_id)
        if job is None:
            raise KeyError(f"Trabajo desconocido: {provider_job_id}")

        job["polls"] += 1
        if job["polls"] < self._polls_until_done:
            return VideoJobStatus(
                provider_job_id=provider_job_id, state=VideoJobState.RUNNING,
                progress=round(job["polls"] / self._polls_until_done, 2))

        if self._fail_job:
            return VideoJobStatus(
                provider_job_id=provider_job_id, state=VideoJobState.FAILED,
                error_message="fallo simulado durante la generación")

        return VideoJobStatus(
            provider_job_id=provider_job_id, state=VideoJobState.SUCCEEDED,
            video_url=f"https://fake.local/{provider_job_id}.mp4",
            cost_usd=video_price(self.name).cost(job["duration"]),
            progress=1.0)


class HTTPVideoProvider:
    """
    Plantilla para un proveedor real (Kling 3.0 u otro).

    Deliberadamente incompleta: el endpoint y la forma del payload varían y no
    los tengo verificados. Al implementarla sólo hay que respetar
    `submit`/`poll` — nada más del sistema cambia.
    """

    def __init__(self, provider_name: str = "kling_3", api_key: str | None = None):
        self.name = provider_name
        self._api_key = api_key or os.getenv("KLING_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                f"Falta la clave del proveedor de video '{provider_name}'. "
                f"Configurar KLING_API_KEY en .env.")

    def submit(self, request: VideoRequest) -> str:
        raise NotImplementedError(
            "Implementar contra la API real. Debe devolver el id de trabajo "
            "del proveedor inmediatamente, sin esperar a que termine.")

    def poll(self, provider_job_id: str) -> VideoJobStatus:
        raise NotImplementedError(
            "Implementar contra la API real. No debe bloquear: devuelve el "
            "estado actual y vuelve.")
