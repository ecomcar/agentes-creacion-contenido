"""Endpoints de proyectos y clips."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db import ClipRepository, ProjectRepository
from ..deps import get_session
from ..schemas import ClipCreate, ClipOut, ProjectCreate, ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, session: Session = Depends(get_session)):
    repo = ProjectRepository(session)
    if repo.by_code(body.code) is not None:
        raise HTTPException(409, f"Ya existe un proyecto con code '{body.code}'.")
    proyecto = repo.create(**body.model_dump())
    return proyecto


@router.get("/{code}", response_model=ProjectOut)
def get_project(code: str, session: Session = Depends(get_session)):
    proyecto = ProjectRepository(session).by_code(code)
    if proyecto is None:
        raise HTTPException(404, f"No existe el proyecto '{code}'.")
    return proyecto


@router.get("/{code}/clips", response_model=list[ClipOut])
def list_clips(code: str, session: Session = Depends(get_session)):
    proyecto = _get_project_or_404(code, session)
    return ClipRepository(session).for_project(proyecto.id)


@router.post("/{code}/clips", response_model=ClipOut, status_code=201)
def create_clip(code: str, body: ClipCreate, session: Session = Depends(get_session)):
    proyecto = _get_project_or_404(code, session)
    clip_repo = ClipRepository(session)
    if clip_repo.by_code(proyecto.id, body.code) is not None:
        raise HTTPException(
            409, f"El clip '{body.code}' ya existe en este proyecto.")
    return clip_repo.get_or_create(proyecto.id, body.code,
                                   sequence_order=body.sequence_order,
                                   role=body.role, dialogue=body.dialogue)


def _get_project_or_404(code: str, session: Session):
    proyecto = ProjectRepository(session).by_code(code)
    if proyecto is None:
        raise HTTPException(404, f"No existe el proyecto '{code}'.")
    return proyecto
