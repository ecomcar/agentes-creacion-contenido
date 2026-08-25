"""
Esquemas de la API.

Deliberadamente distintos de los contratos de dominio (`app.contracts`): un
`ProjectOut` es una vista para HTTP, no el mismo objeto que usa el
orquestador internamente. Mezclarlos acopla la API a decisiones internas que
deberían poder cambiar sin romper el contrato con quien consuma esto.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=32)
    brand_name: str
    product_name: str
    brand_id: str | None = None
    campaign_goal: str | None = None
    platform: str | None = None
    target_duration_sec: int = 35
    auto_mode: bool = False


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    brand_id: str | None
    brand_name: str
    product_name: str
    current_stage: str
    stage_status: str
    auto_mode: bool
    total_cost_usd: float
    created_at: datetime


class BrandCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    default_audience: dict = Field(default_factory=dict)
    brand_voice: str | None = None
    forbidden_claims: list[str] = Field(default_factory=list)
    competitors: list[dict] = Field(default_factory=list)
    notes: str | None = None


class BrandUpdate(BaseModel):
    """Todos opcionales a propósito: es una actualización parcial."""
    model_config = ConfigDict(extra="forbid")

    default_audience: dict | None = None
    brand_voice: str | None = None
    forbidden_claims: list[str] | None = None
    competitors: list[dict] | None = None
    notes: str | None = None


class BrandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    default_audience: dict
    brand_voice: str | None
    forbidden_claims: list
    competitors: list
    notes: str | None
    is_active: bool
    created_at: datetime


class ClipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^C\d{2}$")
    sequence_order: int = 0
    role: str | None = None
    dialogue: str | None = None


class ClipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    sequence_order: int
    role: str | None
    dialogue: str | None
    status: str


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    version: int
    status: str
    payload: dict
    created_by: str
    clip_id: str | None
    input_ref: str | None
    created_at: datetime


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    clip_id: str | None
    kind: str
    version: int
    storage_url: str
    provider: str | None
    is_selected: bool
    cost_usd: float
    duration_sec: float | None
    created_at: datetime


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: str | None = None


class StageIssueOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    severity: str
    field: str | None = None


class StageResultOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    status: str
    message: str
    cost_usd: float
    artifact: ArtifactOut | None = None
    issues: list[StageIssueOut] = Field(default_factory=list)


# -- payloads específicos de cada etapa ----------------------------------
# Sólo lo que requiere una decisión humana va en el body; lo demás (el
# brief, la estrategia, etc.) se busca automáticamente en la base como el
# último artefacto aprobado del proyecto.


class RunResearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str
    brand_name: str
    description: str
    known_audience: str | None = None
    competitors_known: list[str] = Field(default_factory=list)
    brand_voice: str | None = None
    extra_material: str | None = None
    feedback: str | None = None


class RunStrategyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: str | None = None


class RunHooksIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    angle_id: str = Field(pattern=r"^A\d{2}$")
    feedback: str | None = None


class RunScriptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook_id: str = Field(pattern=r"^H\d{2}$")
    target_duration_sec: float = 35.0
    feedback: str | None = None
