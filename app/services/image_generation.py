"""
Servicio de generación de imagen.

**Generar no es tarea de un agente.** El Agente 7 produce un `ImagePrompt`
—un objeto Pydantic— y este servicio lo ejecuta. Mantener esa separación es lo
que permite testear los agentes sin proveedores y cambiar de proveedor sin
tocar agentes.

El servicio hace tres cosas que el agente no debe hacer:
  1. Comprobar el tope de créditos ANTES de generar.
  2. Rechazar prompts que no superan las compuertas, antes de gastar.
  3. Gestionar variantes y selección, con la garantía de una sola
     seleccionada por clip.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import ApprovalIssue, CharacterBible, ImagePrompt
from ..gateway.providers.image_provider import (
    ImageProvider,
    ImageRequest,
    image_price,
)
from ..gateway.types import BudgetExceeded


class Asset(BaseModel):
    """Una imagen generada, con la forma de la tabla `assets`."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    project_code: str
    clip_id: str | None = None
    kind: str = "image"
    version: int = 1
    storage_url: str
    source_prompt_id: str | None = None   # qué ImagePrompt lo generó
    provider: str
    is_selected: bool = False
    cost_usd: float = 0.0
    seed: int | None = None
    # Falta en assets de imagen (no aplica), presente en video y audio.
    # Ya existía en la tabla `assets` de la base de datos (Fase de
    # persistencia); el modelo Pydantic se había quedado atrás.
    duration_sec: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GenerationBlocked(Exception):
    """El prompt no superó las compuertas; no se gastó nada."""

    def __init__(self, message: str, issues: list[ApprovalIssue]):
        super().__init__(message)
        self.issues = issues


