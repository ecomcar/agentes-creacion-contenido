"""
Modelos SQLAlchemy.

DECISIÓN DE PORTABILIDAD: los tipos son portables entre Postgres y SQLite.

  JSONB → JSON().with_variant(JSONB, "postgresql")
  UUID  → String(32) con uuid4().hex generado en Python

Lo que se gana: las pruebas corren en SQLite en memoria, en milisegundos, sin
Docker. Lo que se pierde: la generación de UUID del lado de la base de datos
(`gen_random_uuid()`) y el tipado nativo de JSONB.

El intercambio vale la pena porque el sistema ya tiene 225 pruebas que corren
en medio segundo, y obligarlas a levantar Postgres las volvería lentas y
frágiles. En producción se usa Postgres igual: la variante JSONB se activa
sola y los índices GIN se crean en la migración.

Lo que NO es portable y hay que saberlo: el índice parcial único que garantiza
una sola imagen seleccionada por clip. SQLite lo soporta, pero no todos los
motores; si algún día se cambia de base, esa garantía hay que revisarla.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Tipo JSON que usa JSONB en Postgres y JSON normal en el resto.
JSONType = JSON().with_variant(JSONB, "postgresql")


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_now, nullable=False)


# ---------------------------------------------------------- proyectos


class Brand(Base, TimestampMixin):
    """
    Marca/empresa cliente, con su brief persistente.

    Existe para separar "quién es el cliente" de "qué campaña se está
    corriendo": Karol puede tener varias campañas (distintos productos,
    distintos ángulos) y todas comparten la misma audiencia conocida, voz
    de marca y reclamos prohibidos — no tiene sentido volver a escribir eso
    cada vez. `CreativeMemory.scope_value` ya anticipaba este concepto
    (memoria por marca) pero nunca se conectó a una entidad real; ésta lo
    es.
    """

    __tablename__ = "brands"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    # Mismo shape que AudienceSignals del contrato ResearchBrief, pero a
    # nivel de marca: edad, ubicación, dolores conocidos — reutilizable
    # como punto de partida en cada campaña nueva.
    default_audience: Mapped[dict] = mapped_column(JSONType, default=dict)
    brand_voice: Mapped[str | None] = mapped_column(Text)
    forbidden_claims: Mapped[list] = mapped_column(JSONType, default=list)
    # Lista de {"name":..., "angle_observed":..., "url":...} — mismo shape
    # que Competitor del contrato, para poder precargar sin transformar.
    competitors: Mapped[list] = mapped_column(JSONType, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    projects: Mapped[list["Project"]] = relationship(back_populates="brand")


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    # brand_id es opcional a propósito: un proyecto puede existir sin
    # marca asociada (prueba rápida, cliente nuevo sin brief todavía) —
    # brand_name sigue siendo el campo de texto libre que ya existía,
    # se conserva para no romper proyectos previos a esta migración.
    brand_id: Mapped[str | None] = mapped_column(
        ForeignKey("brands.id", ondelete="SET NULL"))
    brand_name: Mapped[str] = mapped_column(String(120), nullable=False)
    product_name: Mapped[str] = mapped_column(String(120), nullable=False)
    campaign_goal: Mapped[str | None] = mapped_column(String(60))
    platform: Mapped[str | None] = mapped_column(String(40))
    target_duration_sec: Mapped[int] = mapped_column(Integer, default=35)
    current_stage: Mapped[str] = mapped_column(String(20), default="research")
    stage_status: Mapped[str] = mapped_column(String(30), default="pending")
    auto_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_counts: Mapped[dict] = mapped_column(JSONType, default=dict)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_now, onupdate=_now)

    brand: Mapped["Brand | None"] = relationship(back_populates="projects")
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="project", cascade="all, delete-orphan")
    clips: Mapped[list[Clip]] = relationship(
        back_populates="project", cascade="all, delete-orphan")

    __table_args__ = (Index("idx_projects_stage", "current_stage",
                            "stage_status"),)


# ---------------------------------------------------------- artefactos


class Artifact(Base, TimestampMixin):
    """
    Inmutable: corregir es insertar una versión nueva, nunca UPDATE del
    payload. Lo único mutable es `status`.
    """

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    created_by: Mapped[str] = mapped_column(String(30), nullable=False)
    input_ref: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"))
    clip_id: Mapped[str | None] = mapped_column(
        ForeignKey("clips.id", ondelete="CASCADE"))
    # Duplicado no nulo de clip_id ('' para artefactos de proyecto).
    #
    # SQL trata cada NULL como distinto, así que una restricción única sobre
    # clip_id nullable NO impide dos artefactos con el mismo
    # project+type+version cuando ambos son de proyecto. Postgres 15 tiene
    # NULLS NOT DISTINCT, pero SQLite no, y las pruebas corren en SQLite.
    #
    # Esta columna hace la garantía portable y explícita.
    clip_key: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    schema_version: Mapped[str] = mapped_column(String(10), default="v1")
    errors: Mapped[list] = mapped_column(JSONType, default=list)

    project: Mapped[Project] = relationship(back_populates="artifacts")

    __table_args__ = (
        UniqueConstraint("project_id", "type", "version", "clip_key",
                         name="uq_artifact_version"),
        Index("idx_artifacts_lookup", "project_id", "type", "status", "version"),
    )


# --------------------------------------------------------------- clips


class Clip(Base, TimestampMixin):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(8), nullable=False)   # 'C01'
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str | None] = mapped_column(String(20))
    start_sec: Mapped[float | None] = mapped_column(Float)
    end_sec: Mapped[float | None] = mapped_column(Float)
    dialogue: Mapped[str | None] = mapped_column(Text)
    avatar_id: Mapped[str | None] = mapped_column(
        ForeignKey("avatar_library.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    current_audit_score: Mapped[int | None] = mapped_column(Integer)

    project: Mapped[Project] = relationship(back_populates="clips")
    assets: Mapped[list["AssetRow"]] = relationship(
        back_populates="clip", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("project_id", "code",
                                       name="uq_clip_code"),)


# -------------------------------------------------------------- assets


class AssetRow(Base, TimestampMixin):
    """
    Sufijo "Row" por el mismo motivo que JobRow: existe un `Asset`
    Pydantic en app.services (el que ya usan los tres servicios de
    generación) y una importación sin alias de ambos se pisaría en
    silencio.
    """

    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    clip_id: Mapped[str | None] = mapped_column(
        ForeignKey("clips.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_url: Mapped[str] = mapped_column(Text, nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    source_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"))
    provider: Mapped[str | None] = mapped_column(String(40))
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    asset_metadata: Mapped[dict] = mapped_column("metadata", JSONType,
                                                 default=dict)

    clip: Mapped[Clip | None] = relationship(back_populates="assets")

    __table_args__ = (
        Index("idx_assets_clip", "clip_id", "kind", "version"),
        # Una sola variante seleccionada por clip y tipo. Sin esto, el Editor
        # puede ensamblar dos versiones distintas del mismo clip — un fallo
        # que aparece tarde y cuesta encontrar.
        Index("idx_assets_one_selected", "clip_id", "kind", unique=True,
              postgresql_where=(is_selected.is_(True)),
              sqlite_where=(is_selected.is_(True))),
    )


# ---------------------------------------------------------- agent_runs


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    clip_id: Mapped[str | None] = mapped_column(
        ForeignKey("clips.id", ondelete="SET NULL"))
    agent_number: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_name: Mapped[str] = mapped_column(String(40), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="running")
    input_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"))
    output_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"))
    prompt_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"))
    model_used: Mapped[str | None] = mapped_column(String(60))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[str] = mapped_column(String(20), default="orchestrator")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("agent_number BETWEEN 1 AND 12", name="ck_agent_number"),
        Index("idx_runs_project", "project_id", "started_at"),
        Index("idx_runs_agent", "agent_number", "status"),
    )


# ------------------------------------------------------------- jobs


class JobRow(Base, TimestampMixin):
    """
    Trabajos asíncronos de generación.

    Esta tabla no estaba en el esquema original: apareció en la fase 5, cuando
    el video obligó a separar envío de recogida. `provider_job_id` es lo que
    permite recuperar un trabajo si el proceso muere con él en vuelo.
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    clip_id: Mapped[str | None] = mapped_column(
        ForeignKey("clips.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), default="video")
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_job_id: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    polls: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    result_url: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # La idempotencia se garantiza en la base de datos, no sólo en
        # memoria: dos procesos concurrentes no pueden crear el mismo trabajo.
        UniqueConstraint("idempotency_key", name="uq_job_idempotency"),
        Index("idx_jobs_inflight", "status", "provider_job_id"),
    )


# -------------------------------------------------------- aprobaciones


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"))
    asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    feedback: Mapped[str | None] = mapped_column(Text)
    selected_option: Mapped[str | None] = mapped_column(String(16))
    decided_by: Mapped[str | None] = mapped_column(String(32))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=_now)

    __table_args__ = (
        CheckConstraint("decision IN ('approved','rejected','edited')",
                        name="ck_approval_decision"),
        CheckConstraint("artifact_id IS NOT NULL OR asset_id IS NOT NULL",
                        name="ck_approval_target"),
    )


