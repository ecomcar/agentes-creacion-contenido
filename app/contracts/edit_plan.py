"""Agente 10 — Editor."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .base import ApprovalIssue, ArtifactBase, ArtifactType, Severity


class Transition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    after_clip: str = Field(pattern=r"^C\d{2}$")
    kind: str                        # 'cut' | 'jump_cut' | 'zoom' | 'whip'


class SfxCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at_clip: str = Field(pattern=r"^C\d{2}$")
    track: str
    moment: str                      # 'hook' | 'demo' | 'reveal' | 'cta'


class EditPlan(ArtifactBase):
    artifact: ArtifactType = ArtifactType.EDIT_PLAN

    clip_order: list[str] = Field(min_length=2)
    expected_clip_ids: list[str] = Field(min_length=2)   # los del guion
    script_duration_sec: float = Field(gt=0)
    assembled_duration_sec: float = Field(gt=0)
    transitions: list[Transition] = Field(default_factory=list)
    subtitles: bool = True
    music_track: str | None = None
    sfx: list[SfxCue] = Field(default_factory=list)
    broll: list[str] = Field(default_factory=list)

    DURATION_TOLERANCE: ClassVar[float] = 0.10

    @field_validator("clip_order")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("clip repetido en clip_order")
        return v

    def approval_check(self) -> list[ApprovalIssue]:
        issues: list[ApprovalIssue] = []

        missing = [c for c in self.expected_clip_ids if c not in self.clip_order]
        if missing:
            issues.append(ApprovalIssue(
                code="clips_missing_in_edit",
                message=f"El montaje omite clips del guion: {', '.join(missing)}.",
                field="clip_order",
            ))

        lo = self.script_duration_sec * (1 - self.DURATION_TOLERANCE)
        hi = self.script_duration_sec * (1 + self.DURATION_TOLERANCE)
        if not lo <= self.assembled_duration_sec <= hi:
            issues.append(ApprovalIssue(
                code="assembled_duration_drift",
                message=f"El ensamblado dura {self.assembled_duration_sec}s "
                        f"frente a {self.script_duration_sec}s del guion.",
                field="assembled_duration_sec",
            ))

        if not self.subtitles:
            issues.append(ApprovalIssue(
                code="no_subtitles",
                message="Sin subtítulos se pierde la mayoría del público que "
                        "ve sin sonido.",
                severity=Severity.WARNING,
                field="subtitles",
            ))

        return issues
