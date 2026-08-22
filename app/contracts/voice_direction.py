"""Agente 9 — Director de voz."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .base import ApprovalIssue, ArtifactBase, ArtifactType, Severity, is_placeholder


class Pace(str, Enum):
    LENTO = "lento"
    MEDIO = "medio"
    MEDIO_RAPIDO = "medio_rapido"
    RAPIDO = "rapido"


class VoiceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str                    # 'es-EC'
    accent: str                      # 'ecuatoriano-neutro'
    age_perception: str              # '27-34'
    pace: Pace
    tone: str
    voice_id: str | None = None      # id del proveedor, si ya está elegida


class VoiceDirection(ArtifactBase):
    artifact: ArtifactType = ArtifactType.VOICE_DIRECTION

    profile: VoiceProfile
    pauses_before: list[str] = Field(default_factory=list)   # palabras clave
    emphasis_words: list[str] = Field(default_factory=list)
    pacing_notes: str
    avoid: list[str] = Field(default_factory=list)

    def approval_check(self) -> list[ApprovalIssue]:
        issues: list[ApprovalIssue] = []

        if is_placeholder(self.pacing_notes) or len(self.pacing_notes) < 25:
            issues.append(ApprovalIssue(
                code="generic_pacing",
                message="Las notas de ritmo son genéricas; sin indicaciones "
                        "concretas la voz sale plana.",
                field="pacing_notes",
            ))

        # El defecto que más delata un UGC generado: entonación de locutor.
        avoid_text = " ".join(self.avoid).lower()
        if not any(k in avoid_text for k in
                   ("locutor", "announcer", "publicitari", "commercial", "radio")):
            issues.append(ApprovalIssue(
                code="no_announcer_guard",
                message="No se prohíbe explícitamente la entonación de locutor "
                        "publicitario.",
                field="avoid",
            ))

        if not self.pauses_before:
            issues.append(ApprovalIssue(
                code="no_pauses",
                message="Sin pausas marcadas, la lectura suena continua y "
                        "artificial.",
                severity=Severity.WARNING,
                field="pauses_before",
            ))

        return issues
