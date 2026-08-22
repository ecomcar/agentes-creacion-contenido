"""
Base común de los 12 contratos.

DOS NIVELES DE VALIDACIÓN — esta es la decisión central del módulo:

  Nivel 1 · ESQUEMA (validators de Pydantic)
      Rechaza lo estructuralmente imposible: un clip que termina antes de
      empezar, un score de 130/100, un artefacto sin los campos del contrato.
      Si esto falla, el artefacto NO se guarda. Se reintenta o se corta.

  Nivel 2 · CRITERIOS DE APROBACIÓN (metodo approval_check())
      Evalúa calidad editorial: "3 ángulos realmente distintos entre sí",
      "al menos 3 hooks con promedio >= 80". Un artefacto puede guardarse
      como draft incumpliendo esto. Quien decide qué hacer es el Orquestador.

Por qué separarlos: si mezclamos las dos cosas en validators, un ángulo flojo
tira una excepción y perdemos el trabajo del agente. Queremos guardarlo,
mostrarlo en el dashboard y decidir con información.

Regla heredada del proyecto anterior: los criterios deterministas mandan sobre
el juicio del agente. Un agente puede declarar su salida perfecta; si
approval_check() devuelve issues bloqueantes, no pasa.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------- enums


class ArtifactType(str, Enum):
    RESEARCH_BRIEF = "research_brief"
    STRATEGY = "strategy"
    HOOKS = "hooks"
    UGC_SCRIPT = "ugc_script"
    STORYBOARD = "storyboard"
    CHARACTER_BIBLE = "character_bible"
    IMAGE_PROMPT = "image_prompt"
    VIDEO_PROMPT = "video_prompt"
    VOICE_DIRECTION = "voice_direction"
    EDIT_PLAN = "edit_plan"
    AUDIT_RESULT = "audit_result"
    CAMPAIGN_LEARNINGS = "campaign_learnings"


class ArtifactStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class Severity(str, Enum):
    BLOCKING = "blocking"  # no puede aprobarse
    WARNING = "warning"    # se puede aprobar, queda registrado


class Confidence(str, Enum):
    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"


# --------------------------------------------------- issues de aprobación


class ApprovalIssue(BaseModel):
    """Un incumplimiento concreto de los criterios de aprobación."""

    code: str
    message: str
    severity: Severity = Severity.BLOCKING
    field: str | None = None

    def __str__(self) -> str:  # pragma: no cover - conveniencia de debug
        return f"[{self.severity.value}] {self.code}: {self.message}"


class AgentError(BaseModel):
    """
    Error declarado por el propio agente.

    Existe para que un agente pueda decir "no pude conseguir esto" en vez de
    inventarlo. Es la contraparte estructurada de la degradación elegante:
    hueco declarado > hueco rellenado con datos plausibles.
    """

    code: str
    message: str
    field: str | None = None
    recoverable: bool = True


# ------------------------------------------------------------ base común


class ArtifactBase(BaseModel):
    """Campos que lleva todo artefacto, sin excepción."""

    model_config = ConfigDict(
        extra="forbid",            # un campo de más suele ser el agente alucinando
        validate_assignment=True,
        use_enum_values=False,
    )

    artifact: ArtifactType
    version: int = Field(ge=1, default=1)
    schema_version: str = "v1"
    status: ArtifactStatus = ArtifactStatus.DRAFT
    created_by: str                       # 'agent_04' | 'human'
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    input_ref: UUID | None = None         # artefacto exacto que se usó de entrada
    clip_id: str | None = None            # sólo artefactos por clip ('C01')
    errors: list[AgentError] = Field(default_factory=list)

    # -- criterios de aprobación -------------------------------------

    def approval_check(self) -> list[ApprovalIssue]:
        """Sobrescribir en cada contrato. Sin issues = apto para aprobación."""
        return []

    def blocking_issues(self) -> list[ApprovalIssue]:
        return [i for i in self.approval_check() if i.severity is Severity.BLOCKING]

    def can_be_approved(self) -> bool:
        return not self.blocking_issues()

    # -- utilidades --------------------------------------------------

    def next_version(self, **changes: Any):
        """
        Los artefactos son inmutables: corregir es crear versión nueva.
        Nunca mutamos el payload de una versión ya guardada.
        """
        data = self.model_dump()
        data.update(changes)
        data["version"] = self.version + 1
        data["status"] = ArtifactStatus.DRAFT
        data["created_at"] = datetime.now(timezone.utc)
        return type(self)(**data)


# ----------------------------------------------------------- helpers


PLACEHOLDERS = {
    "", "...", "n/a", "na", "tbd", "por definir", "a definir",
    "pendiente", "todo", "string", "lorem ipsum", "-",
}


def is_placeholder(value: str | None) -> bool:
    """
    Detecta relleno. Un LLM al que le falta información tiende a poner
    '...' o 'por definir' antes que declarar el error. Esto lo caza.
    """
    if value is None:
        return True
    return value.strip().lower() in PLACEHOLDERS


def too_similar(a: str, b: str, threshold: float = 0.50) -> bool:
    """
    Similitud léxica por Jaccard sobre palabras significativas (>3 letras).

    Detecta 'tres ángulos' que son el mismo ángulo reescrito — el modo de
    fallo más común del Agente 2.

    Umbral calibrado con medición, no a ojo: dos premisas casi idénticas
    ("mamá agotada que intenta organizar la fiesta sola" vs "mamá cansada
    que intenta organizar la fiesta sola") dan 0.556. Un umbral de 0.75
    no las habría detectado.

    Es una heurística, no una prueba: dos ángulos pueden compartir
    vocabulario y ser distintos de verdad. Por eso quien la usa la reporta
    como advertencia, no como bloqueo.
    """
    wa = {w for w in a.lower().split() if len(w) > 3}
    wb = {w for w in b.lower().split() if len(w) > 3}
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= threshold


# Puntuación 0-100 reutilizada por hooks, auditoría y métricas de librería.
Score = Annotated[int, Field(ge=0, le=100)]
