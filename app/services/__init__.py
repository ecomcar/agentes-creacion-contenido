"""Servicios: ejecutan lo que los agentes especifican."""

from __future__ import annotations

from .image_generation import (
    Asset,
    AvatarLibrary,
    GenerationBlocked,
    ImageGenerationService,
)
from .job_queue import (
    MAX_POLLS_PER_JOB,
    Job,
    JobQueue,
    JobStatus,
    idempotency_key,
)
from .diagnostics import (
    Finding,
    StageDiagnostics,
    diagnose_brief,
    diagnose_hooks,
    diagnose_script,
    diagnose_strategy,
)
from .creative_memory import DEFAULT_TTL_DAYS, CreativeMemory, MemoryEntry
from .video_generation import ClipProgress, VideoBlocked, VideoGenerationService
from .voice_library import (
    TODAS_LAS_VOCES,
    VOCES_FEMENINAS,
    VOCES_MASCULINAS,
    CuratedVoice,
    VoiceGender,
    find_duplicate_ids,
    get_by_id,
    get_by_name,
    list_by_gender,
    usable_voices,
)

__all__ = [
    "Asset", "AvatarLibrary", "GenerationBlocked", "ImageGenerationService",
    "Job", "JobQueue", "JobStatus", "idempotency_key", "MAX_POLLS_PER_JOB",
    "VideoGenerationService", "VideoBlocked", "ClipProgress",
    "TODAS_LAS_VOCES", "VOCES_FEMENINAS", "VOCES_MASCULINAS", "CuratedVoice",
    "VoiceGender", "find_duplicate_ids", "get_by_id", "get_by_name",
    "list_by_gender", "usable_voices",
    "CreativeMemory", "MemoryEntry", "DEFAULT_TTL_DAYS",
    "Finding", "StageDiagnostics", "diagnose_brief", "diagnose_strategy",
    "diagnose_hooks", "diagnose_script",
]
