"""
Política de reintentos.

**Esto no es el bucle de reparación del gateway.** Son dos cosas distintas y
conviene no confundirlas:

- *Reparación* (gateway): el modelo devolvió un JSON que no cumple el
  contrato. Se le devuelven los errores y corrige. Tope: 2. Nadie más se
  entera.
- *Reintento* (aquí): el artefacto es válido pero **no supera los criterios
  de calidad**, o el humano lo rechazó, o el Auditor lo devolvió. Se
  reejecuta el agente con feedback. Tope por etapa.

Cuando se agota el tope, el proyecto no muere: pasa a `BLOCKED` y espera a un
humano. Un sistema que reintenta indefinidamente es el que vacía la cuenta.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field

from .state_machine import Stage


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


class RetryLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: int = Field(default_factory=lambda: _env_int("MAX_RETRY_STRATEGY", 2))
    hooks: int = Field(default_factory=lambda: _env_int("MAX_RETRY_HOOKS", 2))
    script: int = Field(default_factory=lambda: _env_int("MAX_RETRY_SCRIPT", 2))
    storyboard: int = Field(default_factory=lambda: _env_int("MAX_RETRY_STORYBOARD", 2))
    image: int = Field(default_factory=lambda: _env_int("MAX_RETRY_IMAGE", 3))
    video: int = Field(default_factory=lambda: _env_int("MAX_RETRY_VIDEO", 3))
    audit_cycles: int = Field(default_factory=lambda: _env_int("MAX_AUDIT_CYCLES", 3))
    default: int = 2


class RetryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    attempt: int
    limit: int
    reason: str

    @property
    def exhausted(self) -> bool:
        return not self.allowed


class RetryPolicy:
    def __init__(self, limits: RetryLimits | None = None):
        self.limits = limits or RetryLimits()

    def limit_for(self, stage: Stage) -> int:
        return {
            Stage.STRATEGY: self.limits.strategy,
            Stage.HOOKS: self.limits.hooks,
            Stage.SCRIPT: self.limits.script,
            Stage.STORYBOARD: self.limits.storyboard,
            Stage.IMAGE: self.limits.image,
            Stage.VIDEO: self.limits.video,
            Stage.AUDIT: self.limits.audit_cycles,
        }.get(stage, self.limits.default)

    def check(self, stage: Stage, attempts_so_far: int) -> RetryDecision:
        limit = self.limit_for(stage)
        if attempts_so_far >= limit:
            return RetryDecision(
                allowed=False, attempt=attempts_so_far, limit=limit,
                reason=(f"La etapa '{stage.value}' agotó sus {limit} intentos. "
                        f"Requiere intervención humana antes de seguir "
                        f"gastando."),
            )
        return RetryDecision(
            allowed=True, attempt=attempts_so_far + 1, limit=limit,
            reason=f"Intento {attempts_so_far + 1} de {limit}.",
        )

    @staticmethod
    def retry_key(stage: Stage, clip_id: str | None = None) -> str:
        """
        Los topes de imagen y video se cuentan **por clip**, no por proyecto.

        Si se contaran por proyecto, un anuncio de seis clips agotaría el tope
        en el segundo clip problemático y bloquearía los cuatro que aún no se
        han intentado.
        """
        return f"{stage.value}:{clip_id}" if clip_id else stage.value
