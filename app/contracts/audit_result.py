"""
Agente 11 — Auditor anti-IA (Creative Quality Control).

Aquí vive la regla más importante del sistema: si el Auditor rechaza, está
obligado a decir QUIÉN corrige. Un rechazo sin ruta obliga a regenerar todo
el anuncio, que es exactamente el desperdicio que este diseño evita.

La ruta no la elige el agente libremente: se deriva de la categoría del
problema mediante ERROR_ROUTING. Si el agente propone otra ruta, el contrato
lo marca como incumplimiento.
"""

from __future__ import annotations

from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, model_validator

from .base import ApprovalIssue, ArtifactBase, ArtifactType, Score, Severity


class AuditDecision(str, Enum):
    APPROVED = "approved"
    REGENERATE = "regenerate"
    HUMAN_REVIEW = "human_review"


class IssueCategory(str, Enum):
    IDENTITY = "identity"
    ANATOMY = "anatomy"
    MOTION = "motion"
    PHYSICS = "physics"
    LIP_SYNC = "lip_sync"
    VOICE = "voice"
    PRODUCT = "product"
    CONTINUITY = "continuity"
    UGC_REALISM = "ugc_realism"
    HOOK_VISUAL = "hook_visual"
    PACING = "pacing"
    COMMERCIAL_CLARITY = "commercial_clarity"


# Categoría del problema → agente que debe corregirlo.
# Es la tabla de enrutamiento del documento maestro, ejecutable.
ERROR_ROUTING: dict[IssueCategory, int] = {
    IssueCategory.IDENTITY: 6,            # 11 → 6 → 7 → 8 → 11
    IssueCategory.ANATOMY: 7,             # se corrige en la imagen base
    IssueCategory.MOTION: 8,              # 11 → 8 → 11, sin tocar imagen
    IssueCategory.PHYSICS: 8,
    IssueCategory.LIP_SYNC: 9,
    IssueCategory.VOICE: 9,               # 11 → 9 → 10 → 11
    IssueCategory.PRODUCT: 7,
    IssueCategory.CONTINUITY: 5,          # error de storyboard
    IssueCategory.UGC_REALISM: 8,
    IssueCategory.HOOK_VISUAL: 3,         # 11 → 3 → 4 → 5 → ...
    IssueCategory.PACING: 10,
    IssueCategory.COMMERCIAL_CLARITY: 4,
}


class AuditScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: Score
    anatomy: Score
    motion: Score
    physics: Score
    lip_sync: Score
    voice: Score
    product: Score
    continuity: Score
    ugc_realism: Score
    hook_visual: Score
    pacing: Score
    commercial_clarity: Score

    def weakest(self) -> tuple[str, int]:
        d = self.model_dump()
        k = min(d, key=d.get)
        return k, d[k]


class AuditIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: IssueCategory
    description: str
    route_to_agent: int

    @model_validator(mode="after")
    def _route_matches_category(self):
        expected = ERROR_ROUTING[self.category]
        if self.route_to_agent != expected:
            raise ValueError(
                f"categoría '{self.category.value}' debe enrutarse al agente "
                f"{expected}, no al {self.route_to_agent}"
            )
        return self


class AuditResult(ArtifactBase):
    artifact: ArtifactType = ArtifactType.AUDIT_RESULT

    cycle: int = 1
    scores: AuditScores
    realism_score: Score
    ad_score: Score
    decision: AuditDecision
    issue: AuditIssue | None = None

    MIN_REALISM: ClassVar[int] = 80
    MIN_AD: ClassVar[int] = 75
    MAX_CYCLES: ClassVar[int] = 3

    @model_validator(mode="after")
    def _rejection_needs_route(self):
        if self.decision is AuditDecision.REGENERATE and self.issue is None:
            raise ValueError(
                "un rechazo sin 'issue' obliga a regenerar todo el anuncio; "
                "el Auditor debe identificar qué agente corrige"
            )
        if self.decision is AuditDecision.APPROVED and self.issue is not None:
            raise ValueError("un resultado aprobado no puede llevar 'issue'")
        return self

    @property
    def meets_thresholds(self) -> bool:
        return (self.realism_score >= self.MIN_REALISM
                and self.ad_score >= self.MIN_AD)

    def approval_check(self) -> list[ApprovalIssue]:
        """
        Aquí 'aprobación' significa: ¿es coherente el veredicto del Auditor?
        Los umbrales son deterministas y mandan sobre el juicio del agente —
        si dice 'aprobado' con 62 de realismo, gana el umbral.
        """
        issues: list[ApprovalIssue] = []

        if self.decision is AuditDecision.APPROVED and not self.meets_thresholds:
            issues.append(ApprovalIssue(
                code="approved_below_threshold",
                message=f"Aprobado con realismo {self.realism_score} y anuncio "
                        f"{self.ad_score}; los mínimos son "
                        f"{self.MIN_REALISM}/{self.MIN_AD}.",
                field="decision",
            ))

        if self.decision is AuditDecision.REGENERATE and self.meets_thresholds:
            issues.append(ApprovalIssue(
                code="rejected_above_threshold",
                message="Rechazado pese a superar ambos umbrales; revisar "
                        "criterio del Auditor.",
                severity=Severity.WARNING,
                field="decision",
            ))

        # Tope duro de ciclos: al cuarto intento no seguimos quemando créditos.
        if self.cycle > self.MAX_CYCLES and self.decision is AuditDecision.REGENERATE:
            issues.append(ApprovalIssue(
                code="max_cycles_exceeded",
                message=f"Ciclo {self.cycle} supera el tope de "
                        f"{self.MAX_CYCLES}; corresponde intervención humana.",
                field="cycle",
            ))

        # Coherencia interna: si el eje más bajo no coincide con la categoría
        # reportada, el Auditor está mirando otra cosa que la que puntuó.
        if self.issue is not None:
            weakest_axis, weakest_value = self.scores.weakest()
            if weakest_value < 70 and weakest_axis != self.issue.category.value:
                issues.append(ApprovalIssue(
                    code="issue_axis_mismatch",
                    message=f"El eje más débil es '{weakest_axis}' "
                            f"({weakest_value}) pero el problema reportado es "
                            f"'{self.issue.category.value}'.",
                    severity=Severity.WARNING,
                    field="issue",
                ))

        return issues
