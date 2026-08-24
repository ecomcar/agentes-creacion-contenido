"""
Repositorio de auditorías.

`clip_audits` es la tabla estructurada y consultable (scores, ruta de
corrección) — distinta de `artifacts`, donde el `AuditResult` también se
guarda como artefacto genérico versionado. Se escriben ambas: la genérica
para trazabilidad completa del pipeline, ésta para consultas rápidas
("¿cuántos clips fallaron por identidad este mes?").
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...contracts import AuditResult
from ..models import ClipAudit


class ClipAuditRepository:
    def __init__(self, session: Session):
        self.session = session

    def record(self, clip_id: str, audit: AuditResult) -> ClipAudit:
        row = ClipAudit(
            clip_id=clip_id, cycle=audit.cycle,
            scores=audit.scores.model_dump(mode="json"),
            realism_score=audit.realism_score, ad_score=audit.ad_score,
            decision=audit.decision.value,
            issue_category=audit.issue.category.value if audit.issue else None,
            issue_description=audit.issue.description if audit.issue else None,
            route_to_agent=audit.issue.route_to_agent if audit.issue else None,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def for_clip(self, clip_id: str) -> list[ClipAudit]:
        return list(self.session.scalars(
            select(ClipAudit).where(ClipAudit.clip_id == clip_id)
            .order_by(ClipAudit.cycle)))
