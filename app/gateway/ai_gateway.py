"""
AI Gateway.

La diferencia importante con un wrapper de API: **este gateway no devuelve
texto, devuelve un contrato validado.** El agente pide "dame un `Strategy`" y
recibe un objeto `Strategy` o una excepción. Nunca una cadena que haya que
interpretar.

Eso hace posible el bucle de reparación: si el modelo devuelve un JSON que no
cumple el contrato, el gateway le devuelve los errores exactos de Pydantic y
le pide que corrija — sin que el agente ni el orquestador se enteren.

Orden de operaciones en cada llamada:

    Router elige modelo
        ↓
    Cost Guard estima el PEOR caso y autoriza o corta   ← antes de gastar
        ↓
    Proveedor ejecuta
        ↓
    Se extrae y parsea el JSON
        ↓
    Se valida contra el contrato
        ↓
    ¿inválido? → reparación con los errores exactos (tope duro)
        ↓
    Se registra el gasto REAL y se emite la traza
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import ValidationError

from ..contracts import ArtifactBase
from .cost_guard import CostGuard
from .model_router import ModelRouter, RoutingDecision
from .providers import Provider
from .types import (
    BudgetExceeded,
    GatewayError,
    GenerationRequest,
    RepairFailed,
    RunRecord,
    TaskSpec,
    Usage,
)

T = TypeVar("T", bound=ArtifactBase)

MAX_REPAIR_ATTEMPTS = 2   # tope duro: 1 intento + 2 reparaciones = 3 llamadas

JSON_INSTRUCTION = (
    "Responde ÚNICAMENTE con un objeto JSON válido que cumpla el esquema. "
    "Sin preámbulo, sin explicación, sin ``` de markdown. "
    "Si te falta información para algún campo, NO la inventes: declárala en "
    "el array 'errors' con un código y un mensaje."
)


def schema_block(contract: type[ArtifactBase]) -> str:
    """
    Esquema JSON del contrato, listo para pegar en el prompt.

    Sin esto, el modelo sólo sabe "cumple el esquema" en abstracto y termina
    inventando nombres de campo razonables (`core_benefit` en la raíz en vez
    de `product.core_benefit`, `audience_signals.primary` en vez de
    `age_range`) que no coinciden con los reales. Mostrar los nombres exactos
    —incluidos los anidados y los enums— es lo que hace que el JSON llegue
    bien a la primera, en vez de depender del bucle de reparación para
    corregir cada campo mal nombrado.
    """
    esquema = contract.model_json_schema()
    return json.dumps(esquema, ensure_ascii=False)


def extract_json(text: str) -> dict:
    """
    Saca el objeto JSON de la respuesta.

    Los modelos añaden preámbulos y vallas de markdown incluso cuando se les
    pide que no lo hagan. Esto lo tolera en vez de fallar por un ``` de más.
    """
    cleaned = text.strip()

    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Último recurso: el primer objeto balanceado que aparezca.
    start = cleaned.find("{")
    if start == -1:
        raise GatewayError("La respuesta no contiene ningún objeto JSON.")
    depth, in_str, escaped = 0, False, False
    for i, ch in enumerate(cleaned[start:], start):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start:i + 1])
                except json.JSONDecodeError as exc:
                    raise GatewayError(f"JSON malformado: {exc}") from exc
    raise GatewayError("El objeto JSON de la respuesta está incompleto.")


def format_validation_errors(exc: ValidationError) -> str:
    """Errores de Pydantic en el formato más accionable para el modelo."""
    lines = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(raíz)"
        lines.append(f"- campo '{loc}': {err['msg']}")
    return "\n".join(lines)


class AIGateway:
    """Punto único de contacto entre los agentes y cualquier modelo."""

    def __init__(self, provider: Provider, router: ModelRouter | None = None,
                 cost_guard: CostGuard | None = None):
        self.provider = provider
        self.router = router or ModelRouter()
        self.cost_guard = cost_guard or CostGuard()
        self.runs: list[RunRecord] = []

    # -- API principal -----------------------------------------------

    def generate_artifact(
        self,
        *,
        contract: type[T],
        spec: TaskSpec,
        system: str,
        user: str,
        agent_number: int,
        agent_name: str,
        project_code: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        triggered_by: str = "orchestrator",
    ) -> T:
        """
        Pide al modelo un artefacto y lo devuelve ya validado.

        Lanza BudgetExceeded (cortado antes de gastar) o RepairFailed (el
        modelo no consiguió cumplir el contrato dentro del tope).
        """
        decision: RoutingDecision = self.router.route(spec)
        system_full = (f"{system}\n\n{JSON_INSTRUCTION}\n\n"
                       f"ESQUEMA — usa EXACTAMENTE estos nombres de campo, "
                       f"anidados como se indica:\n{schema_block(contract)}")
        conversation_user = user
        last_errors = ""

        for attempt in range(1, MAX_REPAIR_ATTEMPTS + 2):
            request = GenerationRequest(
                system=system_full, user=conversation_user,
                max_tokens=max_tokens, temperature=temperature,
                model=decision.model,
            )

            # ── el tope se comprueba ANTES de ejecutar ──
            approx_input = (len(system_full) + len(conversation_user)) // 4
            try:
                self.cost_guard.check(
                    model=decision.model, input_tokens=approx_input,
                    max_output_tokens=max_tokens, project_code=project_code,
                )
            except BudgetExceeded as exc:
                self._record(agent_number, agent_name, attempt, "blocked",
                             model=decision.model, error=str(exc),
                             triggered_by=triggered_by)
                raise

            try:
                response = self.provider.generate(request)
            except Exception as exc:
                self._record(agent_number, agent_name, attempt, "failed",
                             model=decision.model, error=str(exc),
                             triggered_by=triggered_by)
                raise GatewayError(f"El proveedor falló: {exc}") from exc

            self.cost_guard.record(response.usage.cost_usd, project_code)

            try:
                payload = extract_json(response.text)
                artifact = contract.model_validate(payload)
            except (GatewayError, ValidationError) as exc:
                last_errors = (format_validation_errors(exc)
                               if isinstance(exc, ValidationError) else str(exc))
                self._record(agent_number, agent_name, attempt, "failed",
                             model=response.model, usage=response.usage,
                             latency_ms=response.latency_ms,
                             error=last_errors, triggered_by=triggered_by)

                if attempt > MAX_REPAIR_ATTEMPTS:
                    raise RepairFailed(
                        f"El modelo no produjo un artefacto válido tras "
                        f"{attempt} intentos.", attempts=attempt,
                        last_errors=last_errors,
                    ) from exc

                # Reparación: se le devuelven los errores exactos, no un
                # "inténtalo otra vez" que no le dice qué corregir.
                conversation_user = (
                    f"{user}\n\n"
                    f"--- CORRECCIÓN REQUERIDA ---\n"
                    f"Tu respuesta anterior no cumplió el contrato:\n"
                    f"{last_errors}\n\n"
                    f"Devuelve el JSON completo corregido."
                )
                continue

            self._record(agent_number, agent_name, attempt, "success",
                         model=response.model, usage=response.usage,
                         latency_ms=response.latency_ms,
                         triggered_by=triggered_by)
            return artifact

        raise RepairFailed("Bucle de reparación agotado.",
                           attempts=MAX_REPAIR_ATTEMPTS + 1,
                           last_errors=last_errors)

    # -- trazas ------------------------------------------------------

    def _record(self, agent_number: int, agent_name: str, attempt: int,
                status: str, *, model: str | None = None,
                usage: Usage | None = None, latency_ms: int = 0,
                error: str | None = None,
                triggered_by: str = "orchestrator") -> None:
        self.runs.append(RunRecord(
            agent_number=agent_number, agent_name=agent_name, attempt=attempt,
            status=status, model_used=model,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            cost_usd=usage.cost_usd if usage else 0.0,
            latency_ms=latency_ms, error_message=error,
            triggered_by=triggered_by,
        ))

    def total_cost(self) -> float:
        return round(sum(r.cost_usd for r in self.runs), 6)

    def failed_runs(self) -> list[RunRecord]:
        return [r for r in self.runs if r.status != "success"]
