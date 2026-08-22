"""
Agente 12 — Analista de resultados.

El riesgo específico de este agente: escribir en creative_memory un
aprendizaje sacado de una sola campaña, que después los Agentes 1-3 tratan
como ley. Por eso ningún insight puede declararse de confianza alta sin
declarar de qué proyectos y con cuánto gasto salió.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .base import (
    ApprovalIssue,
    ArtifactBase,
    ArtifactType,
    Confidence,
    Severity,
)


class Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    impressions: int = Field(ge=0)
    ctr: float = Field(ge=0, le=1)
    hook_rate: float = Field(ge=0, le=1)     # % que pasa del segundo 3
    cpa: float | None = Field(default=None, ge=0)
    roas: float | None = Field(default=None, ge=0)
    spend_usd: float = Field(ge=0)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_codes: list[str] = Field(min_length=1)
    total_impressions: int = Field(ge=0)
    total_spend_usd: float = Field(ge=0)


class Insight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=15)
    confidence: Confidence
    applies_to: list[str] = Field(min_length=1)   # ['hook_type','avatar_id']
    scope: str = "brand"                          # brand | category | global
    scope_value: str | None = None
    evidence: Evidence

    MIN_PROJECTS_FOR_HIGH: ClassVar[int] = 3
    MIN_IMPRESSIONS_FOR_HIGH: ClassVar[int] = 10_000

    @model_validator(mode="after")
    def _confidence_needs_evidence(self):
        if self.confidence is Confidence.ALTA:
            if len(self.evidence.project_codes) < self.MIN_PROJECTS_FOR_HIGH:
                raise ValueError(
                    f"confianza alta requiere al menos "
                    f"{self.MIN_PROJECTS_FOR_HIGH} campañas de evidencia"
                )
            if self.evidence.total_impressions < self.MIN_IMPRESSIONS_FOR_HIGH:
                raise ValueError(
                    f"confianza alta requiere al menos "
                    f"{self.MIN_IMPRESSIONS_FOR_HIGH} impresiones acumuladas"
                )
        return self


class CampaignLearnings(ArtifactBase):
    artifact: ArtifactType = ArtifactType.CAMPAIGN_LEARNINGS

    project_code: str
    metrics: Metrics
    insights: list[Insight] = Field(default_factory=list)

    def writable_to_memory(self) -> list[Insight]:
        """Sólo los insights de confianza alta alimentan creative_memory."""
        return [i for i in self.insights if i.confidence is Confidence.ALTA]

    def approval_check(self) -> list[ApprovalIssue]:
        issues: list[ApprovalIssue] = []

        if not self.insights:
            issues.append(ApprovalIssue(
                code="no_insights",
                message="La campaña no produjo ningún aprendizaje; el loop de "
                        "mejora queda abierto.",
                field="insights",
            ))

        if self.insights and not self.writable_to_memory():
            issues.append(ApprovalIssue(
                code="no_high_confidence_insight",
                message="Ningún insight alcanza confianza alta; nada se "
                        "escribirá en creative_memory todavía.",
                severity=Severity.WARNING,
                field="insights",
            ))

        # Muestra insuficiente: cualquier conclusión aquí es ruido.
        if self.metrics.impressions < 1000:
            issues.append(ApprovalIssue(
                code="sample_too_small",
                message=f"{self.metrics.impressions} impresiones son muy pocas "
                        f"para concluir nada.",
                field="metrics.impressions",
            ))

        return issues
