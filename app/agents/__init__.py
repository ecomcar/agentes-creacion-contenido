"""Agentes del sistema. Fase 3 cubre los cuatro primeros."""

from __future__ import annotations

from .base import Agent, PromptNotFound, available_versions, load_prompt
from .final_agents import (
    AnalystAgent,
    AuditorAgent,
    CampaignMetricsInput,
    EditorAgent,
    VoiceDirectorAgent,
)
from .video_agents import VideoDirectorAgent
from .visual_agents import (
    IdentityArchitectAgent,
    ImagePromptAgent,
    VisualDirectorAgent,
)
from .text_agents import (
    HooksAgent,
    ProductInput,
    ResearcherAgent,
    ScriptwriterAgent,
    StrategistAgent,
    StrategistWithMemoryAgent,
)

# Número de agente → clase. Los 8 restantes se registran en fases 4-6.
AGENT_REGISTRY: dict[int, type[Agent]] = {
    1: ResearcherAgent,
    2: StrategistAgent,
    3: HooksAgent,
    4: ScriptwriterAgent,
    5: VisualDirectorAgent,
    6: IdentityArchitectAgent,
    7: ImagePromptAgent,
    8: VideoDirectorAgent,
    9: VoiceDirectorAgent,
    10: EditorAgent,
    11: AuditorAgent,
    12: AnalystAgent,
}

__all__ = [
    "Agent", "AGENT_REGISTRY", "load_prompt", "available_versions",
    "PromptNotFound", "ProductInput",
    "ResearcherAgent", "StrategistAgent", "StrategistWithMemoryAgent",
    "HooksAgent", "ScriptwriterAgent",
    "VisualDirectorAgent", "IdentityArchitectAgent", "ImagePromptAgent",
    "VideoDirectorAgent", "VoiceDirectorAgent", "EditorAgent",
    "AuditorAgent", "AnalystAgent", "CampaignMetricsInput",
]
