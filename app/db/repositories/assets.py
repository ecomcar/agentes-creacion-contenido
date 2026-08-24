"""
Repositorio de assets.

Traduce entre el `Asset` Pydantic que ya usan los tres servicios de
generación (imagen, video, audio) y la fila `AssetRow` de la base de datos.
La garantía de "una sola variante seleccionada por clip y tipo" vive en un
índice parcial único de la propia base — este repositorio no la reimplementa,
sólo hace el `UPDATE` que la base aceptará o rechazará.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AssetRow


class AssetRepository:
    def __init__(self, session: Session):
        self.session = session

    def next_version(self, project_id: str, clip_id: str | None,
                     kind: str) -> int:
        stmt = (select(AssetRow)
                .where(AssetRow.project_id == project_id, AssetRow.kind == kind,
                       AssetRow.clip_id.is_(clip_id) if clip_id is None
                       else AssetRow.clip_id == clip_id)
                .order_by(AssetRow.version.desc()))
        ultimo = self.session.scalars(stmt).first()
        return (ultimo.version + 1) if ultimo else 1

    def create(self, *, project_id: str, clip_id: str | None, kind: str,
              storage_url: str, provider: str | None = None,
              cost_usd: float = 0.0, duration_sec: float | None = None,
              source_artifact_id: str | None = None,
              is_selected: bool = False) -> AssetRow:
        if is_selected:
            # Deseleccionar y flushear ANTES de crear la nueva fila. Si se
            # hiciera todo en el mismo flush, el orden entre el UPDATE de
            # deselección y el INSERT no está garantizado — puede llegar
            # primero el INSERT con is_selected=True mientras la fila vieja
            # sigue en True, y el índice único de la base lo rechaza en ese
            # instante intermedio.
            self._deselect_all(project_id, clip_id, kind)
            self.session.flush()

        row = AssetRow(
            project_id=project_id, clip_id=clip_id, kind=kind,
            version=self.next_version(project_id, clip_id, kind),
            storage_url=storage_url, provider=provider, cost_usd=cost_usd,
            duration_sec=duration_sec, source_artifact_id=source_artifact_id,
            is_selected=is_selected,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def select(self, asset_id: str) -> AssetRow:
        row = self.session.get(AssetRow, asset_id)
        if row is None:
            raise KeyError(f"No existe el asset {asset_id}.")
        # Mismo motivo: deseleccionar y flushear antes de activar ésta.
        self._deselect_others(row.project_id, row.clip_id, row.kind, exclude=row)
        self.session.flush()
        row.is_selected = True
        self.session.flush()
        return row

    def _deselect_all(self, project_id: str, clip_id: str | None,
                      kind: str) -> None:
        stmt = select(AssetRow).where(
            AssetRow.project_id == project_id, AssetRow.kind == kind,
            AssetRow.clip_id.is_(clip_id) if clip_id is None
            else AssetRow.clip_id == clip_id,
            AssetRow.is_selected == True,  # noqa: E712
        )
        for fila in self.session.scalars(stmt):
            fila.is_selected = False

    def _deselect_others(self, project_id: str, clip_id: str | None,
                         kind: str, exclude: AssetRow) -> None:
        stmt = select(AssetRow).where(
            AssetRow.project_id == project_id, AssetRow.kind == kind,
            AssetRow.clip_id.is_(clip_id) if clip_id is None
            else AssetRow.clip_id == clip_id,
            AssetRow.is_selected == True,  # noqa: E712
        )
        for otro in self.session.scalars(stmt):
            if otro is not exclude:
                otro.is_selected = False

    def selected_for(self, project_id: str, clip_id: str,
                     kind: str) -> AssetRow | None:
        stmt = select(AssetRow).where(
            AssetRow.project_id == project_id, AssetRow.clip_id == clip_id,
            AssetRow.kind == kind, AssetRow.is_selected == True)  # noqa: E712
        return self.session.scalars(stmt).first()

    def for_clip(self, project_id: str, clip_id: str,
                kind: str | None = None) -> list[AssetRow]:
        stmt = select(AssetRow).where(AssetRow.project_id == project_id,
                                      AssetRow.clip_id == clip_id)
        if kind is not None:
            stmt = stmt.where(AssetRow.kind == kind)
        return list(self.session.scalars(stmt.order_by(AssetRow.version)))
