"""
Tipos del AI Gateway.

Un agente nunca nombra un modelo. Declara qué necesita —tarea, calidad,
presupuesto— y el Router decide. Así, cuando aparezca un modelo mejor, se
cambia una tabla y ningún agente se entera.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TaskKind(str, Enum):
    """Qué tipo de trabajo cognitivo pide el agente."""

    REASONING = "reasoning"        # estrategia, análisis, auditoría
    STRUCTURED = "structured"      # rellenar un contrato con poco juicio
    CREATIVE = "creative"          # hooks, guion, diálogo
    EXTRACTION = "extraction"      # sacar datos de texto ya dado
    IMAGE_GENERATION = "image_generation"
    VIDEO_GENERATION = "video_generation"
    VOICE = "voice"


class Quality(str, Enum):
    DRAFT = "draft"
    STANDARD = "standard"
    HIGH = "high"


class Budget(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskSpec(BaseModel):
    """Lo que el agente declara. No incluye nombre de modelo, a propósito."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task: TaskKind
    quality: Quality = Quality.STANDARD
    budget: Budget = Budget.MEDIUM
    reference_consistency_critical: bool = False   # relevante para imagen


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system: str
    user: str
    max_tokens: int = 4096
    temperature: float = Field(default=1.0, ge=0, le=1)
    model: str | None = None      # lo rellena el Router, no el agente


class GenerationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    model: str
    usage: Usage
    latency_ms: int
    stop_reason: str | None = None


class RunRecord(BaseModel):
    """
    Traza de una llamada, con la forma exacta de la tabla `agent_runs`.

    El gateway la produce siempre —también cuando falla— para que el
    dashboard pueda mostrar qué pasó sin lógica adicional.
    """

    model_config = ConfigDict(extra="forbid")

    agent_number: int
    agent_name: str
    attempt: int = 1
    status: str                       # success | failed | blocked
    model_used: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    error_message: str | None = None
    triggered_by: str = "orchestrator"
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GatewayError(Exception):
    """Fallo de la capa gateway (no del contrato)."""


class BudgetExceeded(GatewayError):
    """El tope de gasto cortó la llamada ANTES de ejecutarla."""


class RepairFailed(GatewayError):
    """El modelo no logró producir un contrato válido dentro del tope."""

    def __init__(self, message: str, attempts: int, last_errors: str):
        super().__init__(message)
        self.attempts = attempts
        self.last_errors = last_errors
