"""
Máquina de estados del pipeline.

Las transiciones son datos, no `if`s repartidos por el código. Se pueden ver
completas, testear y cambiar en un sitio.

Regla de fondo: **no se puede saltar de una etapa a otra que no sea su
sucesora legítima.** Sin esto, un bug en el enrutamiento de errores puede
mandar el proyecto a "video" sin haber pasado por "storyboard", y el fallo
aparece tres pasos después disfrazado de otra cosa.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class Stage(str, Enum):
    RESEARCH = "research"
    STRATEGY = "strategy"
    HOOKS = "hooks"
    SCRIPT = "script"
    STORYBOARD = "storyboard"
    IDENTITY = "identity"
    IMAGE = "image"
    VIDEO = "video"
    VOICE = "voice"
    EDIT = "edit"
    AUDIT = "audit"
    PUBLISHED = "published"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PENDING_HUMAN_APPROVAL = "pending_human_approval"
    APPROVED = "approved"
    FAILED = "failed"
    BLOCKED = "blocked"          # tope agotado: requiere intervención humana


# Avance normal del pipeline.
FORWARD: dict[Stage, Stage | None] = {
    Stage.RESEARCH: Stage.STRATEGY,
    Stage.STRATEGY: Stage.HOOKS,
    Stage.HOOKS: Stage.SCRIPT,
    Stage.SCRIPT: Stage.STORYBOARD,
    Stage.STORYBOARD: Stage.IDENTITY,
    Stage.IDENTITY: Stage.IMAGE,
    Stage.IMAGE: Stage.VIDEO,
    Stage.VIDEO: Stage.VOICE,
    Stage.VOICE: Stage.EDIT,
    Stage.EDIT: Stage.AUDIT,
    Stage.AUDIT: Stage.PUBLISHED,
    Stage.PUBLISHED: None,
}

# Etapa → agente que la ejecuta.
STAGE_AGENT: dict[Stage, int] = {
    Stage.RESEARCH: 1, Stage.STRATEGY: 2, Stage.HOOKS: 3, Stage.SCRIPT: 4,
    Stage.STORYBOARD: 5, Stage.IDENTITY: 6, Stage.IMAGE: 7, Stage.VIDEO: 8,
    Stage.VOICE: 9, Stage.EDIT: 10, Stage.AUDIT: 11,
}

# Etapas que se detienen a esperar al humano mientras `auto_mode` esté en
# false. Coinciden con los puntos donde una decisión equivocada se paga cara
# más adelante: el ángulo, el hook, el guion, el storyboard y la selección de
# imagen y video.
HUMAN_GATES: frozenset[Stage] = frozenset({
    Stage.STRATEGY, Stage.HOOKS, Stage.SCRIPT, Stage.STORYBOARD,
    Stage.IMAGE, Stage.VIDEO,
})

# El Analista no tiene etapa: no lo dispara el pipeline sino la llegada de
# métricas, días o semanas después de publicar. Modelarlo como una etapa más
# obligaría a que un proyecto quedara "en curso" indefinidamente esperando
# datos de campaña que quizá no lleguen nunca.
#
# Es lo que hace que el sistema sea un ciclo y no una cadena: el 12 entra por
# fuera y alimenta a los agentes 1-3 de la campaña SIGUIENTE.
OUT_OF_PIPELINE_AGENTS: frozenset[int] = frozenset({12})

# Etapas que consumen créditos de generación además de tokens.
BILLABLE_GENERATION: frozenset[Stage] = frozenset({
    Stage.IMAGE, Stage.VIDEO, Stage.VOICE,
})

# Hasta dónde llega la implementación actual (fase 6): los 12 agentes.
IMPLEMENTED_THROUGH: Stage = Stage.AUDIT


class InvalidTransition(Exception):
    pass


class StateMachine:
    @staticmethod
    def next_stage(current: Stage) -> Stage | None:
        return FORWARD[current]

    @staticmethod
    def requires_human(stage: Stage, auto_mode: bool = False) -> bool:
        return stage in HUMAN_GATES and not auto_mode

    @staticmethod
    def agent_for(stage: Stage) -> int:
        if stage is Stage.PUBLISHED:
            raise InvalidTransition("La etapa 'published' no ejecuta agentes.")
        return STAGE_AGENT[stage]

    @staticmethod
    def is_implemented(stage: Stage) -> bool:
        order = list(FORWARD)
        return order.index(stage) <= order.index(IMPLEMENTED_THROUGH)

    @classmethod
    def advance(cls, current: Stage, target: Stage) -> Stage:
        """
        Valida un avance. Sólo se permite la sucesora legítima; cualquier
        otro salto es un error, no una optimización.
        """
        expected = FORWARD[current]
        if expected is None:
            raise InvalidTransition(
                f"'{current.value}' es terminal; no hay etapa siguiente."
            )
        if target is not expected:
            raise InvalidTransition(
                f"No se puede pasar de '{current.value}' a '{target.value}'. "
                f"La sucesora es '{expected.value}'."
            )
        return target

    @staticmethod
    def stages_before(stage: Stage) -> list[Stage]:
        order = list(FORWARD)
        return order[:order.index(stage)]


class ProjectState(BaseModel):
    """Estado vivo de un proyecto, con la forma de la tabla `projects`."""

    model_config = ConfigDict(extra="forbid")

    project_code: str
    current_stage: Stage = Stage.RESEARCH
    stage_status: StageStatus = StageStatus.PENDING
    auto_mode: bool = False
    retry_counts: dict[str, int] = {}
    total_cost_usd: float = 0.0

    def bump_retry(self, key: str) -> int:
        self.retry_counts[key] = self.retry_counts.get(key, 0) + 1
        return self.retry_counts[key]

    def reset_retry(self, key: str) -> None:
        self.retry_counts.pop(key, None)