# --------------------------------------------------------- auditoría


class ClipAudit(Base, TimestampMixin):
    __tablename__ = "clip_audits"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    clip_id: Mapped[str] = mapped_column(
        ForeignKey("clips.id", ondelete="CASCADE"), nullable=False)
    cycle: Mapped[int] = mapped_column(Integer, default=1)
    scores: Mapped[dict] = mapped_column(JSONType, nullable=False)
    realism_score: Mapped[int] = mapped_column(Integer, nullable=False)
    ad_score: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    issue_category: Mapped[str | None] = mapped_column(String(30))
    issue_description: Mapped[str | None] = mapped_column(Text)
    route_to_agent: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        # La regla del documento maestro, en la base de datos: un rechazo sin
        # responsable obligaría a regenerar el anuncio entero.
        CheckConstraint("decision = 'approved' OR route_to_agent IS NOT NULL",
                        name="ck_audit_route_required"),
        CheckConstraint(
            "route_to_agent IS NULL OR route_to_agent BETWEEN 1 AND 12",
            name="ck_audit_route_range"),
    )


# --------------------------------------------------------- bibliotecas


class AvatarLibraryRow(Base, TimestampMixin):
    __tablename__ = "avatar_library"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    bible: Mapped[dict] = mapped_column(JSONType, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    avg_realism_score: Mapped[float | None] = mapped_column(Float)

    references: Mapped[list[AvatarReference]] = relationship(
        back_populates="avatar", cascade="all, delete-orphan")


class AvatarReference(Base, TimestampMixin):
    __tablename__ = "avatar_references"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    avatar_id: Mapped[str] = mapped_column(
        ForeignKey("avatar_library.id", ondelete="CASCADE"), nullable=False)
    angle: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_canonical: Mapped[bool] = mapped_column(Boolean, default=False)

    avatar: Mapped[AvatarLibraryRow] = relationship(back_populates="references")

    __table_args__ = (UniqueConstraint("avatar_id", "angle",
                                       name="uq_avatar_angle"),)


class PromptLibraryRow(Base, TimestampMixin):
    __tablename__ = "prompt_library"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    agent_number: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)

    versions: Mapped[list[PromptVersion]] = relationship(
        back_populates="prompt", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("agent_number BETWEEN 1 AND 12",
                        name="ck_prompt_agent_number"),
    )


