"""
Endpoints de marcas.

Una marca se crea una vez y se reutiliza en cada campaña — su brief (voz,
audiencia conocida, reclamos prohibidos, competidores) no se vuelve a
escribir cada vez.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db import BrandRepository
from ..deps import get_session
from ..schemas import BrandCreate, BrandOut, BrandUpdate, ProjectOut

router = APIRouter(prefix="/brands", tags=["brands"])


@router.post("", response_model=BrandOut, status_code=201)
def create_brand(body: BrandCreate, session: Session = Depends(get_session)):
    repo = BrandRepository(session)
    if repo.by_name(body.name) is not None:
        raise HTTPException(409, f"Ya existe una marca llamada '{body.name}'.")
    return repo.create(**body.model_dump())


@router.get("", response_model=list[BrandOut])
def list_brands(session: Session = Depends(get_session)):
    return BrandRepository(session).list_active()


@router.get("/{brand_id}", response_model=BrandOut)
def get_brand(brand_id: str, session: Session = Depends(get_session)):
    return _brand_or_404(brand_id, session)


@router.patch("/{brand_id}", response_model=BrandOut)
def update_brand(brand_id: str, body: BrandUpdate,
                 session: Session = Depends(get_session)):
    _brand_or_404(brand_id, session)
    cambios = body.model_dump(exclude_unset=True)
    return BrandRepository(session).update(brand_id, **cambios)


@router.get("/{brand_id}/projects", response_model=list[ProjectOut])
def list_brand_campaigns(brand_id: str, session: Session = Depends(get_session)):
    """El historial: todas las campañas que se han corrido para esta marca."""
    _brand_or_404(brand_id, session)
    return BrandRepository(session).campaigns_for(brand_id)


def _brand_or_404(brand_id: str, session: Session):
    marca = BrandRepository(session).by_id(brand_id)
    if marca is None:
        raise HTTPException(404, f"No existe la marca '{brand_id}'.")
    return marca
