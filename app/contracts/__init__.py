"""
Contratos de los 12 agentes.

El registro permite al Orquestador validar un payload sin saber de antemano
qué agente lo produjo: `parse_artifact(type, payload)`.
"""

from __future__ import annotations

from typing import Any

from .base import (
    AgentError,
    ApprovalIssue,
    ArtifactBase,
    ArtifactStatus,
    ArtifactType,
    Confidence,
    Score,
    Severity,
    is_placeholder,
    too_similar,
)
from .audit_result import (
    ERROR_ROUTING,
    AuditDecision,
    AuditIssue,
    AuditResult,
    AuditScores,
    IssueCategory,
)
from .campaign_learnings import CampaignLearnings, Evidence, Insight, Metrics
from .character_bible import REQUIRED_ANGLES, CharacterBible, PhysicalTraits
from .edit_plan import EditPlan, SfxCue, Transition
from .hooks import Hook, Hooks, HookScores, HookType
from .image_prompt import COMMERCIAL_TERMS, ImagePrompt, SceneTemplate
from .research_brief import (
    AudienceSignals,
    Competitor,
    Constraints,
    Product,
    ResearchBrief,
)
from .storyboard import ShotType, Storyboard, StoryboardClip
from .strategy import Angle, AwarenessLevel, Strategy
from .ugc_script import ClipRole, ScriptClip, UGCScript
from .video_prompt import PromptBlocks, VideoPrompt
from .voice_direction import Pace, VoiceDirection, VoiceProfile

# Tipo de artefacto → clase del contrato
CONTRACT_REGISTRY: dict[ArtifactType, type[ArtifactBase]] = {
    ArtifactType.RESEARCH_BRIEF: ResearchBrief,
    ArtifactType.STRATEGY: Strategy,
    ArtifactType.HOOKS: Hooks,
    ArtifactType.UGC_SCRIPT: UGCScript,
    ArtifactType.STORYBOARD: Storyboard,
    ArtifactType.CHARACTER_BIBLE: CharacterBible,
    ArtifactType.IMAGE_PROMPT: ImagePrompt,
    ArtifactType.VIDEO_PROMPT: VideoPrompt,
    ArtifactType.VOICE_DIRECTION: VoiceDirection,
    ArtifactType.EDIT_PLAN: EditPlan,
    ArtifactType.AUDIT_RESULT: AuditResult,
    ArtifactType.CAMPAIGN_LEARNINGS: CampaignLearnings,
}

# Número de agente → tipo de artefacto que produce
AGENT_OUTPUT: dict[int, ArtifactType] = {
    1: ArtifactType.RESEARCH_BRIEF,
    2: ArtifactType.STRATEGY,
    3: ArtifactType.HOOKS,
    4: ArtifactType.UGC_SCRIPT,
    5: ArtifactType.STORYBOARD,
    6: ArtifactType.CHARACTER_BIBLE,
    7: ArtifactType.IMAGE_PROMPT,
    8: ArtifactType.VIDEO_PROMPT,
    9: ArtifactType.VOICE_DIRECTION,
    10: ArtifactType.EDIT_PLAN,
    11: ArtifactType.AUDIT_RESULT,
    12: ArtifactType.CAMPAIGN_LEARNINGS,
}

# Artefactos que existen una vez por clip, no una vez por proyecto.
PER_CLIP_ARTIFACTS: set[ArtifactType] = {
    ArtifactType.IMAGE_PROMPT,
    ArtifactType.VIDEO_PROMPT,
    ArtifactType.VOICE_DIRECTION,
    ArtifactType.AUDIT_RESULT,
}


def parse_artifact(artifact_type: ArtifactType | str, payload: dict[str, Any]) -> ArtifactBase:
    """Valida un payload crudo contra el contrato que le corresponde."""
    key = ArtifactType(artifact_type)
    return CONTRACT_REGISTRY[key].model_validate(payload)


def contract_for_agent(agent_number: int) -> type[ArtifactBase]:
    return CONTRACT_REGISTRY[AGENT_OUTPUT[agent_number]]


__all__ = [
    "AGENT_OUTPUT", "CONTRACT_REGISTRY", "PER_CLIP_ARTIFACTS", "ERROR_ROUTING",
    "COMMERCIAL_TERMS", "REQUIRED_ANGLES",
    "parse_artifact", "contract_for_agent",
    "AgentError", "ApprovalIssue", "ArtifactBase", "ArtifactStatus",
    "ArtifactType", "Confidence", "Score", "Severity",
    "is_placeholder", "too_similar",
    "ResearchBrief", "Product", "AudienceSignals", "Competitor", "Constraints",
    "Strategy", "Angle", "AwarenessLevel",
    "Hooks", "Hook", "HookScores", "HookType",
    "UGCScript", "ScriptClip", "ClipRole",
    "Storyboard", "StoryboardClip", "ShotType",
    "CharacterBible", "PhysicalTraits",
    "ImagePrompt", "SceneTemplate",
    "VideoPrompt", "PromptBlocks",
    "VoiceDirection", "VoiceProfile", "Pace",
    "EditPlan", "Transition", "SfxCue",
    "AuditResult", "AuditScores", "AuditIssue", "AuditDecision", "IssueCategory",
    "CampaignLearnings", "Metrics", "Insight", "Evidence",
]
