"""
Repositorios de trazas y trabajos.

`RunRepository` persiste lo que el gateway ya produce en memoria: las trazas
que alimentan el panel del agente del dashboard.

`JobRepository` es la parte de la cola que sobrevive a un reinicio. La
idempotencia deja de depender de un diccionario en memoria y pasa a estar
garantizada por una restricción única de la base: dos procesos concurrentes no
pueden crear el mismo trabajo.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...gateway.types import RunRecord
from ..models import AgentRun, JobRow


class RunRepository:
    def __init__(self, session: Session):
        self.session = session

    def record(self, project_id: str, run: RunRecord,
               clip_id: str | None = None, **refs) -> AgentRun:
        row = AgentRun(
            project_id=project_id, clip_id=clip_id,
            agent_number=run.agent_number, agent_name=run.agent_name,
            attempt=run.attempt, status=run.status, model_used=run.model_used,
            input_tokens=run.input_tokens, output_tokens=run.output_tokens,
            cost_usd=run.cost_usd, latency_ms=run.latency_ms,
            error_message=run.error_message, triggered_by=run.triggered_by,
            started_at=run.started_at,
            finished_at=datetime.now(timezone.utc), **refs)
        self.session.add(row)
        self.session.flush()
        return row

    def record_all(self, project_id: str, runs: list[RunRecord]) -> int:
        for r in runs:
            self.record(project_id, r)
        return len(runs)

    def for_project(self, project_id: str) -> list[AgentRun]:
        return list(self.session.scalars(
            select(AgentRun).where(AgentRun.project_id == project_id)
            .order_by(AgentRun.started_at.desc())))

    def cost_by_agent(self, project_id: str) -> dict[int, float]:
        """De dónde sale el gasto. El dato que dice qué etapa optimizar."""
        rows = self.session.execute(
            select(AgentRun.agent_number, func.sum(AgentRun.cost_usd))
            .where(AgentRun.project_id == project_id)
            .group_by(AgentRun.agent_number)).all()
        return {n: round(c or 0.0, 6) for n, c in rows}

    def wasted_cost(self, project_id: str) -> float:
        """
        Gasto en intentos que no produjeron nada utilizable.

        Separarlo del gasto total es lo que permite saber si el problema es
        que el sistema es caro o que falla mucho.
        """
        total = self.session.scalar(
            select(func.sum(AgentRun.cost_usd))
            .where(AgentRun.project_id == project_id,
                   AgentRun.status != "success"))
        return round(total or 0.0, 6)

    def correction_cost(self, project_id: str) -> float:
        """Gasto causado por correcciones del Auditor."""
        total = self.session.scalar(
            select(func.sum(AgentRun.cost_usd))
            .where(AgentRun.project_id == project_id,
                   AgentRun.triggered_by == "audit_route"))
        return round(total or 0.0, 6)


class JobRepository:
    def __init__(self, session: Session):
        self.session = session

    def by_idempotency_key(self, key: str) -> JobRow | None:
        return self.session.scalars(
            select(JobRow).where(JobRow.idempotency_key == key)).first()

    def create(self, *, project_id: str, clip_id: str | None,
               idempotency_key: str, provider: str,
               duration_sec: float = 0.0, kind: str = "video") -> JobRow:
        row = JobRow(project_id=project_id, clip_id=clip_id,
                     idempotency_key=idempotency_key, provider=provider,
                     duration_sec=duration_sec, kind=kind)
        self.session.add(row)
        self.session.flush()
        return row

    def mark_submitted(self, job_id: str, provider_job_id: str) -> JobRow:
        """
        Guarda el id del proveedor lo antes posible.

        Si el proceso muere después de esta línea, el trabajo sigue siendo
        recuperable en vez de convertirse en gasto perdido.
        """
        row = self.session.get(JobRow, job_id)
        if row is None:
            raise KeyError(f"No existe el trabajo {job_id}.")
        row.provider_job_id = provider_job_id
        row.status = "submitted"
        self.session.flush()
        return row

    def orphans(self) -> list[JobRow]:
        """Trabajos en vuelo al arrancar: el proveedor puede estar cobrándolos."""
        return list(self.session.scalars(
            select(JobRow).where(JobRow.status.in_(("submitted", "running")),
                                 JobRow.provider_job_id.is_not(None))))

    def finish(self, job_id: str, *, status: str, result_url: str | None = None,
               cost_usd: float = 0.0, error: str | None = None) -> JobRow:
        row = self.session.get(JobRow, job_id)
        if row is None:
            raise KeyError(f"No existe el trabajo {job_id}.")
        row.status = status
        row.result_url = result_url
        row.cost_usd = cost_usd
        row.error_message = error
        row.finished_at = datetime.now(timezone.utc)
        self.session.flush()
        return row
