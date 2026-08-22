"""
Pruebas de persistencia.

Corren sobre SQLite en memoria: sin Docker, en milisegundos. Lo que se prueba
son las garantías del esquema y los repositorios, no el motor.

Lo que estas pruebas NO cubren y hay que verificar con Postgres real:
  - Los tipos JSONB (aquí son JSON normal).
  - Concurrencia real sobre la restricción única de `jobs`.
  - Los índices GIN.
Para eso está `python verificar_db.py` con el compose levantado.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.contracts import ArtifactStatus, ArtifactType, ResearchBrief, Strategy
from app.db import (
    ArtifactRepository,
    Asset,
    Clip,
    ClipAudit,
    JobRepository,
    ProjectRepository,
    RunRepository,
    create_all,
    engine_for,
    session_factory,
)
from app.gateway.types import RunRecord

BRIEF = {
    "artifact": "research_brief", "created_by": "agent_01",
    "product": {"name": "Party Voom", "category": "eventos",
                "core_benefit": "La fiesta queda montada sin organizar nada"},
    "audience_signals": {"age_range": "25-40", "location": "Guayaquil"},
}

STRATEGY = {
    "artifact": "strategy", "created_by": "agent_02",
    "awareness_level": "problem_aware",
    "primary_pain": "Organizar consume semanas",
    "primary_desire": "Que salga bonita sin esfuerzo",
    "objections": ["precio"], "unique_mechanism": "Montaje en tres horas",
    "angles": [
        {"angle_id": "A01", "name": "Sola", "premise": "Lo hace todo sola",
         "emotion": "alivio", "recommended_format": "ugc"},
        {"angle_id": "A02", "name": "Precio", "premise": "Improvisar cuesta más",
         "emotion": "sorpresa", "recommended_format": "ugc"},
        {"angle_id": "A03", "name": "Cambio", "premise": "Transformación visible",
         "emotion": "orgullo", "recommended_format": "reel"},
    ],
}


@pytest.fixture
def session():
    engine = engine_for("sqlite://")
    create_all(engine)
    factory = session_factory(engine)
    s = factory()
    yield s
    s.close()


@pytest.fixture
def project(session):
    return ProjectRepository(session).create(
        code="UGC-0001", brand_name="Party Voom", product_name="Decoración")


# ------------------------------------------------------ esquema


def test_el_esquema_tiene_las_catorce_tablas():
    from sqlalchemy import inspect
    engine = engine_for("sqlite://")
    create_all(engine)
    tablas = set(inspect(engine).get_table_names())
    assert "jobs" in tablas          # la que apareció en la fase 5
    assert len(tablas) == 14


def test_el_codigo_de_proyecto_es_unico(session, project):
    repo = ProjectRepository(session)
    session.flush()
    with pytest.raises(IntegrityError):
        repo.create(code="UGC-0001", brand_name="Otra", product_name="Otro")
        session.flush()


# ------------------------------------------- artefactos inmutables


def test_crear_version_no_sobrescribe_la_anterior(session, project):
    repo = ArtifactRepository(session)
    v1 = repo.create_version(project.id, ResearchBrief.model_validate(BRIEF))
    v2 = repo.create_version(project.id, ResearchBrief.model_validate(
        {**BRIEF, "product": {**BRIEF["product"],
                              "core_benefit": "Otro beneficio"}}))

    assert (v1.version, v2.version) == (1, 2)
    assert v1.payload["product"]["core_benefit"] != v2.payload["product"]["core_benefit"]
    assert len(repo.history(project.id, ArtifactType.RESEARCH_BRIEF)) == 2


def test_la_version_la_asigna_la_base_no_el_agente(session, project):
    """Dos agentes concurrentes no pueden reclamar el mismo número."""
    repo = ArtifactRepository(session)
    for esperado in (1, 2, 3):
        assert repo.create_version(
            project.id, ResearchBrief.model_validate(BRIEF)).version == esperado


def test_no_puede_haber_dos_versiones_iguales(session, project):
    """
    Esta prueba encontró un bug real: la restricción original incluía
    `clip_id`, que es NULL en los artefactos de proyecto, y SQL trata cada
    NULL como distinto. Tres 'strategy v1' convivían sin protesta.

    La restricción usa ahora `clip_key`, no nulo.
    """
    from app.db.models import Artifact
    session.add(Artifact(project_id=project.id, type="strategy", version=1,
                         payload={}, created_by="agent_02", clip_key=""))
    session.add(Artifact(project_id=project.id, type="strategy", version=1,
                         payload={}, created_by="agent_02", clip_key=""))
    with pytest.raises(IntegrityError):
        session.flush()


def test_latest_approved_ignora_los_borradores(session, project):
    repo = ArtifactRepository(session)
    v1 = repo.create_version(project.id, Strategy.model_validate(STRATEGY))
    repo.approve(v1.id)
    repo.create_version(project.id, Strategy.model_validate(STRATEGY))  # borrador

    vigente = repo.latest_approved(project.id, ArtifactType.STRATEGY)
    assert vigente.version == 1
    assert repo.latest(project.id, ArtifactType.STRATEGY).version == 2


def test_aprobar_una_version_supera_la_anterior(session, project):
    """
    Sin esto, rechazar la v2 dejaría dos aprobadas y `latest_approved`
    devolvería la que ordene el índice, no la vigente.
    """
    repo = ArtifactRepository(session)
    v1 = repo.create_version(project.id, Strategy.model_validate(STRATEGY))
    repo.approve(v1.id)
    v2 = repo.create_version(project.id, Strategy.model_validate(STRATEGY))
    repo.approve(v2.id)

    session.refresh(v1)
    assert v1.status == ArtifactStatus.SUPERSEDED.value
    assert repo.latest_approved(project.id, ArtifactType.STRATEGY).version == 2


def test_el_artefacto_vuelve_a_ser_un_contrato_validado(session, project):
    """Ida y vuelta: Pydantic → JSON en la base → Pydantic."""
    repo = ArtifactRepository(session)
    row = repo.create_version(project.id, Strategy.model_validate(STRATEGY))
    recuperado = repo.load(row)
    assert isinstance(recuperado, Strategy)
    assert len(recuperado.angles) == 3
    assert recuperado.can_be_approved()


def test_los_artefactos_por_clip_versionan_por_separado(session, project):
    from app.db.models import Artifact
    c1 = Clip(project_id=project.id, code="C01", sequence_order=1)
    c2 = Clip(project_id=project.id, code="C02", sequence_order=2)
    session.add_all([c1, c2])
    session.flush()

    for clip in (c1, c2):
        session.add(Artifact(project_id=project.id, type="image_prompt",
                             version=1, payload={}, created_by="agent_07",
                             clip_id=clip.id, clip_key=clip.id))
    session.flush()      # misma versión, clips distintos: permitido

    repo = ArtifactRepository(session)
    assert repo.latest(project.id, "image_prompt", c1.id).version == 1
    assert repo.latest(project.id, "image_prompt", c2.id).version == 1


# ------------------------------------------------- trazabilidad


def test_la_cadena_llega_hasta_el_brief_original(session, project):
    """
    Sigue `input_ref`, que apunta a la versión que realmente se usó — no a la
    última. Es la diferencia entre saber cómo se llegó al resultado y
    suponerlo.
    """
    repo = ArtifactRepository(session)
    brief = repo.create_version(project.id, ResearchBrief.model_validate(BRIEF))
    estrategia = repo.create_version(project.id, Strategy.model_validate(STRATEGY),
                                     input_ref=brief.id)

    cadena = repo.lineage(estrategia.id)
    assert [a.type for a in cadena] == ["strategy", "research_brief"]


def test_la_cadena_no_se_cuelga_con_referencias_circulares(session, project):
    repo = ArtifactRepository(session)
    a = repo.create_version(project.id, ResearchBrief.model_validate(BRIEF))
    a.input_ref = a.id            # no debería pasar, pero no puede colgar
    session.flush()
    assert len(repo.lineage(a.id)) == 1


# ------------------------------------------------------- assets


def test_solo_un_asset_seleccionado_por_clip(session, project):
    """
    La garantía del índice parcial, en la base y no sólo en memoria.
    Sin ella el Editor puede ensamblar dos versiones del mismo clip.
    """
    clip = Clip(project_id=project.id, code="C01", sequence_order=1)
    session.add(clip)
    session.flush()

    session.add(Asset(project_id=project.id, clip_id=clip.id, kind="image",
                      version=1, storage_url="a.png", is_selected=True))
    session.flush()
    session.add(Asset(project_id=project.id, clip_id=clip.id, kind="image",
                      version=2, storage_url="b.png", is_selected=True))
    with pytest.raises(IntegrityError):
        session.flush()


def test_varias_variantes_sin_seleccionar_conviven(session, project):
    clip = Clip(project_id=project.id, code="C01", sequence_order=1)
    session.add(clip)
    session.flush()
    for v in range(1, 4):
        session.add(Asset(project_id=project.id, clip_id=clip.id, kind="image",
                          version=v, storage_url=f"{v}.png"))
    session.flush()      # ninguna seleccionada: permitido


def test_imagen_y_video_pueden_estar_ambos_seleccionados(session, project):
    """El índice es por clip Y tipo: una imagen y un video, no dos imágenes."""
    clip = Clip(project_id=project.id, code="C01", sequence_order=1)
    session.add(clip)
    session.flush()
    session.add(Asset(project_id=project.id, clip_id=clip.id, kind="image",
                      version=1, storage_url="a.png", is_selected=True))
    session.add(Asset(project_id=project.id, clip_id=clip.id, kind="video",
                      version=1, storage_url="a.mp4", is_selected=True))
    session.flush()


# ------------------------------------------------- auditoría


def test_un_rechazo_sin_responsable_es_rechazado_por_la_base(session, project):
    """
    La regla del documento maestro codificada en el esquema, no confiada al
    código: un rechazo sin ruta obliga a regenerar el anuncio entero.
    """
    clip = Clip(project_id=project.id, code="C03", sequence_order=3)
    session.add(clip)
    session.flush()

    session.add(ClipAudit(clip_id=clip.id, scores={}, realism_score=62,
                          ad_score=70, decision="regenerate",
                          route_to_agent=None))
    with pytest.raises(IntegrityError):
        session.flush()


def test_una_aprobacion_no_necesita_ruta(session, project):
    clip = Clip(project_id=project.id, code="C01", sequence_order=1)
    session.add(clip)
    session.flush()
    session.add(ClipAudit(clip_id=clip.id, scores={}, realism_score=91,
                          ad_score=85, decision="approved"))
    session.flush()


# --------------------------------------------------- trazas


def test_las_trazas_del_gateway_se_persisten(session, project):
    repo = RunRepository(session)
    repo.record_all(project.id, [
        RunRecord(agent_number=2, agent_name="strategist", status="failed",
                  cost_usd=0.03, model_used="claude-opus-5"),
        RunRecord(agent_number=2, agent_name="strategist", attempt=2,
                  status="success", cost_usd=0.031, model_used="claude-opus-5"),
    ])
    assert len(repo.for_project(project.id)) == 2


def test_el_gasto_se_agrupa_por_agente(session, project):
    repo = RunRepository(session)
    repo.record_all(project.id, [
        RunRecord(agent_number=1, agent_name="researcher", status="success",
                  cost_usd=0.001),
        RunRecord(agent_number=2, agent_name="strategist", status="success",
                  cost_usd=0.030),
    ])
    por_agente = repo.cost_by_agent(project.id)
    assert por_agente[2] > por_agente[1] * 10


def test_el_gasto_desperdiciado_se_puede_separar(session, project):
    """
    Distingue "el sistema es caro" de "el sistema falla mucho". Son problemas
    distintos con soluciones distintas.
    """
    repo = RunRepository(session)
    repo.record_all(project.id, [
        RunRecord(agent_number=2, agent_name="strategist", status="failed",
                  cost_usd=0.03),
        RunRecord(agent_number=2, agent_name="strategist", status="success",
                  cost_usd=0.03),
    ])
    assert repo.wasted_cost(project.id) == 0.03


def test_el_coste_de_las_correcciones_se_puede_aislar(session, project):
    repo = RunRepository(session)
    repo.record_all(project.id, [
        RunRecord(agent_number=8, agent_name="video_director", status="success",
                  cost_usd=0.10, triggered_by="orchestrator"),
        RunRecord(agent_number=8, agent_name="video_director", status="success",
                  cost_usd=0.10, triggered_by="audit_route"),
    ])
    assert repo.correction_cost(project.id) == 0.10


# ---------------------------------------------------- trabajos


def test_la_idempotencia_la_garantiza_la_base(session, project):
    """
    En memoria bastaba un diccionario. Con dos procesos, no: la restricción
    única es lo que impide que ambos creen el mismo trabajo.
    """
    repo = JobRepository(session)
    repo.create(project_id=project.id, clip_id=None, idempotency_key="abc",
                provider="kling_3")
    with pytest.raises(IntegrityError):
        repo.create(project_id=project.id, clip_id=None,
                    idempotency_key="abc", provider="kling_3")


def test_los_trabajos_en_vuelo_se_recuperan_tras_un_reinicio(session, project):
    repo = JobRepository(session)
    j = repo.create(project_id=project.id, clip_id=None, idempotency_key="k1",
                    provider="kling_3")
    repo.mark_submitted(j.id, "kling_job_123")

    huerfanos = repo.orphans()
    assert len(huerfanos) == 1
    assert huerfanos[0].provider_job_id == "kling_job_123"


def test_un_trabajo_terminado_ya_no_es_huerfano(session, project):
    repo = JobRepository(session)
    j = repo.create(project_id=project.id, clip_id=None, idempotency_key="k1",
                    provider="kling_3")
    repo.mark_submitted(j.id, "kling_job_123")
    repo.finish(j.id, status="succeeded", result_url="x.mp4", cost_usd=0.30)
    assert repo.orphans() == []


def test_un_trabajo_sin_enviar_no_cuenta_como_huerfano(session, project):
    """Sin provider_job_id no hay nada que el proveedor esté cobrando."""
    JobRepository(session).create(project_id=project.id, clip_id=None,
                                  idempotency_key="k1", provider="kling_3")
    assert JobRepository(session).orphans() == []
