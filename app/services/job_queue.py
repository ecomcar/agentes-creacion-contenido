"""
Cola de trabajos de video.

Tres problemas aparecen en cuanto una operación deja de ser síncrona, y los
tres cuestan dinero si no se resuelven:

1. **Doble cobro.** El usuario pulsa "generar" dos veces, o un reintento se
   solapa con el original. Se resuelve con una clave de idempotencia derivada
   del contenido: mismo prompt + misma imagen + misma duración = mismo
   trabajo, no dos.

2. **Trabajos huérfanos.** El proceso muere con un trabajo en vuelo. El
   proveedor lo sigue ejecutando y cobrando, pero nadie recoge el resultado.
   Se resuelve guardando `provider_job_id` en el momento del envío, antes de
   cualquier otra cosa, para poder reconciliar al arrancar.

3. **Sondeo infinito.** Un trabajo que nunca termina consume sondeos para
   siempre. Se resuelve con un tope de sondeos por trabajo.

`Job` tiene la forma de una tabla `jobs` que el esquema aún no incluye: es la
tabla que hay que añadir al migrar esta fase a Postgres.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from ..gateway.providers.video_provider import (
    VideoJobState,
    VideoProvider,
    VideoRequest,
)

MAX_POLLS_PER_JOB = 120   # a ~5s por sondeo, unos 10 minutos


class JobStatus(str, Enum):
    PENDING = "pending"          # creado, aún no enviado al proveedor
    SUBMITTED = "submitted"      # el proveedor lo aceptó
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABANDONED = "abandoned"      # superó el tope de sondeos


class Job(BaseModel):
    """Un trabajo de generación. Forma de la tabla `jobs`."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    project_code: str
    clip_id: str
    kind: str = "video"
    idempotency_key: str
    provider: str
    provider_job_id: str | None = None
    status: JobStatus = JobStatus.PENDING
    polls: int = 0
    progress: float = 0.0
    result_url: str | None = None
    cost_usd: float = 0.0
    duration_sec: float = 0.0
    error_message: str | None = None
    attempt: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None

    @property
    def terminal(self) -> bool:
        return self.status in (JobStatus.SUCCEEDED, JobStatus.FAILED,
                               JobStatus.ABANDONED)

    @property
    def in_flight(self) -> bool:
        """En el proveedor y sin recoger: si el proceso muere, es dinero vivo."""
        return (self.status in (JobStatus.SUBMITTED, JobStatus.RUNNING)
                and self.provider_job_id is not None)


def idempotency_key(project_code: str, clip_id: str, prompt: str,
                    image_url: str, duration_sec: float,
                    seed: int | None = None) -> str:
    """
    Clave derivada del contenido, no del momento.

    Dos envíos idénticos producen la misma clave y por tanto el mismo trabajo.
    Cambiar el prompt, la imagen, la duración o la semilla produce una clave
    distinta y un trabajo nuevo, que es lo correcto: eso ya es otra
    generación.

    La semilla tiene que entrar. Sin ella, pedir una segunda variante del
    mismo clip —el caso más normal cuando la primera no convence— devolvía el
    trabajo anterior en vez de generar nada nuevo.
    """
    material = (f"{project_code}|{clip_id}|{prompt}|{image_url}"
                f"|{duration_sec}|{seed}")
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


