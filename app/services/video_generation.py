"""
Servicio de generación de video.

Igual que en imagen: el Agente 8 produce un `VideoPrompt` y este servicio lo
ejecuta. La diferencia es que aquí la ejecución es asíncrona y pasa por la
cola de trabajos.

Añade una compuerta que no existía antes: **no se puede animar un clip que no
tiene imagen seleccionada.** Sin ella, el sistema generaría video sobre una
variante que el humano no eligió, o sobre ninguna.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..contracts import ApprovalIssue, VideoPrompt
from ..gateway.providers.video_provider import VideoRequest, video_price
from ..gateway.types import BudgetExceeded
from .image_generation import Asset
from .job_queue import Job, JobQueue, JobStatus


class VideoBlocked(Exception):
    """El clip no cumple las condiciones para animarse; no se gastó nada."""

    def __init__(self, message: str, issues: list[ApprovalIssue] | None = None):
        super().__init__(message)
        self.issues = issues or []


class VideoGenerationService:
    def __init__(self, queue: JobQueue, *,
                 max_cost_per_clip_usd: float = 2.00,
                 max_cost_per_project_usd: float = 20.00):
        self.queue = queue
        self.max_cost_per_clip_usd = max_cost_per_clip_usd
        self.max_cost_per_project_usd = max_cost_per_project_usd
        self.assets: list[Asset] = []
        self.spent_by_clip: dict[str, float] = {}
        self.spent_by_project: dict[str, float] = {}

    # -- envío ---------------------------------------------------------

    def submit(self, prompt: VideoPrompt, *, project_code: str,
               image_asset: Asset, seed: int | None = None) -> Job:
        """
        Encola la generación y devuelve el trabajo enseguida.

        No espera al resultado: eso es `wait()` o el sondeo del frontend.
        """
        clip_id = prompt.clip_id or "sin_clip"

        # 1 ── el clip debe tener imagen elegida por un humano
        if not image_asset.is_selected:
            raise VideoBlocked(
                f"La imagen del clip {clip_id} no está seleccionada. Animar "
                f"una variante no elegida produce un clip que nadie aprobó."
            )
        if image_asset.clip_id != prompt.clip_id:
            raise VideoBlocked(
                f"La imagen pertenece al clip {image_asset.clip_id} pero el "
                f"prompt es del {prompt.clip_id}."
            )

        # 2 ── compuertas del prompt, antes de gastar
        blocking = prompt.blocking_issues()
        if blocking:
            raise VideoBlocked(
                f"El prompt de movimiento del clip {clip_id} no supera las "
                f"compuertas; no se encoló nada.", blocking)

        # 3 ── tope: el coste va por segundo, no por generación
        precio = video_price(self.queue.provider.name)
        worst = precio.cost(prompt.duration_sec)
        self._check_budget(clip_id, project_code, worst)

        request = VideoRequest(
            prompt=prompt.blocks.as_prompt(),
            negative_prompt=prompt.blocks.negative_behavior,
            image_url=image_asset.storage_url,
            duration_sec=prompt.duration_sec, seed=seed,
        )
        return self.queue.submit(project_code=project_code, clip_id=clip_id,
                                 request=request)

    def _check_budget(self, clip_id: str, project_code: str,
                      worst: float) -> None:
        gastado_clip = self.spent_by_clip.get(clip_id, 0.0)
        if gastado_clip + worst > self.max_cost_per_clip_usd:
            raise BudgetExceeded(
                f"El clip {clip_id} lleva ${gastado_clip:.4f} en video y esta "
                f"generación añadiría ${worst:.4f}, superando el tope de "
                f"${self.max_cost_per_clip_usd:.4f} por clip.")
        gastado_proj = self.spent_by_project.get(project_code, 0.0)
        if gastado_proj + worst > self.max_cost_per_project_usd:
            raise BudgetExceeded(
                f"El proyecto {project_code} lleva ${gastado_proj:.4f} en "
                f"video y esta generación añadiría ${worst:.4f}, superando el "
                f"tope de ${self.max_cost_per_project_usd:.4f}.")

    # -- recogida ------------------------------------------------------

    def collect(self, job: Job) -> Asset | None:
        """
        Convierte un trabajo terminado con éxito en un asset de video.

        Devuelve None si el trabajo aún corre o falló. Es idempotente: llamar
        dos veces sobre el mismo trabajo no duplica el asset ni el gasto.
        """
        if job.status is not JobStatus.SUCCEEDED or job.result_url is None:
            return None

        ya = next((a for a in self.assets if a.source_prompt_id == job.id), None)
        if ya is not None:
            return ya

        self.spent_by_clip[job.clip_id] = round(
            self.spent_by_clip.get(job.clip_id, 0.0) + job.cost_usd, 6)
        self.spent_by_project[job.project_code] = round(
            self.spent_by_project.get(job.project_code, 0.0) + job.cost_usd, 6)

        asset = Asset(
            project_code=job.project_code, clip_id=job.clip_id, kind="video",
            version=self._next_version(job.project_code, job.clip_id),
            storage_url=job.result_url, source_prompt_id=job.id,
            provider=job.provider, cost_usd=job.cost_usd,
            duration_sec=job.duration_sec,
        )
        self.assets.append(asset)
        return asset

    def _next_version(self, project_code: str, clip_id: str) -> int:
        previos = [a.version for a in self.assets
                   if a.project_code == project_code and a.clip_id == clip_id]
        return max(previos, default=0) + 1

    def wait_and_collect(self, job: Job) -> Asset | None:
        return self.collect(self.queue.wait(job.id))

    # -- selección -----------------------------------------------------

    def select(self, asset_id: str) -> Asset:
        elegido = next((a for a in self.assets if a.id == asset_id), None)
        if elegido is None:
            raise KeyError(f"No existe el asset de video {asset_id}.")
        for a in self.assets:
            if (a.project_code == elegido.project_code
                    and a.clip_id == elegido.clip_id):
                a.is_selected = (a.id == asset_id)
        return elegido

    def selected_for(self, project_code: str, clip_id: str) -> Asset | None:
        return next((a for a in self.assets if a.project_code == project_code
                     and a.clip_id == clip_id and a.is_selected), None)

    def variants_for(self, project_code: str, clip_id: str) -> list[Asset]:
        return [a for a in self.assets if a.project_code == project_code
                and a.clip_id == clip_id]

    def cost_report(self, project_code: str) -> dict[str, float]:
        return {
            "project_usd": self.spent_by_project.get(project_code, 0.0),
            "project_limit_usd": self.max_cost_per_project_usd,
            **{f"clip_{k}_usd": v for k, v in self.spent_by_clip.items()},
        }


class ClipProgress(BaseModel):
    """Estado de un clip para el storyboard del dashboard."""

    model_config = ConfigDict(extra="forbid")

    clip_id: str
    has_image: bool = False
    has_selected_image: bool = False
    video_status: str = "pending"
    video_progress: float = 0.0
    audit_score: int | None = None

    @property
    def icon(self) -> str:
        return {"succeeded": "🟢", "running": "🟡", "submitted": "🟡",
                "failed": "🔴", "abandoned": "⛔"}.get(self.video_status, "⚪")
