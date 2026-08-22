"""Capa de control: máquina de estados, enrutamiento de correcciones y topes."""

from __future__ import annotations

from .correction_loop import (
    CorrectionLoop,
    CorrectionOutcome,
    stages_touching_credits,
)
from .orchestrator import NotImplementedStage, Orchestrator, StageOutcome
from .retry_policy import RetryDecision, RetryLimits, RetryPolicy
from .router import (
    AGENT_STAGE,
    CORRECTION_CHAINS,
    CorrectionRoute,
    cheapest_first,
    route_correction,
)
from .state_machine import (
    BILLABLE_GENERATION,
    FORWARD,
    HUMAN_GATES,
    IMPLEMENTED_THROUGH,
    OUT_OF_PIPELINE_AGENTS,
    STAGE_AGENT,
    InvalidTransition,
    ProjectState,
    Stage,
    StageStatus,
    StateMachine,
)

__all__ = [
    "Orchestrator", "StageOutcome", "NotImplementedStage",
    "StateMachine", "ProjectState", "Stage", "StageStatus",
    "InvalidTransition", "FORWARD", "STAGE_AGENT", "HUMAN_GATES",
    "BILLABLE_GENERATION", "IMPLEMENTED_THROUGH", "OUT_OF_PIPELINE_AGENTS",
    "RetryPolicy", "RetryLimits", "RetryDecision",
    "route_correction", "CorrectionRoute", "CORRECTION_CHAINS",
    "AGENT_STAGE", "cheapest_first",
    "CorrectionLoop", "CorrectionOutcome", "stages_touching_credits",
]
