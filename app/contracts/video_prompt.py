"""Agente 8 — Director de video (Kling / equivalente)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .base import ApprovalIssue, ArtifactBase, ArtifactType, Severity, is_placeholder


class PromptBlocks(BaseModel):
    """
    Prompt compuesto por bloques con responsabilidad separada.

    El agente no redacta un párrafo libre: rellena casillas. Eso da
    consistencia entre clips y permite corregir un solo bloque cuando el
    Auditor detecta, por ejemplo, un gesto imposible — sin tocar cámara,
    física ni producto.
    """

    model_config = ConfigDict(extra="forbid")

    camera: str
    subject_action: str
    microgestures: str
    performance: str
    physics: str
    product_constraint: str = ""     # vacío legítimo si el producto no sale
    negative_behavior: str

    def as_prompt(self) -> str:
        parts = [
            ("CAMERA", self.camera),
            ("SUBJECT ACTION", self.subject_action),
            ("MICROGESTURES", self.microgestures),
            ("PERFORMANCE", self.performance),
            ("PHYSICS", self.physics),
            ("PRODUCT", self.product_constraint),
            ("AVOID", self.negative_behavior),
        ]
        return "\n\n".join(f"[{k}]\n{v}" for k, v in parts if v.strip())


class VideoPrompt(ArtifactBase):
    artifact: ArtifactType = ArtifactType.VIDEO_PROMPT

    image_asset_id: str              # imagen base ya seleccionada
    pattern_code: str                # 'KL_TALKING_SELFIE'
    pattern_version: int = Field(ge=1)
    duration_sec: float = Field(gt=0, le=15)   # los modelos actuales no dan más
    blocks: PromptBlocks

    @property
    def pattern_id(self) -> str:
        return f"{self.pattern_code}_V{self.pattern_version}"

    def approval_check(self) -> list[ApprovalIssue]:
        issues: list[ApprovalIssue] = []

        required = [
            "camera", "subject_action", "microgestures",
            "performance", "physics", "negative_behavior",
        ]
        for name in required:
            if is_placeholder(getattr(self.blocks, name)):
                issues.append(ApprovalIssue(
                    code="empty_block",
                    message=f"El bloque '{name}' está vacío.",
                    field=f"blocks.{name}",
                ))

        # Sin restricciones negativas, el modelo tira a movimiento de
        # comercial: postura perfecta, contacto visual continuo, gesto amplio.
        neg = self.blocks.negative_behavior.lower()
        if neg and not any(k in neg for k in
                           ("perfect", "continuous", "exaggerat", "cinematic",
                            "slow motion", "perfecta", "exagerad")):
            issues.append(ApprovalIssue(
                code="weak_negative_behavior",
                message="Las restricciones negativas no cubren los defectos "
                        "típicos (postura perfecta, contacto visual continuo, "
                        "gestos exagerados, cámara cinematográfica).",
                severity=Severity.WARNING,
                field="blocks.negative_behavior",
            ))

        return issues