class JobQueue:
    """Cola en memoria. En producción, las mismas operaciones sobre `jobs`."""

    def __init__(self, provider: VideoProvider,
                 max_polls: int = MAX_POLLS_PER_JOB,
                 poll_interval_s: float = 8.0):
        self.provider = provider
        self.max_polls = max_polls
        # 8s es el intervalo que ya se probó funcionando de verdad
        # contra Kling (ver probar_fal_video.py). Los tests con
        # FakeVideoProvider deben pasar poll_interval_s=0
        # explícitamente para no volverse lentos — este valor por
        # defecto es para uso real, no para tests.
        self.poll_interval_s = poll_interval_s
        self.jobs: dict[str, Job] = {}
        self._by_key: dict[str, str] = {}


    # -- envío --------------------------------------------------------

    def submit(self, *, project_code: str, clip_id: str,
               request: VideoRequest) -> Job:
        """
        Envía un trabajo, o devuelve el existente si ya se envió uno igual.

        Nunca lanza por duplicado: devolver el trabajo en curso es la
        respuesta correcta a "genera esto otra vez" cuando ya se está
        generando.
        """
        key = idempotency_key(project_code, clip_id, request.prompt,
                              request.image_url, request.duration_sec,
                              request.seed)

        existente = self._by_key.get(key)
        if existente is not None:
            previo = self.jobs[existente]
            # Un trabajo fallido sí puede reintentarse: la clave se libera.
            if previo.status is not JobStatus.FAILED:
                return previo
            self._by_key.pop(key, None)

        job = Job(project_code=project_code, clip_id=clip_id,
                  idempotency_key=key, provider=self.provider.name,
                  duration_sec=request.duration_sec)
        self.jobs[job.id] = job
        self._by_key[key] = job.id

        try:
            # El id del proveedor se guarda ANTES de nada más: si el proceso
            # muere en la línea siguiente, el trabajo sigue siendo
            # recuperable en vez de convertirse en gasto perdido.
            job.provider_job_id = self.provider.submit(request)
            job.status = JobStatus.SUBMITTED
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            job.finished_at = datetime.now(timezone.utc)

        return job

    # -- sondeo -------------------------------------------------------

    def poll(self, job_id: str) -> Job:
        job = self.jobs[job_id]
        if job.terminal or job.provider_job_id is None:
            return job

        if job.polls >= self.max_polls:
            job.status = JobStatus.ABANDONED
            job.error_message = (
                f"El trabajo superó {self.max_polls} sondeos sin terminar. "
                f"Se abandona el seguimiento; revisar en el proveedor "
                f"({job.provider_job_id}) antes de reintentar para no pagar "
                f"dos veces.")
            job.finished_at = datetime.now(timezone.utc)
            return job

        job.polls += 1
        estado = self.provider.poll(job.provider_job_id)
        job.progress = estado.progress

        if estado.state is VideoJobState.SUCCEEDED:
            job.status = JobStatus.SUCCEEDED
            job.result_url = estado.video_url
            job.cost_usd = estado.cost_usd
            job.finished_at = datetime.now(timezone.utc)
        elif estado.state is VideoJobState.FAILED:
            job.status = JobStatus.FAILED
            job.error_message = estado.error_message
            job.finished_at = datetime.now(timezone.utc)
        else:
            job.status = JobStatus.RUNNING

        return job

    def wait(self, job_id: str, max_polls: int | None = None,
             poll_interval_s: float | None = None) -> Job:
        """
        Sondea hasta terminar, con una espera real entre cada consulta.

        Bug real encontrado con una llamada de verdad: sin la espera,
        este método agotaba los 120 intentos en segundos —limitado sólo
        por la latencia de red— y abandonaba el trabajo mucho antes de
        que Kling terminara de generar (1-3 minutos reales). No es que
        el proveedor tardara 16 minutos; es que nunca se esperó nada.

        En la API HTTP no se usa: allí se devuelve el `job_id` al instante
        y el frontend consulta el estado.
        """
        limite = max_polls if max_polls is not None else self.max_polls
        intervalo = (poll_interval_s if poll_interval_s is not None
                    else self.poll_interval_s)
        for intento in range(limite):
            job = self.poll(job_id)
            if job.terminal:
                return job
            if intento < limite - 1 and intervalo > 0:
                time.sleep(intervalo)
        return self.jobs[job_id]


    # -- recuperación -------------------------------------------------

    def orphans(self) -> list[Job]:
        """
        Trabajos enviados y sin recoger.

        Al arrancar el proceso, esto es lo primero que hay que consultar: son
        generaciones que el proveedor puede estar ejecutando y cobrando.
        """
        return [j for j in self.jobs.values() if j.in_flight]

    def reconcile(self) -> list[Job]:
        """Recoge el resultado de los trabajos huérfanos tras un reinicio."""
        return [self.poll(j.id) for j in self.orphans()]

    def for_clip(self, project_code: str, clip_id: str) -> list[Job]:
        return [j for j in self.jobs.values()
                if j.project_code == project_code and j.clip_id == clip_id]

    def total_cost(self, project_code: str | None = None) -> float:
        return round(sum(j.cost_usd for j in self.jobs.values()
                         if project_code is None
                         or j.project_code == project_code), 6)
