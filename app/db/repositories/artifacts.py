"""
Repositorio de artefactos.

Los agentes reciben objetos Pydantic y devuelven objetos Pydantic. Esta capa
es la única que sabe que existe una base de datos, y traduce entre ambos
mundos.

Las dos operaciones que el orquestador ejecuta constantemente:

    latest_approved(project, tipo)   → el artefacto vigente
    create_version(project, artefacto) → versión nueva, nunca UPDATE
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...contracts import ArtifactBase, ArtifactStatus, ArtifactType, parse_artifact
from ..models import Artifact, Project


class ArtifactRepository:
    def __init__(self, session: Session):
        self.session = session

    # -- lectura ------------------------------------------------------

    def latest(self, project_id: str, type_: ArtifactType | str,
               clip_id: str | None = None,
               status: ArtifactStatus | str | None = None) -> Artifact | None:
        tipo = ArtifactType(type_).value
        stmt = (select(Artifact)
                .where(Artifact.project_id == project_id,
                       Artifact.type == tipo,
                       Artifact.clip_id.is_(clip_id) if clip_id is None
                       else Artifact.clip_id == clip_id)
                .order_by(Artifact.version.desc()))
        if status is not None:
            stmt = stmt.where(Artifact.status == ArtifactStatus(status).value)
        return self.session.scalars(stmt).first()

    def latest_approved(self, project_id: str, type_: ArtifactType | str,
                        clip_id: str | None = None) -> Artifact | None:
        return self.latest(project_id, type_, clip_id, ArtifactStatus.APPROVED)

    def load(self, row: Artifact) -> ArtifactBase:
        """Fila → contrato Pydantic validado."""
        return parse_artifact(row.type, row.payload)

    def history(self, project_id: str, type_: ArtifactType | str,
                clip_id: str | None = None) -> list[Artifact]:
        """Todas las versiones, de la más nueva a la más vieja."""
        tipo = ArtifactType(type_).value
        stmt = (select(Artifact)
                .where(Artifact.project_id == project_id,
                       Artifact.type == tipo,
                       Artifact.clip_id.is_(clip_id) if clip_id is None
                       else Artifact.clip_id == clip_id)
                .order_by(Artifact.version.desc()))
        return list(self.session.scalars(stmt))

    def next_version(self, project_id: str, type_: ArtifactType | str,
                     clip_id: str | None = None) -> int:
        ultimo = self.latest(project_id, type_, clip_id)
        return (ultimo.version + 1) if ultimo else 1

    # -- escritura ----------------------------------------------------

    def create_version(self, project_id: str, artifact: ArtifactBase, *,
                       clip_id: str | None = None,
                       input_ref: str | None = None) -> Artifact:
        """
        Inserta una versión nueva. Nunca sobrescribe el payload de una
        anterior: es lo que hace posible abrir un anuncio tres meses después
        y ver exactamente qué produjo qué.

        El número de versión lo asigna la base, no el agente: dos agentes
        concurrentes no pueden reclamar el mismo.
        """
        version = self.next_version(project_id, artifact.artifact, clip_id)
        row = Artifact(
            project_id=project_id,
            type=ArtifactType(artifact.artifact).value,
            version=version,
            status=ArtifactStatus(artifact.status).value,
            payload=artifact.model_dump(mode="json"),
            created_by=artifact.created_by,
            input_ref=input_ref,
            clip_id=clip_id,
            clip_key=clip_id or "",
            schema_version=artifact.schema_version,
            errors=[e.model_dump(mode="json") for e in artifact.errors],
        )
        self.session.add(row)
        self.session.flush()
        return row

    def approve(self, artifact_id: str) -> Artifact:
        """
        Aprueba una versión y marca las anteriores del mismo tipo como
        superadas, para que `latest_approved` no devuelva una vieja si la
        nueva se rechaza después.
        """
        row = self.session.get(Artifact, artifact_id)
        if row is None:
            raise KeyError(f"No existe el artefacto {artifact_id}.")

        for previa in self.history(row.project_id, row.type, row.clip_id):
            if (previa.id != row.id
                    and previa.status == ArtifactStatus.APPROVED.value):
                previa.status = ArtifactStatus.SUPERSEDED.value

        row.status = ArtifactStatus.APPROVED.value
        self.session.flush()
        return row

    def reject(self, artifact_id: str) -> Artifact:
        row = self.session.get(Artifact, artifact_id)
        if row is None:
            raise KeyError(f"No existe el artefacto {artifact_id}.")
        row.status = ArtifactStatus.REJECTED.value
        self.session.flush()
        return row

    # -- trazabilidad -------------------------------------------------

    def lineage(self, artifact_id: str) -> list[Artifact]:
        """
        Cadena hacia atrás desde un artefacto hasta el brief original.

        Sigue `input_ref`, que apunta a la versión que realmente se usó — no a
        la última. Es la diferencia entre saber cómo se llegó al resultado y
        suponerlo.
        """
        cadena: list[Artifact] = []
        actual = self.session.get(Artifact, artifact_id)
        vistos: set[str] = set()
        while actual is not None and actual.id not in vistos:
            cadena.append(actual)
            vistos.add(actual.id)
            actual = (self.session.get(Artifact, actual.input_ref)
                      if actual.input_ref else None)
        return cadena


class ProjectRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, *, code: str, brand_name: str, product_name: str,
               **kw) -> Project:
        row = Project(code=code, brand_name=brand_name,
                      product_name=product_name, **kw)
        self.session.add(row)
        self.session.flush()
        return row

    def by_code(self, code: str) -> Project | None:
        return self.session.scalars(
            select(Project).where(Project.code == code)).first()

    def add_cost(self, project_id: str, cost_usd: float) -> Project:
        row = self.session.get(Project, project_id)
        if row is None:
            raise KeyError(f"No existe el proyecto {project_id}.")
        row.total_cost_usd = round((row.total_cost_usd or 0.0) + cost_usd, 6)
        self.session.flush()
        return row

    def set_stage(self, project_id: str, stage: str, status: str) -> Project:
        row = self.session.get(Project, project_id)
        if row is None:
            raise KeyError(f"No existe el proyecto {project_id}.")
        row.current_stage = stage
        row.stage_status = status
        self.session.flush()
        return row
