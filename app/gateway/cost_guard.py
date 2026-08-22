"""
Cost Guard.

La lección más cara del proyecto anterior: **un tope que se verifica después
de gastar no es un tope.** Aquí todo se comprueba ANTES de ejecutar la
llamada, estimando el coste máximo posible (input real + output al tope de
`max_tokens`, asumiendo el peor caso).

Tres niveles de tope, del más ajustado al más amplio:
  1. por llamada
  2. por proyecto (anuncio)
  3. por ejecución/sesión
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field

from .pricing import price_for
from .types import BudgetExceeded


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


class BudgetLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_cost_per_call_usd: float = Field(
        default_factory=lambda: _env_float("MAX_COST_PER_CALL_USD", 0.50))
    max_cost_per_project_usd: float = Field(
        default_factory=lambda: _env_float("MAX_COST_PER_PROJECT_USD", 5.00))
    max_cost_per_session_usd: float = Field(
        default_factory=lambda: _env_float("MAX_COST_PER_SESSION_USD", 25.00))


class CostGuard:
    def __init__(self, limits: BudgetLimits | None = None):
        self.limits = limits or BudgetLimits()
        self.session_spent: float = 0.0
        self.project_spent: dict[str, float] = {}

    # -- antes de llamar ---------------------------------------------

    def estimate_worst_case(self, model: str, input_tokens: int,
                            max_output_tokens: int) -> float:
        """Peor caso: el modelo agota `max_tokens` de salida."""
        return price_for(model).cost(input_tokens, max_output_tokens)

    def check(self, *, model: str, input_tokens: int, max_output_tokens: int,
              project_code: str | None = None) -> float:
        """
        Lanza BudgetExceeded si la llamada podría pasarse de algún tope.
        Devuelve el coste estimado del peor caso si autoriza.
        """
        worst = self.estimate_worst_case(model, input_tokens, max_output_tokens)

        if worst > self.limits.max_cost_per_call_usd:
            raise BudgetExceeded(
                f"La llamada podría costar hasta ${worst:.4f}, por encima del "
                f"tope por llamada de ${self.limits.max_cost_per_call_usd:.4f}. "
                f"Reducir max_tokens o usar un modelo más barato."
            )

        if self.session_spent + worst > self.limits.max_cost_per_session_usd:
            raise BudgetExceeded(
                f"La sesión lleva ${self.session_spent:.4f} y esta llamada "
                f"podría añadir ${worst:.4f}, superando el tope de sesión de "
                f"${self.limits.max_cost_per_session_usd:.4f}."
            )

        if project_code is not None:
            spent = self.project_spent.get(project_code, 0.0)
            if spent + worst > self.limits.max_cost_per_project_usd:
                raise BudgetExceeded(
                    f"El proyecto {project_code} lleva ${spent:.4f} y esta "
                    f"llamada podría añadir ${worst:.4f}, superando el tope "
                    f"por anuncio de ${self.limits.max_cost_per_project_usd:.4f}."
                )

        return worst

    # -- después de llamar -------------------------------------------

    def record(self, cost_usd: float, project_code: str | None = None) -> None:
        """Registra el gasto REAL, que suele ser menor que el peor caso."""
        self.session_spent = round(self.session_spent + cost_usd, 6)
        if project_code is not None:
            self.project_spent[project_code] = round(
                self.project_spent.get(project_code, 0.0) + cost_usd, 6)

    def report(self) -> dict[str, float]:
        return {
            "session_spent_usd": self.session_spent,
            "session_limit_usd": self.limits.max_cost_per_session_usd,
            **{f"project_{k}_usd": v for k, v in self.project_spent.items()},
        }