class ImageGenerationService:
    def __init__(self, provider: ImageProvider, *,
                 max_cost_per_clip_usd: float = 1.00,
                 max_cost_per_project_usd: float = 10.00):
        self.provider = provider
        self.max_cost_per_clip_usd = max_cost_per_clip_usd
        self.max_cost_per_project_usd = max_cost_per_project_usd
        self.assets: list[Asset] = []
        self.spent_by_clip: dict[str, float] = {}
        self.spent_by_project: dict[str, float] = {}

    # -- generación ---------------------------------------------------

    def generate(self, prompt: ImagePrompt, *, project_code: str,
                 bible: CharacterBible | None = None,
                 reference_urls: list[str] | None = None,
                 n_variants: int = 3, seed: int | None = None) -> list[Asset]:
        """
        Genera variantes para un clip y las devuelve como assets.

        Ninguna queda seleccionada: eso lo decide un humano (o el Auditor en
        modo automático).
        """
        clip_id = prompt.clip_id or "sin_clip"

        # 1 ── compuertas del prompt, antes de gastar
        blocking = prompt.blocking_issues()
        if blocking:
            raise GenerationBlocked(
                f"El prompt del clip {clip_id} no supera las compuertas; "
                f"no se generó nada.", blocking,
            )

        # 2 ── tope de créditos, antes de gastar
        unit = image_price(self.provider.name).usd_per_image
        worst = round(unit * n_variants, 6)
        self._check_budget(clip_id, project_code, worst)

        # 3 ── anclaje de identidad: se pasan las referencias, no se
        #      redescribe al personaje en el prompt
        refs = list(reference_urls or [])

        response = self.provider.generate(ImageRequest(
            prompt=prompt.prompt_text,
            negative_prompt=", ".join(prompt.negative_constraints),
            reference_urls=refs, n_variants=n_variants, seed=seed,
        ))

        # 4 ── registro del gasto real
        self.spent_by_clip[clip_id] = round(
            self.spent_by_clip.get(clip_id, 0.0) + response.cost_usd, 6)
        self.spent_by_project[project_code] = round(
            self.spent_by_project.get(project_code, 0.0) + response.cost_usd, 6)

        base_version = self._next_version(project_code, clip_id)
        per_image = round(response.cost_usd / max(1, len(response.images)), 6)

        nuevos = [
            Asset(project_code=project_code, clip_id=prompt.clip_id,
                  version=base_version + i, storage_url=img.url,
                  source_prompt_id=prompt.template_id, provider=response.provider,
                  cost_usd=per_image, seed=img.seed)
            for i, img in enumerate(response.images)
        ]
        self.assets.extend(nuevos)
        return nuevos

    def _check_budget(self, clip_id: str, project_code: str,
                      worst: float) -> None:
        clip_spent = self.spent_by_clip.get(clip_id, 0.0)
        if clip_spent + worst > self.max_cost_per_clip_usd:
            raise BudgetExceeded(
                f"El clip {clip_id} lleva ${clip_spent:.4f} en imagen y esta "
                f"generación añadiría ${worst:.4f}, superando el tope de "
                f"${self.max_cost_per_clip_usd:.4f} por clip."
            )
        proj_spent = self.spent_by_project.get(project_code, 0.0)
        if proj_spent + worst > self.max_cost_per_project_usd:
            raise BudgetExceeded(
                f"El proyecto {project_code} lleva ${proj_spent:.4f} en imagen "
                f"y esta generación añadiría ${worst:.4f}, superando el tope "
                f"de ${self.max_cost_per_project_usd:.4f}."
            )

    def _next_version(self, project_code: str, clip_id: str) -> int:
        previos = [a.version for a in self.assets
                   if a.project_code == project_code
                   and (a.clip_id or "sin_clip") == clip_id]
        return max(previos, default=0) + 1

    # -- selección ----------------------------------------------------

    def select(self, asset_id: str) -> Asset:
        """
        Marca una variante como elegida.

        Deselecciona automáticamente las demás del mismo clip: es el
        equivalente en memoria del índice parcial único del esquema. Sin esta
        garantía, el Editor puede terminar ensamblando dos versiones distintas
        del mismo clip.
        """
        elegido = next((a for a in self.assets if a.id == asset_id), None)
        if elegido is None:
            raise KeyError(f"No existe el asset {asset_id}.")

        for a in self.assets:
            if (a.project_code == elegido.project_code
                    and a.clip_id == elegido.clip_id
                    and a.kind == elegido.kind):
                a.is_selected = (a.id == asset_id)
        return elegido

    def selected_for(self, project_code: str, clip_id: str) -> Asset | None:
        return next((a for a in self.assets
                     if a.project_code == project_code
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


class AvatarLibrary:
    """
    Biblioteca de avatares en memoria.

    Es la contraparte de las tablas `avatar_library` y `avatar_references`.
    Vive fuera del proyecto: un avatar se construye una vez y se reutiliza en
    decenas de campañas.
    """

    def __init__(self):
        self._bibles: dict[str, CharacterBible] = {}
        self._references: dict[str, dict[str, str]] = {}

    def save(self, bible: CharacterBible) -> None:
        self._bibles[bible.avatar_id] = bible

    def get(self, avatar_id: str) -> CharacterBible | None:
        return self._bibles.get(avatar_id)

    def add_reference(self, avatar_id: str, angle: str, url: str) -> None:
        self._references.setdefault(avatar_id, {})[angle] = url

    def references(self, avatar_id: str) -> list[str]:
        return list(self._references.get(avatar_id, {}).values())

    def missing_references(self, avatar_id: str) -> list[str]:
        """Ángulos que la ficha exige y todavía no se han generado."""
        bible = self._bibles.get(avatar_id)
        if bible is None:
            return []
        tiene = self._references.get(avatar_id, {})
        return [a for a in bible.reference_angles_needed if a not in tiene]

    def is_ready(self, avatar_id: str) -> bool:
        """
        Un avatar sin referencias no puede anclar nada.

        Generar clips antes de tener las referencias produce exactamente el
        fallo de deriva de rostro que todo el diseño intenta evitar.
        """
        return (avatar_id in self._bibles
                and not self.missing_references(avatar_id))
