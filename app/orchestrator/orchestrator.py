"""
Orquestador.

No crea contenido. Decide qué agente trabaja, con qué información, y qué pasa
con lo que devuelve.

El orden de comprobaciones en cada etapa es deliberado:

    1. ¿Está implementada la etapa?          → si no, se dice claramente
    2. ¿Queda presupuesto de reintentos?     → si no, BLOCKED
    3. Ejecutar el agente (gateway valida el contrato)
    4. ¿Supera los criterios de aprobación?  → si no, reintento con feedback
    5. ¿Requiere aprobación humana?          → si sí, PENDING_HUMAN_APPROVAL
    6. Avanzar

El paso 4 es el que distingue este orquestador de un encadenador de llamadas:
un artefacto puede ser válido según el contrato y aun así no ser aprobable.
Los criterios deterministas mandan sobre lo que diga el agente de sí mismo.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..contracts import ApprovalIssue, ArtifactBase
from ..gateway import AIGateway, BudgetExceeded, GatewayError, RepairFailed
from .retry_policy import RetryPolicy
from .state_machine import (
    IMPLEMENTED_THROUGH,
    ProjectState,
    Stage,
    StageStatus,
    StateMachine,
)


class StageOutcome(BaseModel):
    """Resultado de ejecutar una etapa. Lo que el dashboard necesita mostrar."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    stage: Stage
    status: StageStatus
    artifact: ArtifactBase | None = None
    issues: list[ApprovalIssue] = []
    message: str = ""
    cost_usd: float = 0.0
    attempt: int = 1

    @property
    def ok(self) -> bool:
        return self.status in (StageStatus.APPROVED,
                               StageStatus.PENDING_HUMAN_APPROVAL)


class NotImplementedStage(Exception):
    pass


class Orchestrator:
    def __init__(self, gateway: AIGateway, agents: dict[int, object],
                 retry_policy: RetryPolicy | None = None):
        self.gateway = gateway
        self.agents = agents
        self.retry = retry_policy or RetryPolicy()

    # -- ejecución de una etapa --------------------------------------

    def run_stage(self, state: ProjectState, stage: Stage, payload, *,
                  feedback: str | None = None,
                  clip_id: str | None = None,
                  triggered_by: str = "orchestrator") -> StageOutcome:

        if not StateMachine.is_implemented(stage):
            raise NotImplementedStage(
                f"La etapa '{stage.value}' no está implementada todavía. "
                f"La fase actual cubre hasta "
                f"'{IMPLEMENTED_THROUGH.value}'."
            )

        agent_number = StateMachine.agent_for(stage)
        agent = self.agents.get(agent_number)
        if agent is None:
            raise NotImplementedStage(
                f"No hay agente registrado con el número {agent_number} "
                f"para la etapa '{stage.value}'."
            )

        key = RetryPolicy.retry_key(stage, clip_id)
        decision = self.retry.check(stage, state.retry_counts.get(key, 0))
        if not decision.allowed:
            state.stage_status = StageStatus.BLOCKED
            return StageOutcome(stage=stage, status=StageStatus.BLOCKED,
                                message=decision.reason,
                                attempt=decision.attempt)

        cost_before = self.gateway.total_cost()
        state.stage_status = StageStatus.RUNNING

        try:
            artifact = agent.run(self.gateway, payload,
                                 project_code=state.project_code,
                                 feedback=feedback, triggered_by=triggered_by)
        except BudgetExceeded as exc:
            state.stage_status = StageStatus.BLOCKED
            return StageOutcome(stage=stage, status=StageStatus.BLOCKED,
                                message=str(exc), attempt=decision.attempt)
        except (RepairFailed, GatewayError) as exc:
            state.bump_retry(key)
            state.stage_status = StageStatus.FAILED
            cost = round(self.gateway.total_cost() - cost_before, 6)
            state.total_cost_usd = round(state.total_cost_usd + cost, 6)
            mensaje = str(exc)
            if isinstance(exc, RepairFailed) and exc.last_errors:
                # Sin esto, "no produjo un artefacto válido" no dice CUÁL fue
                # el problema — y eso es justo lo que hace falta para saber
                # si es un fallo de conexión, de formato, o del contrato.
                mensaje = f"{mensaje}\n\nÚltimo error de validación:\n{exc.last_errors}"
            return StageOutcome(stage=stage, status=StageStatus.FAILED,
                                message=mensaje, cost_usd=cost,
                                attempt=decision.attempt)

        cost = round(self.gateway.total_cost() - cost_before, 6)
        state.total_cost_usd = round(state.total_cost_usd + cost, 6)

        # -- criterios de aprobación: mandan sobre el agente --
        blocking = artifact.blocking_issues()
        if blocking:
            state.bump_retry(key)
            return StageOutcome(
                stage=stage, status=StageStatus.FAILED, artifact=artifact,
                issues=artifact.approval_check(), cost_usd=cost,
                attempt=decision.attempt,
                message=("El artefacto es válido pero no supera los criterios "
                         "de aprobación."),
            )

        state.reset_retry(key)

        if StateMachine.requires_human(stage, state.auto_mode):
            state.stage_status = StageStatus.PENDING_HUMAN_APPROVAL
            return StageOutcome(
                stage=stage, status=StageStatus.PENDING_HUMAN_APPROVAL,
                artifact=artifact, issues=artifact.approval_check(),
                cost_usd=cost, attempt=decision.attempt,
                message="Esperando decisión humana.",
            )

        state.stage_status = StageStatus.APPROVED
        return StageOutcome(stage=stage, status=StageStatus.APPROVED,
                            artifact=artifact, issues=artifact.approval_check(),
                            cost_usd=cost, attempt=decision.attempt,
                            message="Aprobado automáticamente.")

    # -- avance --------------------------------------------------------

    def approve_and_advance(self, state: ProjectState) -> Stage | None:
        """Registra la aprobación humana y mueve el proyecto a la sucesora."""
        nxt = StateMachine.next_stage(state.current_stage)
        if nxt is None:
            state.stage_status = StageStatus.APPROVED
            return None
        state.current_stage = StateMachine.advance(state.current_stage, nxt)
        state.stage_status = StageStatus.PENDING
        return nxt

    @staticmethod
    def feedback_from(outcome: StageOutcome) -> str:
        """Convierte los incumplimientos en instrucciones para el reintento."""
        lines = [f"- {i.code}: {i.message}" for i in outcome.issues
                 if i.severity.value == "blocking"]
        return "\n".join(lines)
