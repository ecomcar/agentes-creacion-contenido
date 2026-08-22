"""
Bucle de corrección.

Es la pieza que convierte el sistema de una cadena en un ciclo. Hasta ahora el
enrutamiento del Auditor estaba especificado y probado, pero nadie lo
ejecutaba.

El principio: **regenerar sólo lo que falla.** El Auditor dice qué categoría
de problema hay, `route_correction` traduce eso a la cadena mínima de agentes,
y este módulo la ejecuta con un tope de ciclos por clip.

Lo que NO hace, deliberadamente:
  - No reinicia el pipeline entero ante un rechazo.
  - No reintenta indefinidamente: al tercer ciclo pasa a humano.
  - No decide la ruta por su cuenta: la deriva de la categoría, para que un
    Auditor mal calibrado no pueda mandar todo a la cadena cara.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..contracts import AuditDecision, AuditResult, IssueCategory
from .retry_policy import RetryPolicy
from .router import CorrectionRoute, route_correction
from .state_machine import BILLABLE_GENERATION, ProjectState, Stage


class CorrectionOutcome(BaseModel):
    """Qué decidió el bucle para un resultado de auditoría."""

    model_config = ConfigDict(extra="forbid")

    clip_id: str
    cycle: int
    decision: str                     # approved | correct | human_review
    route: CorrectionRoute | None = None
    message: str = ""

    @property
    def needs_human(self) -> bool:
        return self.decision == "human_review"

    @property
    def approved(self) -> bool:
        return self.decision == "approved"


class CorrectionLoop:
    def __init__(self, retry_policy: RetryPolicy | None = None):
        self.retry = retry_policy or RetryPolicy()
        self.history: list[CorrectionOutcome] = []

    def decide(self, state: ProjectState, audit: AuditResult) -> CorrectionOutcome:
        """
        Traduce un resultado de auditoría en la siguiente acción.

        No ejecuta los agentes: devuelve la ruta para que el orquestador la
        recorra. Separar decisión de ejecución permite mostrar al humano qué
        va a pasar antes de que pase.
        """
        clip_id = audit.clip_id or "sin_clip"
        key = RetryPolicy.retry_key(Stage.AUDIT, clip_id)

        # 1 ── el veredicto del agente no basta: los umbrales mandan
        if audit.blocking_issues():
            codigos = {i.code for i in audit.blocking_issues()}
            if "approved_below_threshold" in codigos:
                resultado = CorrectionOutcome(
                    clip_id=clip_id, cycle=audit.cycle, decision="human_review",
                    message=("El Auditor aprobó por debajo de los umbrales "
                             f"({audit.realism_score}/{audit.ad_score} frente a "
                             f"{AuditResult.MIN_REALISM}/{AuditResult.MIN_AD}). "
                             "Revisión humana."),
                )
                self.history.append(resultado)
                return resultado

        # 2 ── aprobado de verdad
        if audit.decision is AuditDecision.APPROVED and audit.meets_thresholds:
            state.reset_retry(key)
            resultado = CorrectionOutcome(
                clip_id=clip_id, cycle=audit.cycle, decision="approved",
                message=(f"Clip aprobado con realismo {audit.realism_score} y "
                         f"anuncio {audit.ad_score}."),
            )
            self.history.append(resultado)
            return resultado

        # 3 ── el Auditor pidió revisión humana explícitamente
        if audit.decision is AuditDecision.HUMAN_REVIEW or audit.issue is None:
            resultado = CorrectionOutcome(
                clip_id=clip_id, cycle=audit.cycle, decision="human_review",
                message="El Auditor derivó el clip a revisión humana.",
            )
            self.history.append(resultado)
            return resultado

        # 4 ── tope de ciclos: no seguimos quemando créditos
        ciclos = state.retry_counts.get(key, 0)
        decision_reintento = self.retry.check(Stage.AUDIT, ciclos)
        if not decision_reintento.allowed:
            resultado = CorrectionOutcome(
                clip_id=clip_id, cycle=audit.cycle, decision="human_review",
                message=(f"{decision_reintento.reason} El último problema fue "
                         f"'{audit.issue.category.value}'."),
            )
            self.history.append(resultado)
            return resultado

        # 5 ── corregir por la cadena mínima
        state.bump_retry(key)
        ruta = route_correction(audit.issue.category, clip_id=clip_id,
                                description=audit.issue.description)
        resultado = CorrectionOutcome(
            clip_id=clip_id, cycle=audit.cycle, decision="correct", route=ruta,
            message=(f"{audit.issue.category.value}: {ruta.as_path()} "
                     f"({ruta.regenerations} etapa"
                     f"{'s' if ruta.regenerations != 1 else ''}"
                     f"{', con créditos' if ruta.touches_billable else ''})."),
        )
        self.history.append(resultado)
        return resultado

    # -- análisis del desperdicio -------------------------------------

    def wasted_regenerations(self) -> int:
        """Cuántas reejecuciones de etapa han causado las correcciones."""
        return sum(o.route.regenerations for o in self.history
                   if o.route is not None)

    def billable_corrections(self) -> int:
        """De ésas, cuántas consumieron créditos de generación."""
        return sum(1 for o in self.history
                   if o.route is not None and o.route.touches_billable)

    def by_category(self) -> dict[IssueCategory, int]:
        """
        Qué problemas causan más correcciones.

        Es el dato que dice qué prompt hay que mejorar: si el 60% de las
        correcciones son de identidad, el trabajo está en el Agente 6, no en
        generar más variantes.
        """
        conteo: dict[IssueCategory, int] = {}
        for o in self.history:
            if o.route is not None:
                conteo[o.route.category] = conteo.get(o.route.category, 0) + 1
        return dict(sorted(conteo.items(), key=lambda kv: kv[1], reverse=True))


def stages_touching_credits(route: CorrectionRoute) -> list[Stage]:
    """Qué etapas de una corrección consumen créditos además de tokens."""
    return [s for s in route.stages if s in BILLABLE_GENERATION]
