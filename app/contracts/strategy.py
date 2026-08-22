"""Agente 2 — Estratega de anuncios."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .base import (
    ApprovalIssue,
    ArtifactBase,
    ArtifactType,
    Severity,
    is_placeholder,
    too_similar,
)


class AwarenessLevel(str, Enum):
    UNAWARE = "unaware"
    PROBLEM_AWARE = "problem_aware"
    SOLUTION_AWARE = "solution_aware"
    PRODUCT_AWARE = "product_aware"
    MOST_AWARE = "most_aware"


class Angle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    angle_id: str = Field(pattern=r"^A\d{2}$")   # A01, A02, A03
    name: str
    premise: str
    emotion: str
    recommended_format: str
    memory_backed: bool = False  # ¿viene de un aprendizaje de creative_memory?


class Strategy(ArtifactBase):
    artifact: ArtifactType = ArtifactType.STRATEGY

    awareness_level: AwarenessLevel
    primary_pain: str
    primary_desire: str
    objections: list[str] = Field(default_factory=list)
    unique_mechanism: str
    angles: list[Angle] = Field(min_length=3, max_length=3)

    @field_validator("angles")
    @classmethod
    def _unique_ids(cls, v: list[Angle]) -> list[Angle]:
        ids = [a.angle_id for a in v]
        if len(set(ids)) != len(ids):
            raise ValueError("angle_id duplicado")
        return v

    def approval_check(self) -> list[ApprovalIssue]:
        issues: list[ApprovalIssue] = []

        for field in ("primary_pain", "primary_desire", "unique_mechanism"):
            if is_placeholder(getattr(self, field)):
                issues.append(ApprovalIssue(
                    code="placeholder_field",
                    message=f"'{field}' quedó sin contenido real.",
                    field=field,
                ))

        # El fallo clásico del Agente 2: entregar el mismo ángulo tres veces
        # con distinta redacción. Se compara la premisa, no el nombre.
        for i in range(len(self.angles)):
            for j in range(i + 1, len(self.angles)):
                a, b = self.angles[i], self.angles[j]
                if too_similar(a.premise, b.premise):
                    issues.append(ApprovalIssue(
                        code="angles_not_distinct",
                        message=f"Los ángulos {a.angle_id} y {b.angle_id} "
                                f"parecen variaciones de la misma idea.",
                        # Advertencia y no bloqueo: la similitud léxica es un
                        # indicio, no una prueba. Además el humano elige el
                        # ángulo justo en este paso, así que basta con
                        # levantarle la bandera en el dashboard.
                        severity=Severity.WARNING,
                        field="angles",
                    ))

        if not self.objections:
            issues.append(ApprovalIssue(
                code="no_objections",
                message="Sin objeciones identificadas el guion no podrá "
                        "rebatir nada.",
                severity=Severity.WARNING,
                field="objections",
            ))

        return issues
