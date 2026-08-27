"""
Endpoints de etapas: corren los agentes 1-4 sobre un proyecto.

Regla de diseño: sólo lo que requiere una decisión humana va en el body de
la petición (el ángulo elegido, el hook elegido). Todo lo demás —el brief,
la estrategia aprobada— se busca en la base como el último artefacto
aprobado del proyecto. El cliente de la API nunca tiene que reenviar datos
que el sistema ya tiene guardados.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...agents import ProductInput
from ...contracts import (
    ArtifactType,
    Hooks,
    ResearchBrief,
    Storyboard,
    Strategy,
    UGCScript,
)
from ...db import ArtifactRepository, ClipRepository, ProjectRepository
from ...orchestrator import Orchestrator, ProjectState, Stage, StageStatus
from ..deps import get_orchestrator, get_session
from ..schemas import (
    RunHooksIn,
    RunIdentityIn,
    RunResearchIn,
    RunScriptIn,
    RunStoryboardIn,
    RunStrategyIn,
    StageIssueOut,
    StageResultOut,
)

router = APIRouter(prefix="/projects/{code}/stages", tags=["stages"])


def _state_from_project(proyecto) -> ProjectState:
    """
    Reconstruye el ProjectState en memoria que el Orchestrator necesita, a
    partir de lo que ya está persistido — mismo puente DB↔memoria usado en
    `continuar_demo_c02.py`, aplicado aquí de forma sistemática.
    """
    return ProjectState(
        project_code=proyecto.code, current_stage=Stage(proyecto.current_stage),
        stage_status=StageStatus(proyecto.stage_status),
        auto_mode=proyecto.auto_mode, retry_counts=dict(proyecto.retry_counts or {}),
        total_cost_usd=proyecto.total_cost_usd,
    )


def _persist_outcome(session: Session, proyecto, state: ProjectState, out,
                     stage: Stage) -> StageResultOut:
    artifact_repo = ArtifactRepository(session)
    proj_repo = ProjectRepository(session)

    artifact_out = None
    if out.artifact is not None:
        fila = artifact_repo.create_version(proyecto.id, out.artifact)
        if out.status is StageStatus.APPROVED:
            artifact_repo.approve(fila.id)
        artifact_out = fila

    # El estado de reintentos y la etapa/estado del proyecto se guardan tal
    # como quedaron en el ProjectState en memoria tras correr la etapa.
    proyecto.retry_counts = state.retry_counts
    proyecto.current_stage = state.current_stage.value
    proyecto.stage_status = state.stage_status.value
    proj_repo.add_cost(proyecto.id, out.cost_usd)
    session.flush()

    return StageResultOut(
        stage=stage.value, status=out.status.value, message=out.message,
        cost_usd=out.cost_usd,
        artifact=artifact_out, issues=[
            StageIssueOut(code=i.code, message=i.message,
                         severity=i.severity.value, field=i.field)
            for i in out.issues],
    )


@router.post("/research", response_model=StageResultOut)
def run_research(code: str, body: RunResearchIn,
                 session: Session = Depends(get_session),
                 orch: Orchestrator = Depends(get_orchestrator)):
    proyecto = _project_or_404(code, session)
    state = _state_from_project(proyecto)
    if state.current_stage is not Stage.RESEARCH:
        raise HTTPException(409, f"El proyecto está en la etapa "
                            f"'{state.current_stage.value}', no en 'research'.")

    payload = ProductInput(**body.model_dump(exclude={"feedback"}))
    out = orch.run_stage(state, Stage.RESEARCH, payload, feedback=body.feedback)
    if out.status is StageStatus.APPROVED:
        orch.approve_and_advance(state)
    return _persist_outcome(session, proyecto, state, out, Stage.RESEARCH)


@router.post("/strategy", response_model=StageResultOut)
def run_strategy(code: str, body: RunStrategyIn,
                 session: Session = Depends(get_session),
                 orch: Orchestrator = Depends(get_orchestrator)):
    proyecto = _project_or_404(code, session)
    state = _state_from_project(proyecto)
    if state.current_stage is not Stage.STRATEGY:
        raise HTTPException(409, f"El proyecto está en la etapa "
                            f"'{state.current_stage.value}', no en 'strategy'.")

    brief_row = ArtifactRepository(session).latest_approved(
        proyecto.id, ArtifactType.RESEARCH_BRIEF)
    if brief_row is None:
        raise HTTPException(409, "No hay un brief de investigación aprobado "
                            "todavía.")
    brief = ResearchBrief.model_validate(brief_row.payload)

    out = orch.run_stage(state, Stage.STRATEGY, brief, feedback=body.feedback)
    return _persist_outcome(session, proyecto, state, out, Stage.STRATEGY)


@router.post("/storyboard", response_model=StageResultOut)
def run_storyboard(code: str, body: RunStoryboardIn,
                   session: Session = Depends(get_session),
                   orch: Orchestrator = Depends(get_orchestrator)):
    proyecto = _project_or_404(code, session)
    state = _state_from_project(proyecto)
    if state.current_stage is not Stage.STORYBOARD:
        raise HTTPException(409, f"El proyecto está en la etapa "
                            f"'{state.current_stage.value}', no en "
                            f"'storyboard'.")

    script_row = ArtifactRepository(session).latest_approved(
        proyecto.id, ArtifactType.UGC_SCRIPT)
    if script_row is None:
        raise HTTPException(409, "No hay un guion aprobado todavía.")
    script = UGCScript.model_validate(script_row.payload)

    out = orch.run_stage(state, Stage.STORYBOARD, script, feedback=body.feedback)
    return _persist_outcome(session, proyecto, state, out, Stage.STORYBOARD)


@router.post("/identity", response_model=StageResultOut)
def run_identity(code: str, body: RunIdentityIn,
                 session: Session = Depends(get_session),
                 orch: Orchestrator = Depends(get_orchestrator)):
    """
    Etapa sin compuerta humana (no está en `HUMAN_GATES`): la identidad
    del avatar se reutiliza en decenas de clips, así que el criterio que
    manda es el contrato (imperfecciones mínimas, rasgos sin vaguedad),
    no una revisión manual del texto. Por eso se auto-aprueba y avanza,
    igual que 'research'.
    """
    proyecto = _project_or_404(code, session)
    state = _state_from_project(proyecto)
    if state.current_stage is not Stage.IDENTITY:
        raise HTTPException(409, f"El proyecto está en la etapa "
                            f"'{state.current_stage.value}', no en "
                            f"'identity'.")

    storyboard_row = ArtifactRepository(session).latest_approved(
        proyecto.id, ArtifactType.STORYBOARD)
    if storyboard_row is None:
        raise HTTPException(409, "No hay un storyboard aprobado todavía.")
    storyboard = Storyboard.model_validate(storyboard_row.payload)

    out = orch.run_stage(state, Stage.IDENTITY,
                         (storyboard, body.avatar_id, body.description),
                         feedback=body.feedback)
    if out.status is StageStatus.APPROVED:
        orch.approve_and_advance(state)
    return _persist_outcome(session, proyecto, state, out, Stage.IDENTITY)


# Qué tipo de artefacto corresponde a cada etapa aprobable — un único
# endpoint genérico sirve a las cuatro, en vez de repetir la misma lógica
# de "aprobar y avanzar" por etapa (el error que se evitó aquí: la primera
# versión sólo tenía este endpoint para 'strategy', y 'hooks'/'script'
# se habrían quedado sin forma de avanzar la etapa del proyecto).
STAGE_ARTIFACT_TYPE = {
    Stage.RESEARCH: ArtifactType.RESEARCH_BRIEF,
    Stage.STRATEGY: ArtifactType.STRATEGY,
    Stage.HOOKS: ArtifactType.HOOKS,
    Stage.SCRIPT: ArtifactType.UGC_SCRIPT,
    Stage.STORYBOARD: ArtifactType.STORYBOARD,
}


@router.post("/approve", response_model=StageResultOut)
def approve_current_stage(code: str, session: Session = Depends(get_session),
                          orch: Orchestrator = Depends(get_orchestrator)):
    """
    Aprueba el artefacto pendiente de la etapa actual y avanza el proyecto
    a la siguiente. Distinto del endpoint genérico
    `/artifacts/{id}/approve`, que sólo marca el artefacto sin tocar el
    estado del pipeline — éste sí avanza la etapa, que es lo que un humano
    espera al "aprobar y seguir".
    """
    proyecto = _project_or_404(code, session)
    state = _state_from_project(proyecto)

    if state.stage_status is not StageStatus.PENDING_HUMAN_APPROVAL:
        raise HTTPException(
            409, f"La etapa '{state.current_stage.value}' no está esperando "
                f"aprobación (estado actual: {state.stage_status.value}).")

    tipo = STAGE_ARTIFACT_TYPE.get(state.current_stage)
    if tipo is None:
        raise HTTPException(
            409, f"La etapa '{state.current_stage.value}' todavía no se "
                f"aprueba desde la API.")

    fila = ArtifactRepository(session).latest(proyecto.id, tipo)
    if fila is None:
        raise HTTPException(404, "No hay artefacto pendiente para aprobar.")

    ArtifactRepository(session).approve(fila.id)

    if state.current_stage is Stage.STORYBOARD:
        # Nada en el sistema creaba filas de `clips` hasta ahora — se
        # esperaba hacerlo a mano por `POST /clips`. El storyboard ya
        # trae los mismos clip_id que el guion, así que aprobarlo es el
        # momento natural para crear los que falten. Idempotente:
        # `get_or_create` no duplica si el humano ya los había creado.
        script_row = ArtifactRepository(session).latest_approved(
            proyecto.id, ArtifactType.UGC_SCRIPT)
        if script_row is not None:
            clip_repo = ClipRepository(session)
            for i, c in enumerate(script_row.payload.get("clips", [])):
                clip_repo.get_or_create(
                    proyecto.id, c["clip_id"], sequence_order=i + 1,
                    role=c.get("role"), dialogue=c.get("dialogue"))

    etapa_anterior = state.current_stage
    orch.approve_and_advance(state)
    proyecto.current_stage = state.current_stage.value
    proyecto.stage_status = state.stage_status.value
    session.flush()

    return StageResultOut(
        stage=etapa_anterior.value, status="approved",
        message=f"'{etapa_anterior.value}' aprobado, avanzó a "
                f"'{state.current_stage.value}'.",
        cost_usd=0.0)


@router.post("/reject", response_model=StageResultOut)
def reject_current_stage(code: str, session: Session = Depends(get_session)):
    """
    Rechaza el artefacto pendiente de la etapa actual. El proyecto se
    queda en la misma etapa — el cliente reintenta llamando de nuevo al
    endpoint de esa etapa, opcionalmente con `feedback`.
    """
    proyecto = _project_or_404(code, session)
    state = _state_from_project(proyecto)
    tipo = STAGE_ARTIFACT_TYPE.get(state.current_stage)
    if tipo is None:
        raise HTTPException(
            409, f"La etapa '{state.current_stage.value}' todavía no se "
                f"rechaza desde la API.")

    fila = ArtifactRepository(session).latest(proyecto.id, tipo)
    if fila is None:
        raise HTTPException(404, "No hay artefacto pendiente para rechazar.")

    ArtifactRepository(session).reject(fila.id)
    return StageResultOut(
        stage=state.current_stage.value, status="rejected",
        message=f"Rechazado. Reintenta el endpoint de "
                f"'{state.current_stage.value}' con feedback si hace falta.",
        cost_usd=0.0)


@router.post("/hooks", response_model=StageResultOut)
def run_hooks(code: str, body: RunHooksIn,
             session: Session = Depends(get_session),
             orch: Orchestrator = Depends(get_orchestrator)):
    proyecto = _project_or_404(code, session)
    state = _state_from_project(proyecto)
    if state.current_stage is not Stage.HOOKS:
        raise HTTPException(409, f"El proyecto está en la etapa "
                            f"'{state.current_stage.value}', no en 'hooks'.")

    strategy_row = ArtifactRepository(session).latest_approved(
        proyecto.id, ArtifactType.STRATEGY)
    if strategy_row is None:
        raise HTTPException(409, "No hay una estrategia aprobada todavía.")
    strategy = Strategy.model_validate(strategy_row.payload)
    if body.angle_id not in {a.angle_id for a in strategy.angles}:
        raise HTTPException(422, f"El ángulo '{body.angle_id}' no existe en "
                            f"la estrategia aprobada.")

    out = orch.run_stage(state, Stage.HOOKS, (strategy, body.angle_id),
                         feedback=body.feedback)
    return _persist_outcome(session, proyecto, state, out, Stage.HOOKS)


@router.post("/script", response_model=StageResultOut)
def run_script(code: str, body: RunScriptIn,
              session: Session = Depends(get_session),
              orch: Orchestrator = Depends(get_orchestrator)):
    proyecto = _project_or_404(code, session)
    state = _state_from_project(proyecto)
    if state.current_stage is not Stage.SCRIPT:
        raise HTTPException(409, f"El proyecto está en la etapa "
                            f"'{state.current_stage.value}', no en 'script'.")

    strategy_row = ArtifactRepository(session).latest_approved(
        proyecto.id, ArtifactType.STRATEGY)
    hooks_row = ArtifactRepository(session).latest_approved(
        proyecto.id, ArtifactType.HOOKS)
    if strategy_row is None or hooks_row is None:
        raise HTTPException(409, "Falta la estrategia o los hooks aprobados.")
    strategy = Strategy.model_validate(strategy_row.payload)
    hooks = Hooks.model_validate(hooks_row.payload)
    if body.hook_id not in {h.hook_id for h in hooks.hooks}:
        raise HTTPException(422, f"El hook '{body.hook_id}' no existe en el "
                            f"banco aprobado.")

    out = orch.run_stage(state, Stage.SCRIPT,
                         (strategy, hooks, body.hook_id, body.target_duration_sec),
                         feedback=body.feedback)
    return _persist_outcome(session, proyecto, state, out, Stage.SCRIPT)


def _project_or_404(code: str, session: Session):
    proyecto = ProjectRepository(session).by_code(code)
    if proyecto is None:
        raise HTTPException(404, f"No existe el proyecto '{code}'.")
    return proyecto
