"""
Model Router.

Traduce lo que el agente declara (tarea, calidad, presupuesto) a un modelo
concreto. Es la única pieza que conoce nombres de modelos.

Las reglas son datos, no `if`s desperdigados: se pueden ver, testear y
cambiar en un sitio. Cuando salga un modelo mejor, se edita la tabla.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict

from .types import Budget, Quality, TaskKind, TaskSpec

DEFAULT_TEXT_MODEL = "claude-sonnet-5"
CHEAP_TEXT_MODEL = "claude-haiku-4-5"
STRONG_TEXT_MODEL = "claude-opus-5"


class RoutingRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task: TaskKind
    quality: Quality | None = None      # None = cualquiera
    budget: Budget | None = None
    model: str
    reason: str

    def matches(self, spec: TaskSpec) -> bool:
        if self.task is not spec.task:
            return False
        if self.quality is not None and self.quality is not spec.quality:
            return False
        if self.budget is not None and self.budget is not spec.budget:
            return False
        return True


# Orden importante: gana la primera regla que encaje, de más específica a
# más general.
RULES: list[RoutingRule] = [
    # Extracción y relleno estructurado: poco juicio, mucho volumen.
    RoutingRule(task=TaskKind.EXTRACTION, model=CHEAP_TEXT_MODEL,
                reason="Extracción sobre texto ya dado; no requiere juicio."),
    RoutingRule(task=TaskKind.STRUCTURED, quality=Quality.DRAFT,
                model=CHEAP_TEXT_MODEL,
                reason="Borrador estructurado; se validará contra el contrato."),

    # Razonamiento: es donde se decide la calidad del anuncio.
    RoutingRule(task=TaskKind.REASONING, quality=Quality.HIGH,
                model=STRONG_TEXT_MODEL,
                reason="Estrategia y auditoría de alta exigencia."),
    RoutingRule(task=TaskKind.REASONING, budget=Budget.LOW,
                model=CHEAP_TEXT_MODEL,
                reason="Presupuesto bajo declarado explícitamente."),
    RoutingRule(task=TaskKind.REASONING, model=DEFAULT_TEXT_MODEL,
                reason="Razonamiento estándar."),

    # Creativo: el modelo barato empobrece hooks y diálogo de forma notoria.
    RoutingRule(task=TaskKind.CREATIVE, model=DEFAULT_TEXT_MODEL,
                reason="Hooks y guion; el modelo barato aplana la escritura."),

    RoutingRule(task=TaskKind.STRUCTURED, model=DEFAULT_TEXT_MODEL,
                reason="Relleno estructurado estándar."),
]


class RoutingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    reason: str
    rule_index: int | None = None


class ModelRouter:
    def __init__(self, rules: list[RoutingRule] | None = None):
        self.rules = rules if rules is not None else RULES

    def route(self, spec: TaskSpec) -> RoutingDecision:
        # Un override de entorno gana sobre todo: sirve para fijar un modelo
        # durante pruebas o para reaccionar rápido a un incidente.
        forced = os.getenv("FORCE_MODEL")
        if forced:
            return RoutingDecision(model=forced,
                                   reason="Forzado por FORCE_MODEL en .env.")

        for i, rule in enumerate(self.rules):
            if rule.matches(spec):
                return RoutingDecision(model=rule.model, reason=rule.reason,
                                       rule_index=i)

        if spec.task in (TaskKind.IMAGE_GENERATION, TaskKind.VIDEO_GENERATION,
                         TaskKind.VOICE):
            raise NotImplementedError(
                f"No hay proveedor registrado para '{spec.task.value}'. "
                f"Se conecta en la fase 4-5, no en esta."
            )

        return RoutingDecision(model=DEFAULT_TEXT_MODEL,
                               reason="Sin regla específica; modelo por defecto.")
