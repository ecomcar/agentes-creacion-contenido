"""
Repositorio de marcas.

Separa "quién es el cliente" de "qué campaña se está corriendo": una marca
tiene un solo brief persistente, muchas campañas lo reutilizan.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Brand, Project


class BrandRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, *, name: str, default_audience: dict | None = None,
              brand_voice: str | None = None,
              forbidden_claims: list | None = None,
              competitors: list | None = None,
              notes: str | None = None) -> Brand:
        marca = Brand(
            name=name, default_audience=default_audience or {},
            brand_voice=brand_voice, forbidden_claims=forbidden_claims or [],
            competitors=competitors or [], notes=notes,
        )
        self.session.add(marca)
        self.session.flush()
        return marca

    def by_id(self, brand_id: str) -> Brand | None:
        return self.session.get(Brand, brand_id)

    def by_name(self, name: str) -> Brand | None:
        return self.session.scalars(
            select(Brand).where(Brand.name == name)).first()

    def list_active(self) -> list[Brand]:
        return list(self.session.scalars(
            select(Brand).where(Brand.is_active == True)  # noqa: E712
            .order_by(Brand.name)))

    def update(self, brand_id: str, **cambios) -> Brand:
        """
        Actualización parcial: sólo toca los campos que vengan en `cambios`.
        Permite "afinar" el brief con lo aprendido campaña tras campaña sin
        tener que reenviar todo el objeto cada vez.
        """
        marca = self.session.get(Brand, brand_id)
        if marca is None:
            raise KeyError(f"No existe la marca {brand_id}.")
        for campo, valor in cambios.items():
            if valor is not None and hasattr(marca, campo):
                setattr(marca, campo, valor)
        self.session.flush()
        return marca

    def campaigns_for(self, brand_id: str) -> list[Project]:
        """El historial: todas las campañas corridas para esta marca."""
        return list(self.session.scalars(
            select(Project).where(Project.brand_id == brand_id)
            .order_by(Project.created_at.desc())))
