"""Repositorio de clips."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Clip


class ClipRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_or_create(self, project_id: str, code: str, *,
                      sequence_order: int | None = None,
                      role: str | None = None,
                      dialogue: str | None = None) -> Clip:
        existente = self.by_code(project_id, code)
        if existente is not None:
            return existente
        row = Clip(project_id=project_id, code=code,
                   sequence_order=sequence_order or 0, role=role,
                   dialogue=dialogue)
        self.session.add(row)
        self.session.flush()
        return row

    def by_code(self, project_id: str, code: str) -> Clip | None:
        return self.session.scalars(
            select(Clip).where(Clip.project_id == project_id,
                               Clip.code == code)).first()

    def for_project(self, project_id: str) -> list[Clip]:
        return list(self.session.scalars(
            select(Clip).where(Clip.project_id == project_id)
            .order_by(Clip.sequence_order)))
