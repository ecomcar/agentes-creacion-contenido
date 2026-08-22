"""Agente 5 — Director visual."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .base import ApprovalIssue, ArtifactBase, ArtifactType, Severity, is_placeholder


class ShotType(str, Enum):
    SELFIE = "selfie"
    MEDIO = "medio"
    DETALLE = "detalle"
    PLANO_GENERAL = "plano_general"
    OVER_SHOULDER = "over_shoulder"
    POV = "pov"


class StoryboardClip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_id: str = Field(pattern=r"^C\d{2}$")
    shot_type: ShotType
    scenario: str
    props: list[str] = Field(default_factory=list)
    action_summary: str
    product_visible: bool = False


class Storyboard(ArtifactBase):
    artifact: ArtifactType = ArtifactType.STORYBOARD

    clips: list[StoryboardClip] = Field(min_length=2)
    script_clip_ids: list[str] = Field(min_length=2)  # los del guion, para cotejar

    @field_validator("clips")
    @classmethod
    def _unique(cls, v: list[StoryboardClip]) -> list[StoryboardClip]:
        ids = [c.clip_id for c in v]
        if len(set(ids)) != len(ids):
            raise ValueError("clip_id duplicado")
        return v

    def approval_check(self) -> list[ApprovalIssue]:
        issues: list[ApprovalIssue] = []

        # Cobertura: cada clip del guion necesita su entrada visual.
        sb_ids = {c.clip_id for c in self.clips}
        missing = [cid for cid in self.script_clip_ids if cid not in sb_ids]
        if missing:
            issues.append(ApprovalIssue(
                code="clips_not_covered",
                message=f"Clips del guion sin storyboard: {', '.join(missing)}.",
                field="clips",
            ))

        extra = [cid for cid in sb_ids if cid not in self.script_clip_ids]
        if extra:
            issues.append(ApprovalIssue(
                code="clips_not_in_script",
                message=f"Storyboard inventa clips que no existen en el guion: "
                        f"{', '.join(sorted(extra))}.",
                field="clips",
            ))

        for c in self.clips:
            if is_placeholder(c.scenario) or is_placeholder(c.action_summary):
                issues.append(ApprovalIssue(
                    code="incomplete_clip",
                    message=f"{c.clip_id}: escenario o acción sin definir.",
                    field="clips",
                ))

        # Continuidad: un cambio de escenario en cada clip rompe la ilusión
        # de que alguien grabó esto con su teléfono en un momento.
        scenarios = [c.scenario.strip().lower() for c in self.clips]
        if len(set(scenarios)) == len(scenarios) and len(scenarios) > 3:
            issues.append(ApprovalIssue(
                code="scenario_discontinuity",
                message="Cada clip ocurre en un escenario distinto; revisar "
                        "continuidad.",
                severity=Severity.WARNING,
                field="clips",
            ))

        if not any(c.product_visible for c in self.clips):
            issues.append(ApprovalIssue(
                code="product_never_visible",
                message="El producto no aparece en ningún clip.",
                field="clips",
            ))

        return issues
