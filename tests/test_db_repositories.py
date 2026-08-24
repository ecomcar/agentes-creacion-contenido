"""
Pruebas de AssetRepository, ClipRepository y ClipAuditRepository.

Corren sobre SQLite en memoria, igual que el resto de test_db.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.contracts import (
    AuditDecision,
    AuditIssue,
    AuditResult,
    AuditScores,
    IssueCategory,
)
from app.db import (
    AssetRepository,
    ClipAuditRepository,
    ClipRepository,
    ProjectRepository,
    create_all,
    engine_for,
    session_factory,
)


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
        code="UGC-0001", brand_name="Karol", product_name="Seytu")


# ------------------------------------------------------------- clips


def test_get_or_create_crea_una_sola_vez(session, project):
    repo = ClipRepository(session)
    c1 = repo.get_or_create(project.id, "C01", sequence_order=1)
    c2 = repo.get_or_create(project.id, "C01", sequence_order=1)
    assert c1.id == c2.id


def test_clips_de_proyectos_distintos_no_chocan(session, project):
    repo = ClipRepository(session)
    otro_proyecto = ProjectRepository(session).create(
        code="UGC-0002", brand_name="X", product_name="Y")
    c1 = repo.get_or_create(project.id, "C01")
    c2 = repo.get_or_create(otro_proyecto.id, "C01")
    assert c1.id != c2.id


def test_for_project_devuelve_en_orden(session, project):
    repo = ClipRepository(session)
    repo.get_or_create(project.id, "C02", sequence_order=2)
    repo.get_or_create(project.id, "C01", sequence_order=1)
    codigos = [c.code for c in repo.for_project(project.id)]
    assert codigos == ["C01", "C02"]


# ------------------------------------------------------------ assets


def test_create_asigna_version_incremental(session, project):
    clip_repo = ClipRepository(session)
    asset_repo = AssetRepository(session)
    clip = clip_repo.get_or_create(project.id, "C01")

    a1 = asset_repo.create(project_id=project.id, clip_id=clip.id, kind="image",
                           storage_url="a.png")
    a2 = asset_repo.create(project_id=project.id, clip_id=clip.id, kind="image",
                           storage_url="b.png")
    assert (a1.version, a2.version) == (1, 2)


def test_select_deselecciona_las_demas(session, project):
    clip_repo = ClipRepository(session)
    asset_repo = AssetRepository(session)
    clip = clip_repo.get_or_create(project.id, "C01")

    a1 = asset_repo.create(project_id=project.id, clip_id=clip.id, kind="image",
                           storage_url="a.png")
    a2 = asset_repo.create(project_id=project.id, clip_id=clip.id, kind="image",
                           storage_url="b.png")
    asset_repo.select(a1.id)
    asset_repo.select(a2.id)

    seleccionadas = [a for a in asset_repo.for_clip(project.id, clip.id, "image")
                     if a.is_selected]
    assert len(seleccionadas) == 1 and seleccionadas[0].id == a2.id


def test_create_con_is_selected_deselecciona_antes_de_insertar(session, project):
    """
    El caso de audio: nace seleccionado porque no hay variantes que elegir
    después. Si no se deselecciona lo anterior ANTES del flush, el índice
    único de la base rechaza la inserción.
    """
    clip_repo = ClipRepository(session)
    asset_repo = AssetRepository(session)
    clip = clip_repo.get_or_create(project.id, "C01")

    a1 = asset_repo.create(project_id=project.id, clip_id=clip.id, kind="audio",
                           storage_url="v1.mp3", is_selected=True)
    a2 = asset_repo.create(project_id=project.id, clip_id=clip.id, kind="audio",
                           storage_url="v2.mp3", is_selected=True)

    session.refresh(a1)
    assert not a1.is_selected and a2.is_selected


def test_imagen_y_video_seleccionados_no_chocan_entre_si(session, project):
    """El índice es por clip Y tipo: una imagen y un video pueden convivir."""
    clip_repo = ClipRepository(session)
    asset_repo = AssetRepository(session)
    clip = clip_repo.get_or_create(project.id, "C01")

    img = asset_repo.create(project_id=project.id, clip_id=clip.id, kind="image",
                            storage_url="a.png", is_selected=True)
    vid = asset_repo.create(project_id=project.id, clip_id=clip.id, kind="video",
                            storage_url="a.mp4", is_selected=True)
    assert img.is_selected and vid.is_selected


def test_selected_for_devuelve_none_sin_seleccion(session, project):
    clip_repo = ClipRepository(session)
    asset_repo = AssetRepository(session)
    clip = clip_repo.get_or_create(project.id, "C01")
    asset_repo.create(project_id=project.id, clip_id=clip.id, kind="image",
                      storage_url="a.png")
    assert asset_repo.selected_for(project.id, clip.id, "image") is None


def test_selected_for_encuentra_la_seleccionada(session, project):
    clip_repo = ClipRepository(session)
    asset_repo = AssetRepository(session)
    clip = clip_repo.get_or_create(project.id, "C01")
    a = asset_repo.create(project_id=project.id, clip_id=clip.id, kind="image",
                          storage_url="a.png")
    asset_repo.select(a.id)
    encontrado = asset_repo.selected_for(project.id, clip.id, "image")
    assert encontrado.id == a.id


# ------------------------------------------------------ clip_audits


def _audit(category=IssueCategory.MOTION, decision=AuditDecision.REGENERATE,
          realism=62, ad=78) -> AuditResult:
    scores = AuditScores(identity=90, anatomy=88, motion=41, physics=70,
                         lip_sync=90, voice=86, product=95, continuity=89,
                         ugc_realism=60, hook_visual=81, pacing=83,
                         commercial_clarity=80)
    issue = AuditIssue(category=category, description="gesto raro",
                       route_to_agent=8) if decision != AuditDecision.APPROVED else None
    return AuditResult(artifact="audit_result", created_by="agent_11",
                       clip_id="C01", scores=scores, realism_score=realism,
                       ad_score=ad, decision=decision, issue=issue)


def test_record_guarda_scores_y_ruta(session, project):
    clip_repo = ClipRepository(session)
    audit_repo = ClipAuditRepository(session)
    clip = clip_repo.get_or_create(project.id, "C01")

    row = audit_repo.record(clip.id, _audit())
    assert row.decision == "regenerate"
    assert row.issue_category == "motion"
    assert row.route_to_agent == 8
    assert row.scores["motion"] == 41


def test_un_rechazo_sin_ruta_es_rechazado_por_la_base(session, project):
    """
    La regla del documento maestro, verificada también desde el
    repositorio: no se puede guardar un rechazo sin responsable.
    """
    clip_repo = ClipRepository(session)
    clip = clip_repo.get_or_create(project.id, "C01")
    from app.db.models import ClipAudit
    session.add(ClipAudit(clip_id=clip.id, scores={}, realism_score=60,
                          ad_score=70, decision="regenerate",
                          route_to_agent=None))
    with pytest.raises(IntegrityError):
        session.flush()


def test_for_clip_ordena_por_ciclo(session, project):
    clip_repo = ClipRepository(session)
    audit_repo = ClipAuditRepository(session)
    clip = clip_repo.get_or_create(project.id, "C01")

    a1 = _audit()
    a1.cycle = 2
    a2 = _audit()
    a2.cycle = 1
    audit_repo.record(clip.id, a1)
    audit_repo.record(clip.id, a2)

    ciclos = [r.cycle for r in audit_repo.for_clip(clip.id)]
    assert ciclos == [1, 2]
