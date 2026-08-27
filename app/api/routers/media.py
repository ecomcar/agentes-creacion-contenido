"""
Endpoints de medios: la referencia del avatar, y por cada clip la imagen,
el video y la voz.

Deliberadamente NO usan el `Orchestrator` de la máquina de estados (ver el
comentario en `deps.get_orchestrator`). Los agentes 7-9 se ejecutan
directos contra el gateway — mismo patrón que ya usan los scripts de
terminal (`demo_pipeline_multiclip.py` llama a `AuditorAgent.run(gw, ...)`
sin pasar por el Orchestrator) — y el prompt que producen se aprueba de
inmediato: la decisión humana real en estas etapas es qué variante
generada elegir, algo que ya resuelve `POST /assets/{id}/select`.

`current_stage` sigue siendo un solo valor por proyecto, así que el
avance de IMAGE→VIDEO→VOICE no lo dispara aprobar un artefacto (como en
1-6) sino un endpoint explícito (`/stages/advance`) que comprueba que
todos los clips ya tienen el asset seleccionado que la siguiente etapa
necesita.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...contracts import (
    ArtifactType,
    CharacterBible,
    ImagePrompt,
    SceneTemplate,
    Storyboard,
    UGCScript,
    VideoPrompt,
)
from ...db import ArtifactRepository, AssetRepository, ClipRepository, ProjectRepository
from ...db.models import Clip, Project
from ...gateway import AIGateway
from ...orchestrator import Stage, StateMachine
from ...services import (
    AudioBlocked,
    AudioGenerationService,
    GenerationBlocked,
    ImageGenerationService,
    VideoBlocked,
    VideoGenerationService,
    get_by_name,
)
from ...services.image_generation import Asset as ServiceAsset
from ..deps import (
    get_audio_service,
    get_gateway,
    get_image_service,
    get_media_agents,
    get_session,
    get_video_service,
)
from ..schemas import (
    AdvanceStageOut,
    AssetOut,
    GenerateImageIn,
    GenerateReferenceIn,
    GenerateVideoIn,
    GenerateVoiceIn,
    JobOut,
    MediaGenerationOut,
    StageIssueOut,
)

router = APIRouter(prefix="/projects/{code}", tags=["media"])


# ------------------------------------------------------ referencia del avatar


@router.post("/avatar/reference", response_model=AssetOut)
def generate_avatar_reference(code: str, body: GenerateReferenceIn,
                              session: Session = Depends(get_session),
                              image_svc: ImageGenerationService = Depends(get_image_service)):
    """
    Genera (o reutiliza) la imagen frontal que ancla la identidad del
    avatar. Es la única generación de imagen que no se anda por un clip
    ni por el Agente 7: es mecánica, una sola vez por avatar, igual que
    la construye `demo_pipeline_multiclip.py` a mano.
    """
    proyecto = _project_or_404(code, session)
    asset_repo = AssetRepository(session)

    existente = asset_repo.selected_for(proyecto.id, None, "image")
    if existente is not None:
        return existente

    bible_row = ArtifactRepository(session).latest_approved(
        proyecto.id, ArtifactType.CHARACTER_BIBLE)
    if bible_row is None:
        raise HTTPException(409, "No hay una ficha de identidad aprobada "
                            "todavía. Correr /stages/identity primero.")
    bible = CharacterBible.model_validate(bible_row.payload)

    prompt_text = body.prompt_text or (
        f"Vertical smartphone photo of a {bible.physical.age_range} year old "
        f"person from {bible.physical.origin}, front-facing, neutral indoor "
        f"background, natural window light, casual expression. Face: "
        f"{bible.physical.face}. Hair: {bible.physical.hair}. Skin: "
        f"{bible.physical.skin}."
    )
    prompt = ImagePrompt(
        artifact="image_prompt", created_by="api", avatar_id=bible.avatar_id,
        template_code="NB_CHARACTER_CREATION", template_version=1,
        scene=SceneTemplate.CHARACTER_CREATION, prompt_text=prompt_text,
        identity_reference_used=False,
        imperfections_included=bible.natural_imperfections[:2] or
        ["visible skin texture", "flyaway hair strand"],
        negative_constraints=["studio lighting", "empty background"],
    )
    blocking = prompt.blocking_issues()
    if blocking:
        raise HTTPException(422, "; ".join(i.message for i in blocking))

    prompt_row = ArtifactRepository(session).create_version(
        proyecto.id, prompt, input_ref=bible_row.id)
    ArtifactRepository(session).approve(prompt_row.id)

    _hydrate_image_budget(image_svc, session, proyecto.id, clip_id=None)
    try:
        generados = image_svc.generate(prompt, project_code=code, n_variants=1)
    except GenerationBlocked as exc:
        raise HTTPException(422, str(exc)) from exc

    asset = generados[0]
    fila = asset_repo.create(
        project_id=proyecto.id, clip_id=None, kind="image",
        storage_url=asset.storage_url, provider=asset.provider,
        cost_usd=asset.cost_usd, source_artifact_id=prompt_row.id,
        is_selected=True)
    ProjectRepository(session).add_cost(proyecto.id, asset.cost_usd)
    return fila


# ------------------------------------------------------------------- imagen


@router.post("/clips/{clip_code}/image", response_model=MediaGenerationOut)
def generate_clip_image(code: str, clip_code: str, body: GenerateImageIn,
                        session: Session = Depends(get_session),
                        gateway: AIGateway = Depends(get_gateway),
                        media_agents: dict = Depends(get_media_agents),
                        image_svc: ImageGenerationService = Depends(get_image_service)):
    proyecto = _project_or_404(code, session)
    clip = _clip_or_404(proyecto, clip_code, session)
    artifact_repo = ArtifactRepository(session)
    asset_repo = AssetRepository(session)

    bible_row = artifact_repo.latest_approved(proyecto.id, ArtifactType.CHARACTER_BIBLE)
    storyboard_row = artifact_repo.latest_approved(proyecto.id, ArtifactType.STORYBOARD)
    if bible_row is None or storyboard_row is None:
        raise HTTPException(409, "Falta la ficha de identidad o el "
                            "storyboard aprobados.")
    ref_row = asset_repo.selected_for(proyecto.id, None, "image")
    if ref_row is None:
        raise HTTPException(409, "No hay imagen de referencia del avatar "
                            "todavía. Generarla en POST "
                            "/projects/{code}/avatar/reference primero.")

    bible = CharacterBible.model_validate(bible_row.payload)
    storyboard = Storyboard.model_validate(storyboard_row.payload)

    cost_antes = gateway.total_cost()
    prompt: ImagePrompt = media_agents[7].run(
        gateway, (bible, storyboard, clip_code), project_code=code,
        feedback=body.feedback, triggered_by="api")
    costo_prompt = round(gateway.total_cost() - cost_antes, 6)
    ProjectRepository(session).add_cost(proyecto.id, costo_prompt)

    prompt_row = artifact_repo.create_version(
        proyecto.id, prompt, clip_id=clip.id, input_ref=bible_row.id)

    blocking = prompt.blocking_issues()
    if blocking:
        return MediaGenerationOut(
            clip_code=clip_code, prompt_artifact=prompt_row,
            cost_prompt_usd=costo_prompt, cost_generation_usd=0.0,
            issues=[_issue_out(i) for i in prompt.approval_check()],
            message="El prompt de imagen no superó las compuertas; no se "
                    "generó nada. Revisar el feedback y reintentar.")

    artifact_repo.approve(prompt_row.id)

    _hydrate_image_budget(image_svc, session, proyecto.id, clip.id)
    try:
        generados = image_svc.generate(
            prompt, project_code=code, bible=bible,
            reference_urls=[ref_row.storage_url],
            n_variants=body.n_variants, seed=body.seed)
    except GenerationBlocked as exc:
        raise HTTPException(422, str(exc)) from exc

    filas = [asset_repo.create(
        project_id=proyecto.id, clip_id=clip.id, kind="image",
        storage_url=a.storage_url, provider=a.provider, cost_usd=a.cost_usd,
        source_artifact_id=prompt_row.id, is_selected=(len(generados) == 1))
        for a in generados]
    costo_generacion = round(sum(a.cost_usd for a in generados), 6)
    ProjectRepository(session).add_cost(proyecto.id, costo_generacion)
    clip.status = "image_generated"

    return MediaGenerationOut(
        clip_code=clip_code, prompt_artifact=prompt_row,
        cost_prompt_usd=costo_prompt, cost_generation_usd=costo_generacion,
        assets=filas,
        issues=[_issue_out(i) for i in prompt.approval_check()],
        message=f"{len(filas)} variante(s) generada(s). Elegir una con "
                f"POST /assets/{{id}}/select." if len(filas) > 1
                else "Imagen generada y seleccionada automáticamente "
                     "(única variante).")


# -------------------------------------------------------------------- video


@router.post("/clips/{clip_code}/video", response_model=MediaGenerationOut)
def generate_clip_video(code: str, clip_code: str, body: GenerateVideoIn,
                        session: Session = Depends(get_session),
                        gateway: AIGateway = Depends(get_gateway),
                        media_agents: dict = Depends(get_media_agents),
                        video_svc: VideoGenerationService = Depends(get_video_service)):
    """
    Encola el video y devuelve enseguida. No espera al resultado: el
    panel sondea `GET .../video/jobs/{job_id}` mientras Kling genera
    (1-3 minutos reales).
    """
    proyecto = _project_or_404(code, session)
    clip = _clip_or_404(proyecto, clip_code, session)
    artifact_repo = ArtifactRepository(session)
    asset_repo = AssetRepository(session)

    storyboard_row = artifact_repo.latest_approved(proyecto.id, ArtifactType.STORYBOARD)
    script_row = artifact_repo.latest_approved(proyecto.id, ArtifactType.UGC_SCRIPT)
    bible_row = artifact_repo.latest_approved(proyecto.id, ArtifactType.CHARACTER_BIBLE)
    if storyboard_row is None or script_row is None:
        raise HTTPException(409, "Falta el storyboard o el guion aprobados.")
    image_row = asset_repo.selected_for(proyecto.id, clip.id, "image")
    if image_row is None:
        raise HTTPException(409, f"El clip {clip_code} no tiene una imagen "
                            f"seleccionada todavía.")

    storyboard = Storyboard.model_validate(storyboard_row.payload)
    script = UGCScript.model_validate(script_row.payload)
    bible = (CharacterBible.model_validate(bible_row.payload)
            if bible_row is not None else None)

    cost_antes = gateway.total_cost()
    prompt: VideoPrompt = media_agents[8].run(
        gateway, (storyboard, script, clip_code, image_row.id, bible),
        project_code=code, feedback=body.feedback, triggered_by="api")
    costo_prompt = round(gateway.total_cost() - cost_antes, 6)
    ProjectRepository(session).add_cost(proyecto.id, costo_prompt)

    prompt_row = artifact_repo.create_version(
        proyecto.id, prompt, clip_id=clip.id,
        input_ref=image_row.source_artifact_id)

    blocking = prompt.blocking_issues()
    if blocking:
        return MediaGenerationOut(
            clip_code=clip_code, prompt_artifact=prompt_row,
            cost_prompt_usd=costo_prompt, cost_generation_usd=0.0,
            issues=[_issue_out(i) for i in prompt.approval_check()],
            message="El prompt de movimiento no superó las compuertas; no "
                    "se encoló nada.")

    artifact_repo.approve(prompt_row.id)

    image_asset = _service_asset_from_row(image_row, code, clip_code, kind="image")
    _hydrate_video_budget(video_svc, session, proyecto.id, clip.id)
    try:
        job = video_svc.submit(prompt, project_code=code,
                               image_asset=image_asset, seed=body.seed)
    except VideoBlocked as exc:
        raise HTTPException(422, str(exc)) from exc

    clip.status = "video_queued"

    return MediaGenerationOut(
        clip_code=clip_code, prompt_artifact=prompt_row,
        cost_prompt_usd=costo_prompt, cost_generation_usd=0.0,
        job_id=job.id,
        message=f"Video encolado, estado '{job.status.value}'. Sondear "
                f"GET .../clips/{clip_code}/video/jobs/{job.id}.")


@router.get("/clips/{clip_code}/video/jobs/{job_id}", response_model=JobOut)
def poll_clip_video(code: str, clip_code: str, job_id: str,
                    session: Session = Depends(get_session),
                    video_svc: VideoGenerationService = Depends(get_video_service)):
    proyecto = _project_or_404(code, session)
    clip = _clip_or_404(proyecto, clip_code, session)

    if job_id not in video_svc.queue.jobs:
        raise HTTPException(404, f"No existe el trabajo '{job_id}' (¿se "
                            f"reinició el servidor desde que se envió?).")

    job = video_svc.queue.poll(job_id)

    if job.status.value == "succeeded":
        asset_repo = AssetRepository(session)
        ya = asset_repo.for_clip(proyecto.id, clip.id, kind="video")
        if not any(a.storage_url == job.result_url for a in ya):
            fila = asset_repo.create(
                project_id=proyecto.id, clip_id=clip.id, kind="video",
                storage_url=job.result_url, provider=job.provider,
                cost_usd=job.cost_usd, duration_sec=job.duration_sec,
                is_selected=(len(ya) == 0))
            ProjectRepository(session).add_cost(proyecto.id, job.cost_usd)
            if fila.is_selected:
                clip.status = "video_generated"

    return JobOut(id=job.id, clip_id=clip_code, status=job.status.value,
                  progress=job.progress, result_url=job.result_url,
                  cost_usd=job.cost_usd, error_message=job.error_message)


# --------------------------------------------------------------------- voz


@router.post("/clips/{clip_code}/voice", response_model=MediaGenerationOut)
def generate_clip_voice(code: str, clip_code: str, body: GenerateVoiceIn,
                        session: Session = Depends(get_session),
                        gateway: AIGateway = Depends(get_gateway),
                        media_agents: dict = Depends(get_media_agents),
                        audio_svc: AudioGenerationService = Depends(get_audio_service)):
    proyecto = _project_or_404(code, session)
    clip = _clip_or_404(proyecto, clip_code, session)
    artifact_repo = ArtifactRepository(session)

    script_row = artifact_repo.latest_approved(proyecto.id, ArtifactType.UGC_SCRIPT)
    bible_row = artifact_repo.latest_approved(proyecto.id, ArtifactType.CHARACTER_BIBLE)
    if script_row is None or bible_row is None:
        raise HTTPException(409, "Falta el guion o la ficha de identidad "
                            "aprobados.")
    script = UGCScript.model_validate(script_row.payload)
    bible = CharacterBible.model_validate(bible_row.payload)
    sc_clip = next((c for c in script.clips if c.clip_id == clip_code), None)
    if sc_clip is None:
        raise HTTPException(404, f"El clip {clip_code} no existe en el "
                            f"guion aprobado.")

    voice_id = None
    if body.voice_name:
        curada = get_by_name(body.voice_name)
        if curada is None:
            raise HTTPException(422, f"No existe la voz '{body.voice_name}' "
                                f"en la biblioteca curada.")
        voice_id = curada.voice_id

    cost_antes = gateway.total_cost()
    direction = media_agents[9].run(
        gateway, (script, clip_code, bible), project_code=code,
        feedback=body.feedback, triggered_by="api")
    costo_prompt = round(gateway.total_cost() - cost_antes, 6)
    ProjectRepository(session).add_cost(proyecto.id, costo_prompt)

    if voice_id and direction.profile.voice_id is None:
        direction = direction.model_copy(
            update={"profile": direction.profile.model_copy(
                update={"voice_id": voice_id})})

    direction_row = artifact_repo.create_version(
        proyecto.id, direction, clip_id=clip.id)

    blocking = direction.blocking_issues()
    if blocking:
        return MediaGenerationOut(
            clip_code=clip_code, prompt_artifact=direction_row,
            cost_prompt_usd=costo_prompt, cost_generation_usd=0.0,
            issues=[_issue_out(i) for i in direction.approval_check()],
            message="La dirección de voz no superó las compuertas; no se "
                    "generó audio.")

    artifact_repo.approve(direction_row.id)

    _hydrate_audio_budget(audio_svc, session, proyecto.id, clip.id)
    try:
        asset = audio_svc.generate(direction, text=sc_clip.dialogue,
                                   project_code=code, voice_id=voice_id)
    except AudioBlocked as exc:
        raise HTTPException(422, str(exc)) from exc

    asset_repo = AssetRepository(session)
    fila = asset_repo.create(
        project_id=proyecto.id, clip_id=clip.id, kind="audio",
        storage_url=asset.storage_url, provider=asset.provider,
        cost_usd=asset.cost_usd, duration_sec=asset.duration_sec,
        source_artifact_id=direction_row.id, is_selected=True)
    ProjectRepository(session).add_cost(proyecto.id, asset.cost_usd)
    clip.status = "voice_generated"

    return MediaGenerationOut(
        clip_code=clip_code, prompt_artifact=direction_row,
        cost_prompt_usd=costo_prompt, cost_generation_usd=asset.cost_usd,
        assets=[fila], message="Voz generada.")


# ----------------------------------------------------------- avance de etapa


# Qué asset (kind, ya seleccionado) tiene que existir en TODOS los clips
# para poder avanzar la etapa del proyecto. IMAGE avanza a VIDEO cuando
# cada clip tiene su imagen elegida; VIDEO a VOICE cuando tiene video;
# VOICE a EDIT cuando tiene audio.
_ADVANCE_REQUIRES: dict[Stage, str] = {
    Stage.IMAGE: "image", Stage.VIDEO: "video", Stage.VOICE: "audio",
}


@router.post("/stages/advance", response_model=AdvanceStageOut)
def advance_media_stage(code: str, session: Session = Depends(get_session)):
    """
    Avanza `current_stage` de IMAGE→VIDEO, VIDEO→VOICE o VOICE→EDIT.

    A diferencia de `/stages/approve`, no aprueba un artefacto único de
    proyecto: comprueba que cada clip tenga seleccionado el asset que la
    etapa actual produce. Ningún gasto ocurre aquí — sólo lectura.
    """
    proyecto = _project_or_404(code, session)
    current = Stage(proyecto.current_stage)
    kind = _ADVANCE_REQUIRES.get(current)
    if kind is None:
        raise HTTPException(409, f"La etapa '{current.value}' no se avanza "
                            f"desde este endpoint.")

    clips = ClipRepository(session).for_project(proyecto.id)
    if not clips:
        raise HTTPException(409, "El proyecto no tiene clips todavía.")

    asset_repo = AssetRepository(session)
    faltan = [c.code for c in clips
             if asset_repo.selected_for(proyecto.id, c.id, kind) is None]
    if faltan:
        return AdvanceStageOut(
            stage=current.value, status="blocked", missing_clips=faltan,
            message=f"Faltan clips con {kind} seleccionado: "
                    f"{', '.join(faltan)}.")

    siguiente = StateMachine.next_stage(current)
    proyecto.current_stage = siguiente.value
    proyecto.stage_status = "pending"
    return AdvanceStageOut(
        stage=siguiente.value, status="approved",
        message=f"'{current.value}' completo en los {len(clips)} clips. "
                f"Avanzó a '{siguiente.value}'.")


# ------------------------------------------------------------------ helpers


def _project_or_404(code: str, session: Session) -> Project:
    proyecto = ProjectRepository(session).by_code(code)
    if proyecto is None:
        raise HTTPException(404, f"No existe el proyecto '{code}'.")
    return proyecto


def _clip_or_404(proyecto: Project, clip_code: str, session: Session) -> Clip:
    clip = ClipRepository(session).by_code(proyecto.id, clip_code)
    if clip is None:
        raise HTTPException(404, f"No existe el clip '{clip_code}' en este "
                            f"proyecto. Aprobar el storyboard lo crea "
                            f"automáticamente.")
    return clip


def _issue_out(issue) -> StageIssueOut:
    return StageIssueOut(code=issue.code, message=issue.message,
                         severity=issue.severity.value, field=issue.field)


def _service_asset_from_row(row, project_code: str, clip_code: str,
                            *, kind: str) -> ServiceAsset:
    """AssetRow (fila de base) → Asset Pydantic (lo que esperan los
    servicios de generación). Ambos representan lo mismo; el servicio no
    conoce la base de datos, así que aquí se traduce."""
    return ServiceAsset(
        id=row.id, project_code=project_code, clip_id=clip_code, kind=kind,
        version=row.version, storage_url=row.storage_url,
        provider=row.provider or "", cost_usd=row.cost_usd or 0.0,
        duration_sec=row.duration_sec, is_selected=row.is_selected)


def _hydrate_image_budget(svc: ImageGenerationService, session: Session,
                          project_id: str, clip_id: str | None) -> None:
    """
    Antes de generar, sincroniza los contadores en memoria del servicio
    con lo que la base dice que ya se gastó — necesario porque el
    servicio es un singleton de proceso (ver `deps.get_image_service`) y
    su presupuesto no debe depender de que nadie haya reiniciado el
    servidor desde la última generación.
    """
    repo = AssetRepository(session)
    proyecto = session.get(Project, project_id)
    svc.spent_by_project[proyecto.code] = repo.total_cost(project_id, "image")
    if clip_id is not None:
        clip = session.get(Clip, clip_id)
        svc.spent_by_clip[clip.code] = repo.total_cost(project_id, "image", clip_id)


def _hydrate_video_budget(svc: VideoGenerationService, session: Session,
                          project_id: str, clip_id: str) -> None:
    repo = AssetRepository(session)
    proyecto = session.get(Project, project_id)
    clip = session.get(Clip, clip_id)
    svc.spent_by_project[proyecto.code] = repo.total_cost(project_id, "video")
    svc.spent_by_clip[clip.code] = repo.total_cost(project_id, "video", clip_id)


def _hydrate_audio_budget(svc: AudioGenerationService, session: Session,
                          project_id: str, clip_id: str) -> None:
    repo = AssetRepository(session)
    proyecto = session.get(Project, project_id)
    clip = session.get(Clip, clip_id)
    svc.spent_by_project[proyecto.code] = repo.total_cost(project_id, "audio")
    svc.spent_by_clip[clip.code] = repo.total_cost(project_id, "audio", clip_id)
