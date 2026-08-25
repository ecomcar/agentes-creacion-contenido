"""Pruebas del repositorio de marcas."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import BrandRepository, ProjectRepository, create_all, engine_for, session_factory


@pytest.fixture
def session():
    engine = engine_for("sqlite://")
    create_all(engine)
    factory = session_factory(engine)
    s = factory()
    yield s
    s.close()


def test_crear_marca_con_brief_completo(session):
    repo = BrandRepository(session)
    marca = repo.create(
        name="Karol Salud y Cosmética",
        default_audience={"age_range": "20-45", "location": "Guayaquil",
                          "known_pain_points": ["comprar el tono equivocado"]},
        brand_voice="Cercana, de mujer a mujer",
        forbidden_claims=["cura", "elimina arrugas al instante"],
        competitors=[{"name": "Farmacias grandes",
                     "angle_observed": "precio, sin asesoría"}],
    )
    assert marca.name == "Karol Salud y Cosmética"
    assert marca.default_audience["location"] == "Guayaquil"
    assert marca.is_active is True


def test_nombre_de_marca_es_unico(session):
    repo = BrandRepository(session)
    repo.create(name="Karol Salud y Cosmética")
    session.flush()
    with pytest.raises(IntegrityError):
        repo.create(name="Karol Salud y Cosmética")
        session.flush()


def test_by_name_encuentra_la_marca(session):
    repo = BrandRepository(session)
    repo.create(name="Party Voom")
    encontrada = repo.by_name("Party Voom")
    assert encontrada is not None and encontrada.name == "Party Voom"


def test_by_name_inexistente_devuelve_none(session):
    assert BrandRepository(session).by_name("No existe") is None


def test_list_active_ordena_alfabeticamente(session):
    repo = BrandRepository(session)
    repo.create(name="Zeta Cosmetics")
    repo.create(name="Alfa Beauty")
    nombres = [m.name for m in repo.list_active()]
    assert nombres == ["Alfa Beauty", "Zeta Cosmetics"]


def test_marca_inactiva_no_aparece_en_list_active(session):
    repo = BrandRepository(session)
    marca = repo.create(name="Marca Vieja")
    marca.is_active = False
    session.flush()
    assert marca.name not in [m.name for m in repo.list_active()]


def test_update_solo_cambia_los_campos_dados(session):
    """
    Actualización parcial: afinar el brief campaña tras campaña sin tener
    que reenviar todo el objeto cada vez.
    """
    repo = BrandRepository(session)
    marca = repo.create(name="Karol", brand_voice="voz original",
                        forbidden_claims=["a"])
    actualizada = repo.update(marca.id, brand_voice="voz afinada")
    assert actualizada.brand_voice == "voz afinada"
    assert actualizada.forbidden_claims == ["a"]   # no se tocó


def test_update_marca_inexistente_lanza_keyerror(session):
    with pytest.raises(KeyError):
        BrandRepository(session).update("no-existe", brand_voice="x")


def test_campaigns_for_devuelve_el_historial(session):
    brand_repo = BrandRepository(session)
    project_repo = ProjectRepository(session)
    marca = brand_repo.create(name="Karol")

    project_repo.create(code="UGC-0001", brand_name="Karol",
                        product_name="Base", brand_id=marca.id)
    project_repo.create(code="UGC-0002", brand_name="Karol",
                        product_name="Labial", brand_id=marca.id)
    project_repo.create(code="UGC-0003", brand_name="Otra marca",
                        product_name="X")  # sin brand_id: no debe aparecer

    historial = brand_repo.campaigns_for(marca.id)
    codigos = {p.code for p in historial}
    assert codigos == {"UGC-0001", "UGC-0002"}


def test_campaigns_for_vacio_si_no_hay_campanas(session):
    marca = BrandRepository(session).create(name="Marca Nueva")
    assert BrandRepository(session).campaigns_for(marca.id) == []


def test_proyecto_sin_marca_sigue_siendo_valido(session):
    """brand_id es opcional a propósito: no romper proyectos sin marca."""
    proyecto = ProjectRepository(session).create(
        code="UGC-SOLO", brand_name="Texto libre", product_name="X")
    assert proyecto.brand_id is None