class PromptVersion(Base, TimestampMixin):
    __tablename__ = "prompt_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    prompt_id: Mapped[str] = mapped_column(
        ForeignKey("prompt_library.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    blocks: Mapped[dict | None] = mapped_column(JSONType)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[float | None] = mapped_column(Float)
    avg_audit_score: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)

    prompt: Mapped[PromptLibraryRow] = relationship(back_populates="versions")

    __table_args__ = (
        UniqueConstraint("prompt_id", "version", name="uq_prompt_version"),
        Index("idx_prompt_one_active", "prompt_id", unique=True,
              postgresql_where=(is_active.is_(True)),
              sqlite_where=(is_active.is_(True))),
    )


# ------------------------------------------------ métricas y memoria


class CampaignMetric(Base):
    __tablename__ = "campaign_metrics"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  nullable=False)
    impressions: Mapped[int | None] = mapped_column(Integer)
    ctr: Mapped[float | None] = mapped_column(Float)
    hook_rate: Mapped[float | None] = mapped_column(Float)
    cpa: Mapped[float | None] = mapped_column(Float)
    roas: Mapped[float | None] = mapped_column(Float)
    spend_usd: Mapped[float | None] = mapped_column(Float)
    raw: Mapped[dict] = mapped_column(JSONType, default=dict)

    __table_args__ = (UniqueConstraint("project_id", "measured_at",
                                       name="uq_metric_day"),)


class CreativeMemoryRow(Base, TimestampMixin):
    __tablename__ = "creative_memory"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    scope: Mapped[str] = mapped_column(String(20), default="brand")
    scope_value: Mapped[str | None] = mapped_column(String(120))
    insight: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    applies_to: Mapped[list] = mapped_column(JSONType, default=list)
    evidence: Mapped[dict] = mapped_column(JSONType, default=dict)
    source_project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint("confidence IN ('alta','media','baja')",
                        name="ck_memory_confidence"),
        Index("idx_memory_scope", "scope", "scope_value", "is_active"),
    )
