"""
Servicio de generación de audio.

Completa el trío junto a `ImageGenerationService` y `VideoGenerationService`:
el Agente 9 produce un `VoiceDirection` —un objeto Pydantic— y este servicio
lo ejecuta contra un `VoiceProvider` real. Misma separación de siempre:
generar no es tarea de un agente.

Diferencia con imagen y video: la voz es **síncrona** (como imagen, a
diferencia del video por cola) y el coste se paga por **carácter de texto**,
no por generación ni por segundo — el tercer modelo de coste del sistema.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..contracts import ApprovalIssue, VoiceDirection
from ..gateway.providers.voice_provider import VoiceProvider, VoiceRequest
from ..gateway.types import BudgetExceeded
from .image_generation import Asset


class AudioBlocked(Exception):
    """El VoiceDirection no supera las compuertas; no se gastó nada."""

    def __init__(self, message: str, issues: list[ApprovalIssue] | None = None):
        super().__init__(message)
        self.issues = issues or []


class AudioGenerationService:
    def __init__(self, provider: VoiceProvider, *,
                max_cost_per_clip_usd: float = 0.20,
                max_cost_per_project_usd: float = 3.00):
        self.provider = provider
        self.max_cost_per_clip_usd = max_cost_per_clip_usd
        self.max_cost_per_project_usd = max_cost_per_project_usd
        self.assets: list[Asset] = []
        self.spent_by_clip: dict[str, float] = {}
        self.spent_by_project: dict[str, float] = {}

    def generate(self, direction: VoiceDirection, *, text: str,
                project_code: str, voice_id: str | None = None) -> Asset:
        """
        Sintetiza el audio de un clip.

        `text` es el diálogo real del guion (`ScriptClip.dialogue`), no algo
        que viva en `VoiceDirection` — el contrato del Agente 9 sólo dirige
        cómo se lee, no qué se lee.
        """
        clip_id = direction.clip_id or "sin_clip"

        # 1 ── compuertas del VoiceDirection, antes de gastar. El defecto
        # que más delata un UGC generado (entonación de locutor) se corta
        # aquí si no está explícitamente prohibido en el propio contrato.
        blocking = direction.blocking_issues()
        if blocking:
            raise AudioBlocked(
                f"La dirección de voz del clip {clip_id} no supera las "
                f"compuertas; no se generó nada.", blocking,
            )

        voz = voice_id or direction.profile.voice_id
        if not voz:
            raise AudioBlocked(
                f"El clip {clip_id} no tiene ninguna voz asignada — ni en "
                f"el VoiceDirection ni pasada explícitamente. Elegir una de "
                f"la biblioteca de voces antes de generar."
            )

        # 2 ── tope de gasto por caracteres, antes de llamar al proveedor.
        precio = _price_for(self.provider)
        worst = round(len(text) / 1000 * precio, 6)
        self._check_budget(clip_id, project_code, worst)

        respuesta = self.provider.synthesize(VoiceRequest(
            text=text, voice_id=voz, language=direction.profile.language,
        ))

        # 3 ── registro del gasto real (puede diferir levemente del peor
        # caso si el proveedor cobra distinto de lo estimado).
        self.spent_by_clip[clip_id] = round(
            self.spent_by_clip.get(clip_id, 0.0) + respuesta.cost_usd, 6)
        self.spent_by_project[project_code] = round(
            self.spent_by_project.get(project_code, 0.0) + respuesta.cost_usd, 6)

        asset = Asset(
            project_code=project_code, clip_id=direction.clip_id, kind="audio",
            version=self._next_version(project_code, clip_id),
            storage_url=respuesta.audio_url, provider=respuesta.provider,
            cost_usd=respuesta.cost_usd, duration_sec=respuesta.duration_sec,
            is_selected=True,   # la voz no tiene variantes que elegir después
        )
        self.assets.append(asset)
        return asset

    def _check_budget(self, clip_id: str, project_code: str,
                      worst: float) -> None:
        gastado_clip = self.spent_by_clip.get(clip_id, 0.0)
        if gastado_clip + worst > self.max_cost_per_clip_usd:
            raise BudgetExceeded(
                f"El clip {clip_id} lleva ${gastado_clip:.4f} en voz y esta "
                f"generación añadiría ${worst:.4f}, superando el tope de "
                f"${self.max_cost_per_clip_usd:.4f} por clip.")
        gastado_proj = self.spent_by_project.get(project_code, 0.0)
        if gastado_proj + worst > self.max_cost_per_project_usd:
            raise BudgetExceeded(
                f"El proyecto {project_code} lleva ${gastado_proj:.4f} en "
                f"voz y esta generación añadiría ${worst:.4f}, superando el "
                f"tope de ${self.max_cost_per_project_usd:.4f}.")

    def _next_version(self, project_code: str, clip_id: str) -> int:
        previos = [a.version for a in self.assets
                  if a.project_code == project_code and a.clip_id == clip_id
                  and a.kind == "audio"]
        return max(previos, default=0) + 1

    def for_clip(self, project_code: str, clip_id: str) -> Asset | None:
        candidatos = [a for a in self.assets if a.project_code == project_code
                     and a.clip_id == clip_id and a.kind == "audio"]
        return max(candidatos, key=lambda a: a.version, default=None)

    def cost_report(self, project_code: str) -> dict[str, float]:
        return {
            "project_usd": self.spent_by_project.get(project_code, 0.0),
            "project_limit_usd": self.max_cost_per_project_usd,
            **{f"clip_{k}_usd": v for k, v in self.spent_by_clip.items()},
        }


def _price_for(provider: VoiceProvider) -> float:
    """
    Precio por 1.000 caracteres del proveedor conectado.

    Se lee de VOICE_PRICES por nombre en vez de pedírselo al proveedor
    directamente: el protocolo VoiceProvider no exige exponer su precio, y
    acoplar el servicio a esa tabla es más simple que ampliar el protocolo
    para un solo dato.
    """
    from ..gateway.providers.voice_provider import voice_price
    return voice_price(provider.name).usd_per_1k_chars
