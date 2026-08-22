"""Agente 1 — Investigación del producto."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .base import ApprovalIssue, ArtifactBase, ArtifactType, Severity, is_placeholder


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    category: str
    price_range: str | None = None
    core_benefit: str
    attributes: list[str] = Field(default_factory=list)


class AudienceSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age_range: str | None = None
    location: str | None = None
    known_pain_points: list[str] = Field(default_factory=list)
    source: str | None = None  # 'cliente' | 'web' | 'inferido'


class Competitor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    angle_observed: str
    url: str | None = None


class Constraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_voice: str | None = None
    forbidden_claims: list[str] = Field(default_factory=list)
    legal_notes: str | None = None


class ResearchBrief(ArtifactBase):
    artifact: ArtifactType = ArtifactType.RESEARCH_BRIEF

    product: Product
    audience_signals: AudienceSignals
    competitors: list[Competitor] = Field(default_factory=list, max_length=5)
    constraints: Constraints = Field(default_factory=Constraints)

    def approval_check(self) -> list[ApprovalIssue]:
        issues: list[ApprovalIssue] = []

        if is_placeholder(self.product.core_benefit):
            issues.append(ApprovalIssue(
                code="missing_core_benefit",
                message="El beneficio central del producto no está definido.",
                field="product.core_benefit",
            ))

        sig = self.audience_signals
        if not sig.known_pain_points and not sig.age_range and not sig.location:
            issues.append(ApprovalIssue(
                code="no_audience_data",
                message="No hay ninguna señal de audiencia. El Estratega no "
                        "puede definir awareness sin esto.",
                field="audience_signals",
            ))

        # Advertencia, no bloqueo: se puede trabajar sin competencia,
        # pero los ángulos salen peor diferenciados.
        if not self.competitors:
            issues.append(ApprovalIssue(
                code="no_competitors",
                message="Sin competencia analizada; los ángulos podrían "
                        "repetir lo que ya dice el mercado.",
                severity=Severity.WARNING,
                field="competitors",
            ))

        return issues
