"""
Endpoints de artefactos.

Aprobar y rechazar son las dos acciones que un humano ejerce sobre el
trabajo de un agente — el resto (crear versiones nuevas) sólo lo hace el
sistema al correr una etapa, nunca directo desde aquí.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db import ArtifactRepository, ProjectRepository
from ...db.models import Artifact
from ..deps import get_session
from ..schemas import ArtifactOut

router = APIRouter(tags=["artifacts"])


@router.get("/projects/{code}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(code: str, type: str | None = None,
                   clip_id: str | None = None,
                   session: Session = Depends(get_session)):
    proyecto = _project_or_404(code, session)
    repo = ArtifactRepository(session)
    if type is not None:
        return repo.history(proyecto.id, type, clip_id=clip_id)
    # Sin filtro de tipo: se listan todos los tipos conocidos y se combinan.
    from ...contracts import ArtifactType
    resultado = []
    for t in ArtifactType:
        resultado.extend(repo.history(proyecto.id, t, clip_id=clip_id))
    resultado.sort(key=lambda a: a.created_at, reverse=True)
    return resultado


@router.get("/artifacts/{artifact_id}", response_model=ArtifactOut)
def get_artifact(artifact_id: str, session: Session = Depends(get_session)):
    return _artifact_or_404(artifact_id, session)


@router.post("/artifacts/{artifact_id}/approve", response_model=ArtifactOut)
def approve_artifact(artifact_id: str, session: Session = Depends(get_session)):
    _artifact_or_404(artifact_id, session)
    return ArtifactRepository(session).approve(artifact_id)


@router.post("/artifacts/{artifact_id}/reject", response_model=ArtifactOut)
def reject_artifact(artifact_id: str, session: Session = Depends(get_session)):
    _artifact_or_404(artifact_id, session)
    return ArtifactRepository(session).reject(artifact_id)


def _project_or_404(code: str, session: Session):
    proyecto = ProjectRepository(session).by_code(code)
    if proyecto is None:
        raise HTTPException(404, f"No existe el proyecto '{code}'.")
    return proyecto


def _artifact_or_404(artifact_id: str, session: Session):
    fila = session.get(Artifact, artifact_id)
    if fila is None:
        raise HTTPException(404, f"No existe el artefacto '{artifact_id}'.")
    return fila
