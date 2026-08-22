"""Agente 6 — Arquitecto de identidad."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from .base import ApprovalIssue, ArtifactBase, ArtifactType, Severity, is_placeholder

REQUIRED_ANGLES = ["frontal", "3/4_izq", "perfil_izq", "3/4_der", "perfil_der"]


class PhysicalTraits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age_range: str
    origin: str
    face: str
    hair: str
    skin: str
    build: str
    distinguishing_features: list[str] = Field(default_factory=list)


class CharacterBible(ArtifactBase):
    artifact: ArtifactType = ArtifactType.CHARACTER_BIBLE

    avatar_id: str = Field(pattern=r"^AV-[A-Z]+-[A-Z]{2}-\d{3}$")  # AV-FEMALE-EC-001
    display_name: str
    physical: PhysicalTraits
    personality: str
    speech_style: str
    wardrobe_allowed: list[str] = Field(min_length=1)
    wardrobe_forbidden: list[str] = Field(default_factory=list)
    natural_imperfections: list[str] = Field(default_factory=list)
    frequent_scenarios: list[str] = Field(default_factory=list)
    reference_angles_needed: list[str] = Field(default=REQUIRED_ANGLES.copy())

    MIN_IMPERFECTIONS: ClassVar[int] = 3

    def approval_check(self) -> list[ApprovalIssue]:
        issues: list[ApprovalIssue] = []

        # Un solo campo físico vago arruina la consistencia entre clips:
        # el modelo rellena el hueco distinto cada vez que genera.
        for field, value in self.physical.model_dump().items():
            if isinstance(value, str) and is_placeholder(value):
                issues.append(ApprovalIssue(
                    code="vague_physical_trait",
                    message=f"El rasgo físico '{field}' quedó sin definir; "
                            f"el generador lo improvisará distinto cada vez.",
                    field=f"physical.{field}",
                ))

        # El núcleo del método: el objetivo no es el avatar más perfecto,
        # es el menos sospechosamente perfecto.
        if len(self.natural_imperfections) < self.MIN_IMPERFECTIONS:
            issues.append(ApprovalIssue(
                code="insufficient_imperfections",
                message=f"Sólo {len(self.natural_imperfections)} imperfecciones "
                        f"declaradas; el mínimo es {self.MIN_IMPERFECTIONS}. Sin "
                        f"ellas el avatar sale con acabado publicitario.",
                field="natural_imperfections",
            ))

        missing = [a for a in REQUIRED_ANGLES if a not in self.reference_angles_needed]
        if missing:
            issues.append(ApprovalIssue(
                code="missing_reference_angles",
                message=f"Faltan ángulos de referencia: {', '.join(missing)}.",
                field="reference_angles_needed",
            ))

        if not self.wardrobe_forbidden:
            issues.append(ApprovalIssue(
                code="no_wardrobe_limits",
                message="Sin vestuario prohibido, el generador puede meter "
                        "branding o ropa fuera de personaje.",
                severity=Severity.WARNING,
                field="wardrobe_forbidden",
            ))

        return issues
