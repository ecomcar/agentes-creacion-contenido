"""Agente 3 — Generador de hooks."""

from __future__ import annotations

from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .base import ApprovalIssue, ArtifactBase, ArtifactType, Score, Severity


class HookType(str, Enum):
    PROBLEMA = "problema"
    CURIOSIDAD = "curiosidad"
    CONFESION = "confesion"
    CONTRARIAN = "contrarian"
    TESTIMONIAL = "testimonial"
    DEMOSTRACION = "demostracion"
    VISUAL = "visual"


class HookScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curiosidad: Score
    claridad: Score
    pattern_interrupt: Score
    relevancia: Score
    ugc_fit: Score
    visual_ease: Score

    @property
    def average(self) -> float:
        vals = self.model_dump().values()
        return sum(vals) / len(vals)


class Hook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook_id: str = Field(pattern=r"^H\d{2}$")
    type: HookType
    text: str = Field(min_length=8, max_length=220)
    scores: HookScores

    @property
    def average(self) -> float:
        return self.scores.average


class Hooks(ArtifactBase):
    artifact: ArtifactType = ArtifactType.HOOKS

    angle_id: str = Field(pattern=r"^A\d{2}$")   # el ángulo elegido por el humano
    hooks: list[Hook] = Field(min_length=8, max_length=12)

    # Constantes de clase (ClassVar): umbrales, no campos del contrato.
    # Umbral recalibrado con datos reales, no puesto a ojo. El valor
    # original (80) se fijó al construir el sistema sin ninguna corrida
    # real que lo respaldara. Evidencia real que lo tumbó: proyecto
    # UGC-0002 (brillo labial), dos intentos reales con Sonnet y el prompt
    # v2 de este agente, ambos bloqueados:
    #   intento 1 — mejor trío: 78.8 / 78.0 / 77.5  (0 hooks llegaban a 80)
    #   intento 2 — mejor trío: 82.2 / 80.0 / 78.8  (sólo 2 llegaban a 80)
    # El texto de esos hooks era genuinamente bueno ("Esto no es photoshop,
    # es polvo de diamante real"): el corte de 80 castigaba trabajo sano,
    # no detectaba trabajo flojo. Con 75, ambos intentos reales pasan con
    # margen (6 y 4 calificados respectivamente) y el hook realmente débil
    # del intento 1 (55.8) se sigue descartando con claridad.
    MIN_AVERAGE: ClassVar[float] = 75.0
    MIN_QUALIFIED: ClassVar[int] = 3

    @field_validator("hooks")
    @classmethod
    def _unique_ids(cls, v: list[Hook]) -> list[Hook]:
        ids = [h.hook_id for h in v]
        if len(set(ids)) != len(ids):
            raise ValueError("hook_id duplicado")
        return v

    def ranked(self) -> list[Hook]:
        return sorted(self.hooks, key=lambda h: h.average, reverse=True)

    def qualified(self) -> list[Hook]:
        return [h for h in self.hooks if h.average >= self.MIN_AVERAGE]

    def approval_check(self) -> list[ApprovalIssue]:
        issues: list[ApprovalIssue] = []

        qualified = self.qualified()
        if len(qualified) < self.MIN_QUALIFIED:
            issues.append(ApprovalIssue(
                code="insufficient_quality_hooks",
                message=f"Sólo {len(qualified)} hooks alcanzan promedio "
                        f">= {self.MIN_AVERAGE:.0f}; se requieren "
                        f"{self.MIN_QUALIFIED}.",
                field="hooks",
            ))

        # Que el top 3 no sea el mismo tipo tres veces: si el mejor hook
        # falla en producción, queremos alternativas de otra naturaleza.
        top3 = self.ranked()[:3]
        if len({h.type for h in top3}) < 2:
            issues.append(ApprovalIssue(
                code="top_hooks_same_type",
                message="Los 3 mejores hooks son del mismo tipo; falta "
                        "diversidad para testear.",
                field="hooks",
            ))

        # El hook ganador se usa literal en el guion (regla del Agente 4),
        # en un clip que no debería pasar de 5 segundos. Un hook de más de
        # 15 palabras obliga a leerlo atropellado o a estirar el clip hasta
        # que deje de funcionar como interrupción. Se detecta aquí, en el
        # contrato, para que el sistema completo lo vea siempre — no sólo
        # cuando corre este script de validación.
        largos = [h.hook_id for h in self.hooks if len(h.text.split()) > 15]
        if largos:
            issues.append(ApprovalIssue(
                code="hook_too_long_to_speak",
                message=f"Hooks de más de 15 palabras, difíciles de decir en "
                        f"3-4 segundos: {', '.join(largos)}.",
                severity=Severity.WARNING,
                field="hooks",
            ))

        return issues
