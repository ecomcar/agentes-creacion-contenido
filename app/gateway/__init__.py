"""AI Gateway — capa única entre los agentes y cualquier proveedor de modelos."""

from __future__ import annotations

from .ai_gateway import (
    JSON_INSTRUCTION,
    MAX_REPAIR_ATTEMPTS,
    AIGateway,
    extract_json,
    format_validation_errors,
)
from .cost_guard import BudgetLimits, CostGuard
from .model_router import (
    CHEAP_TEXT_MODEL,
    DEFAULT_TEXT_MODEL,
    RULES,
    STRONG_TEXT_MODEL,
    ModelRouter,
    RoutingDecision,
    RoutingRule,
)
from .pricing import PRICES, ModelPrice, estimate_cost, price_for, unverified_models
from .providers import FakeProvider, Provider
from .types import (
    Budget,
    BudgetExceeded,
    GatewayError,
    GenerationRequest,
    GenerationResponse,
    Quality,
    RepairFailed,
    RunRecord,
    TaskKind,
    TaskSpec,
    Usage,
)

__all__ = [
    "AIGateway", "extract_json", "format_validation_errors",
    "JSON_INSTRUCTION", "MAX_REPAIR_ATTEMPTS",
    "CostGuard", "BudgetLimits",
    "ModelRouter", "RoutingRule", "RoutingDecision", "RULES",
    "DEFAULT_TEXT_MODEL", "CHEAP_TEXT_MODEL", "STRONG_TEXT_MODEL",
    "PRICES", "ModelPrice", "estimate_cost", "price_for", "unverified_models",
    "Provider", "FakeProvider",
    "TaskSpec", "TaskKind", "Quality", "Budget",
    "GenerationRequest", "GenerationResponse", "Usage", "RunRecord",
    "GatewayError", "BudgetExceeded", "RepairFailed",
]
