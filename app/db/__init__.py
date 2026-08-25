"""Persistencia."""

from __future__ import annotations

from .models import (
    AgentRun,
    Brand,
    Approval,
    Artifact,
    AssetRow,
    AvatarLibraryRow,
    AvatarReference,
    Base,
    CampaignMetric,
    Clip,
    ClipAudit,
    CreativeMemoryRow,
    JobRow,
    Project,
    PromptLibraryRow,
    PromptVersion,
)
from .repositories import (
    ArtifactRepository,
    BrandRepository,
    AssetRepository,
    ClipAuditRepository,
    ClipRepository,
    JobRepository,
    ProjectRepository,
    RunRepository,
)
from .session import (
    create_all,
    drop_all,
    engine_for,
    session_factory,
    session_scope,
)

__all__ = [
    "Base", "Project", "Artifact", "Clip", "AssetRow", "AgentRun", "JobRow",
    "Brand",
    "Approval", "ClipAudit", "AvatarLibraryRow", "AvatarReference",
    "PromptLibraryRow", "PromptVersion", "CampaignMetric", "CreativeMemoryRow",
    "engine_for", "session_factory", "create_all", "drop_all", "session_scope",
    "ArtifactRepository", "ProjectRepository", "RunRepository", "JobRepository",
    "BrandRepository",
    "AssetRepository", "ClipRepository", "ClipAuditRepository",
]
