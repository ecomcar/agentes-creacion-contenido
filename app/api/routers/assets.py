"""Endpoints de assets (imagen/video/audio generados)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db import AssetRepository, ClipRepository, ProjectRepository
from ...db.models import AssetRow
from ..deps import get_session
from ..schemas import AssetOut

router = APIRouter(tags=["assets"])


@router.get("/projects/{code}/clips/{clip_code}/assets",
           response_model=list[AssetOut])
def list_clip_assets(code: str, clip_code: str, kind: str | None = None,
                     session: Session = Depends(get_session)):
    proyecto = _project_or_404(code, session)
    clip_repo = ClipRepository(session)
    clip = clip_repo.by_code(proyecto.id, clip_code)
    if clip is None:
        raise HTTPException(404, f"No existe el clip '{clip_code}'.")
    return AssetRepository(session).for_clip(proyecto.id, clip.id, kind=kind)


@router.post("/assets/{asset_id}/select", response_model=AssetOut)
def select_asset(asset_id: str, session: Session = Depends(get_session)):
    if session.get(AssetRow, asset_id) is None:
        raise HTTPException(404, f"No existe el asset '{asset_id}'.")
    return AssetRepository(session).select(asset_id)


def _project_or_404(code: str, session: Session):
    proyecto = ProjectRepository(session).by_code(code)
    if proyecto is None:
        raise HTTPException(404, f"No existe el proyecto '{code}'.")
    return proyecto
