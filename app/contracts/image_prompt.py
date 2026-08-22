"""Agente 7 — Prompt Engineer de imagen (Nano Banana / equivalente)."""

from __future__ import annotations

from enum import Enum
from typing import ClassVar

from pydantic import Field

from .base import ApprovalIssue, ArtifactBase, ArtifactType, Severity


class SceneTemplate(str, Enum):
    CHARACTER_CREATION = "character_creation"
    SELFIE = "selfie"
    PRODUCT_HOLDING = "product_holding"
    BATHROOM_MIRROR = "bathroom_mirror"
    KITCHEN = "kitchen"
    CAR = "car"
    DESK = "desk"
    BEFORE_AFTER = "before_after"
    DEMONSTRATION = "demonstration"
    REACTION = "reaction"


# Lenguaje que produce acabado de comercial. Es exactamente lo que el
# método intenta evitar, así que se bloquea en el prompt, no después.
COMMERCIAL_TERMS = {
    "perfect skin", "flawless", "cinematic lighting", "professional model",
    "beauty shot", "advertising", "studio lighting", "glamour", "8k",
    "hyperrealistic", "masterpiece", "photoshoot", "piel perfecta",
}


class ImagePrompt(ArtifactBase):
    artifact: ArtifactType = ArtifactType.IMAGE_PROMPT

    avatar_id: str = Field(pattern=r"^AV-[A-Z]+-[A-Z]{2}-\d{3}$")
    template_code: str                       # 'NB_SELFIE_UGC'
    template_version: int = Field(ge=1)      # 3  →  NB_SELFIE_UGC_V3
    scene: SceneTemplate
    prompt_text: str = Field(min_length=40)
    identity_reference_used: bool            # ¿usa la referencia o redescribe?
    imperfections_included: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)

    MIN_IMPERFECTIONS: ClassVar[int] = 2

    @property
    def template_id(self) -> str:
        return f"{self.template_code}_V{self.template_version}"

    def approval_check(self) -> list[ApprovalIssue]:
        issues: list[ApprovalIssue] = []

        # La regla que sostiene toda la consistencia de rostro: el prompt
        # ancla en la referencia del avatar, no vuelve a describirlo.
        if not self.identity_reference_used:
            issues.append(ApprovalIssue(
                code="identity_not_anchored",
                message="El prompt describe al personaje desde cero en vez de "
                        "anclarse en la referencia del Character Bible. "
                        "Garantiza deriva de rostro entre clips.",
                field="identity_reference_used",
            ))

        if len(self.imperfections_included) < self.MIN_IMPERFECTIONS:
            issues.append(ApprovalIssue(
                code="insufficient_imperfections",
                message=f"El prompt incluye {len(self.imperfections_included)} "
                        f"imperfecciones; mínimo {self.MIN_IMPERFECTIONS}.",
                field="imperfections_included",
            ))

        lowered = self.prompt_text.lower()
        found = sorted(t for t in COMMERCIAL_TERMS if t in lowered)
        if found:
            issues.append(ApprovalIssue(
                code="commercial_language",
                message=f"Lenguaje de comercial en el prompt: {', '.join(found)}. "
                        f"Produce el acabado que el método evita.",
                field="prompt_text",
            ))

        if not self.negative_constraints:
            issues.append(ApprovalIssue(
                code="no_negative_constraints",
                message="Sin restricciones negativas declaradas.",
                severity=Severity.WARNING,
                field="negative_constraints",
            ))

        return issues
