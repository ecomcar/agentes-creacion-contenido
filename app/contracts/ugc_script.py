"""Agente 4 — Guionista UGC."""

from __future__ import annotations

from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .base import ApprovalIssue, ArtifactBase, ArtifactType, Severity, is_placeholder


class ClipRole(str, Enum):
    HOOK = "hook"
    PROBLEMA = "problema"
    DESCUBRIMIENTO = "descubrimiento"
    DEMOSTRACION = "demostracion"
    RESULTADO = "resultado"
    CTA = "cta"


class ScriptClip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_id: str = Field(pattern=r"^C\d{2}$")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    role: ClipRole
    dialogue: str

    @model_validator(mode="after")
    def _coherent_times(self):
        if self.end <= self.start:
            raise ValueError(f"{self.clip_id}: end debe ser mayor que start")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class UGCScript(ArtifactBase):
    artifact: ArtifactType = ArtifactType.UGC_SCRIPT

    hook_id: str = Field(pattern=r"^H\d{2}$")
    target_duration_sec: float = Field(gt=0)
    total_duration_sec: float = Field(gt=0)
    clips: list[ScriptClip] = Field(min_length=2, max_length=12)
    cta: str

    DURATION_TOLERANCE: ClassVar[float] = 0.10  # ±10% sobre el objetivo

    @field_validator("clips")
    @classmethod
    def _sequential_and_unique(cls, v: list[ScriptClip]) -> list[ScriptClip]:
        ids = [c.clip_id for c in v]
        if len(set(ids)) != len(ids):
            raise ValueError("clip_id duplicado")
        # Los clips deben encadenarse sin huecos ni solapes: el montaje
        # posterior asume una línea de tiempo continua.
        for prev, cur in zip(v, v[1:]):
            if abs(cur.start - prev.end) > 0.01:
                raise ValueError(
                    f"discontinuidad entre {prev.clip_id} y {cur.clip_id}"
                )
        return v

    def approval_check(self) -> list[ApprovalIssue]:
        issues: list[ApprovalIssue] = []

        lo = self.target_duration_sec * (1 - self.DURATION_TOLERANCE)
        hi = self.target_duration_sec * (1 + self.DURATION_TOLERANCE)
        if not lo <= self.total_duration_sec <= hi:
            issues.append(ApprovalIssue(
                code="duration_out_of_range",
                message=f"Duración {self.total_duration_sec}s fuera del rango "
                        f"{lo:.1f}-{hi:.1f}s.",
                field="total_duration_sec",
            ))

        roles = {c.role for c in self.clips}
        if ClipRole.HOOK not in roles:
            issues.append(ApprovalIssue(
                code="missing_hook_clip",
                message="Ningún clip tiene el rol 'hook'.", field="clips",
            ))
        if ClipRole.CTA not in roles:
            issues.append(ApprovalIssue(
                code="missing_cta_clip",
                message="Ningún clip tiene el rol 'cta'.", field="clips",
            ))

        if is_placeholder(self.cta):
            issues.append(ApprovalIssue(
                code="missing_cta_text",
                message="El CTA está vacío.", field="cta",
            ))

        # El hook se juega en los primeros segundos. Si el primer clip dura
        # más de 5s, probablemente no es un hook sino una introducción.
        first = self.clips[0]
        if first.role is ClipRole.HOOK and first.duration > 5:
            issues.append(ApprovalIssue(
                code="hook_too_long",
                message=f"El hook dura {first.duration:.1f}s; por encima de 5s "
                        f"pierde función de interrupción.",
                severity=Severity.WARNING,
                field="clips",
            ))

        for c in self.clips:
            if is_placeholder(c.dialogue) and c.role is not ClipRole.DEMOSTRACION:
                issues.append(ApprovalIssue(
                    code="empty_dialogue",
                    message=f"{c.clip_id} no tiene diálogo.",
                    field="clips",
                ))

        return issues
