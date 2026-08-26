"""
Pruebas de la API HTTP.

Extremo a extremo, pero sin nada real: SQLite en memoria (vía dependency
override de `get_session`) y un `FakeProvider` en vez de Anthropic (vía
override de `get_gateway`). Ninguna prueba toca Postgres ni gasta un
centavo — mismo principio que el resto del sistema.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_gateway, get_session
from app.api.main import app
from app.db import create_all, engine_for, session_factory
from app.gateway import AIGateway, FakeProvider

BRIEF = {
    "artifact": "research_brief", "created_by": "agent_01",
    "product": {"name": "Party Voom", "category": "eventos",
                "core_benefit": "La fiesta queda montada sin organizar nada"},
    "audience_signals": {"age_range": "25-40", "location": "Guayaquil",
                         "known_pain_points": ["falta de tiempo"]},
    "competitors": [{"name": "X", "angle_observed": "precio bajo"}],
}
STRATEGY = {
    "artifact": "strategy", "created_by": "agent_02",
    "awareness_level": "problem_aware",
    "primary_pain": "Organizar consume semanas", "primary_desire": "Sin esfuerzo",
    "objections": ["precio", "confianza"],
    "unique_mechanism": "Funciona porque arma todo antes de llegar",
    "angles": [
        {"angle_id": "A01", "name": "a", "premise": "premisa uno distinta",
         "emotion": "alivio", "recommended_format": "ugc"},
        {"angle_id": "A02", "name": "b", "premise": "premisa dos distinta",
         "emotion": "sorpresa", "recommended_format": "ugc"},
        {"angle_id": "A03", "name": "c", "premise": "premisa tres distinta",
         "emotion": "orgullo", "recommended_format": "reel"},
    ],
}


def _hooks_payload():
    tipos = ["problema", "confesion", "curiosidad", "contrarian",
            "testimonial", "demostracion", "visual", "problema"]
    return {
        "artifact": "hooks", "created_by": "agent_03", "angle_id": "A01",
        "hooks": [{"hook_id": f"H{i+1:02d}", "type": t,
                   "text": f"Texto natural del hook número {i+1}",
                   "scores": {"curiosidad": 90 - i, "claridad": 85,
                             "pattern_interrupt": 80, "relevancia": 86,
                             "ugc_fit": 88, "visual_ease": 82}}
                  for i, t in enumerate(tipos)],
    }


def _script_payload(hook_id="H01"):
    roles = ["hook", "problema", "demostracion", "cta"]
    total = 35.0
    step = total / len(roles)
    return {
        "artifact": "ugc_script", "created_by": "agent_04", "hook_id": hook_id,
        "target_duration_sec": total, "total_duration_sec": total,
        "clips": [{"clip_id": f"C{i+1:02d}", "start": round(i * step, 2),
                  "end": round((i + 1) * step, 2), "role": r,
                  "dialogue": f"Diálogo natural {i+1}"}
                 for i, r in enumerate(roles)],
        "cta": "Escríbenos por WhatsApp",
    }


@pytest.fixture
def client(monkeypatch):
    """Cliente de pruebas con DB en SQLite y gateway con FakeProvider."""
    engine = engine_for("sqlite://")
    create_all(engine)
    factory = session_factory(engine)

    def _override_session():
        session = factory()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    respuestas = []

    def _override_gateway():
        return AIGateway(provider=FakeProvider(
            responses=[json.dumps(r) for r in respuestas]))

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_gateway] = _override_gateway

    test_client = TestClient(app)
    test_client._respuestas = respuestas   # para inyectar desde cada test
    yield test_client

    app.dependency_overrides.clear()


def _programar(client, *payloads):
    client._respuestas.clear()
    client._respuestas.extend(payloads)


# --------------------------------------------------------------- salud


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# ------------------------------------------------------------ proyectos


def test_crear_proyecto(client):
    r = client.post("/projects", json={
        "code": "UGC-0001", "brand_name": "Party Voom", "product_name": "Decoración"})
    assert r.status_code == 201
    assert r.json()["current_stage"] == "research"


def test_crear_proyecto_duplicado_falla(client):
    body = {"code": "UGC-0001", "brand_name": "X", "product_name": "Y"}
    client.post("/projects", json=body)
    r = client.post("/projects", json=body)
    assert r.status_code == 409


def test_obtener_proyecto_inexistente_da_404(client):
    assert client.get("/projects/NO-EXISTE").status_code == 404


def test_crear_y_listar_clips(client):
    client.post("/projects", json={"code": "UGC-0001", "brand_name": "X",
                                   "product_name": "Y"})
    r = client.post("/projects/UGC-0001/clips",
                    json={"code": "C01", "sequence_order": 1, "role": "hook"})
    assert r.status_code == 201
    assert client.get("/projects/UGC-0001/clips").json()[0]["code"] == "C01"


# --------------------------------------------------- etapa: investigación


def test_run_research_aprueba_automaticamente(client):
    client.post("/projects", json={"code": "UGC-0001", "brand_name": "Party Voom",
                                   "product_name": "Decoración"})
    _programar(client, BRIEF)
    r = client.post("/projects/UGC-0001/stages/research", json={
        "product_name": "Party Voom", "brand_name": "Party Voom",
        "description": "Decoración de fiestas infantiles a domicilio"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["artifact"]["type"] == "research_brief"

    proyecto = client.get("/projects/UGC-0001").json()
    assert proyecto["current_stage"] == "strategy"


def test_run_research_en_etapa_equivocada_da_409(client):
    client.post("/projects", json={"code": "UGC-0001", "brand_name": "X",
                                   "product_name": "Y"})
    _programar(client, BRIEF)
    client.post("/projects/UGC-0001/stages/research", json={
        "product_name": "X", "brand_name": "X", "description": "d" * 20})
    # Ya está en 'strategy'; investigar de nuevo debe fallar.
    r = client.post("/projects/UGC-0001/stages/research", json={
        "product_name": "X", "brand_name": "X", "description": "d" * 20})
    assert r.status_code == 409


# ------------------------------------------------------- etapa: estrategia


def _hasta_strategy(client, code="UGC-0001"):
    client.post("/projects", json={"code": code, "brand_name": "X",
                                   "product_name": "Y"})
    _programar(client, BRIEF)
    client.post(f"/projects/{code}/stages/research", json={
        "product_name": "X", "brand_name": "X", "description": "d" * 20})


def test_run_strategy_sin_brief_aprobado_da_409(client):
    client.post("/projects", json={"code": "UGC-0001", "brand_name": "X",
                                   "product_name": "Y"})
    r = client.post("/projects/UGC-0001/stages/strategy", json={})
    assert r.status_code == 409


def test_run_strategy_queda_pendiente_de_aprobacion(client):
    _hasta_strategy(client)
    _programar(client, STRATEGY)
    r = client.post("/projects/UGC-0001/stages/strategy", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "pending_human_approval"


def test_aprobar_estrategia_avanza_a_hooks(client):
    _hasta_strategy(client)
    _programar(client, STRATEGY)
    client.post("/projects/UGC-0001/stages/strategy", json={})

    r = client.post("/projects/UGC-0001/stages/approve")
    assert r.status_code == 200
    assert client.get("/projects/UGC-0001").json()["current_stage"] == "hooks"


def test_aprobar_sin_nada_pendiente_da_409(client):
    _hasta_strategy(client)
    r = client.post("/projects/UGC-0001/stages/approve")
    assert r.status_code == 409


# ------------------------------------------------------------ etapa: hooks


def _hasta_hooks(client, code="UGC-0001"):
    _hasta_strategy(client, code)
    _programar(client, STRATEGY)
    client.post(f"/projects/{code}/stages/strategy", json={})
    client.post(f"/projects/{code}/stages/approve")


def test_run_hooks_con_angulo_valido(client):
    _hasta_hooks(client)
    _programar(client, _hooks_payload())
    r = client.post("/projects/UGC-0001/stages/hooks", json={"angle_id": "A01"})
    assert r.status_code == 200
    assert r.json()["artifact"]["type"] == "hooks"


def test_run_hooks_con_angulo_inexistente_da_422(client):
    _hasta_hooks(client)
    r = client.post("/projects/UGC-0001/stages/hooks", json={"angle_id": "A09"})
    assert r.status_code == 422


def test_rechazar_y_reintentar_hooks(client):
    _hasta_hooks(client)
    base = _hooks_payload()
    hooks_flojos = {**base,
                    "hooks": [{**h, "scores": {k: 40 for k in h["scores"]}}
                             for h in base["hooks"]]}
    _programar(client, hooks_flojos)
    primero = client.post("/projects/UGC-0001/stages/hooks",
                          json={"angle_id": "A01"})
    assert primero.json()["status"] == "failed"

    r = client.post("/projects/UGC-0001/stages/reject")
    assert r.status_code == 200

    _programar(client, _hooks_payload())
    segundo = client.post("/projects/UGC-0001/stages/hooks",
                          json={"angle_id": "A01", "feedback": "mejora los scores"})
    assert segundo.json()["status"] == "pending_human_approval"


# ------------------------------------------------------------ etapa: guion


def _hasta_script(client, code="UGC-0001"):
    _hasta_hooks(client, code)
    _programar(client, _hooks_payload())
    client.post(f"/projects/{code}/stages/hooks", json={"angle_id": "A01"})
    client.post(f"/projects/{code}/stages/approve")


def test_run_script_con_hook_valido(client):
    _hasta_script(client)
    _programar(client, _script_payload(hook_id="H01"))
    r = client.post("/projects/UGC-0001/stages/script",
                    json={"hook_id": "H01", "target_duration_sec": 35.0})
    assert r.status_code == 200
    assert r.json()["artifact"]["type"] == "ugc_script"


def test_run_script_con_hook_inexistente_da_422(client):
    _hasta_script(client)
    r = client.post("/projects/UGC-0001/stages/script", json={"hook_id": "H99"})
    assert r.status_code == 422


def test_pipeline_completo_hasta_guion(client):
    """El recorrido completo: investigación → estrategia → hooks → guion."""
    _hasta_script(client)
    _programar(client, _script_payload(hook_id="H01"))
    r = client.post("/projects/UGC-0001/stages/script",
                    json={"hook_id": "H01"})
    assert r.json()["status"] == "pending_human_approval"

    aprobar = client.post("/projects/UGC-0001/stages/approve")
    assert aprobar.status_code == 200

    proyecto = client.get("/projects/UGC-0001").json()
    assert proyecto["current_stage"] == "storyboard"
    assert proyecto["total_cost_usd"] > 0


# ----------------------------------------------------------- artefactos


def test_listar_artefactos_de_un_proyecto(client):
    _hasta_strategy(client)
    r = client.get("/projects/UGC-0001/artifacts")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_obtener_artefacto_inexistente_da_404(client):
    assert client.get("/artifacts/no-existe").status_code == 404


def test_aprobar_artefacto_directo(client):
    _hasta_strategy(client)
    fila = client.get("/projects/UGC-0001/artifacts").json()[0]
    r = client.post(f"/artifacts/{fila['id']}/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


# ---------------------------------------------------------------- assets


def test_listar_assets_de_un_clip_vacio(client):
    _hasta_strategy(client)
    client.post("/projects/UGC-0001/clips", json={"code": "C01"})
    r = client.get("/projects/UGC-0001/clips/C01/assets")
    assert r.status_code == 200
    assert r.json() == []


def test_seleccionar_asset_inexistente_da_404(client):
    assert client.post("/assets/no-existe/select").status_code == 404


# ------------------------------------------------------------- marcas


def test_crear_marca(client):
    r = client.post("/brands", json={
        "name": "Karol Salud y Cosmética",
        "default_audience": {"age_range": "20-45", "location": "Guayaquil"},
        "brand_voice": "Cercana, de mujer a mujer",
        "forbidden_claims": ["cura"],
    })
    assert r.status_code == 201
    assert r.json()["name"] == "Karol Salud y Cosmética"


def test_crear_marca_duplicada_falla(client):
    body = {"name": "Party Voom"}
    client.post("/brands", json=body)
    r = client.post("/brands", json=body)
    assert r.status_code == 409


def test_listar_marcas(client):
    client.post("/brands", json={"name": "Alfa"})
    client.post("/brands", json={"name": "Beta"})
    r = client.get("/brands")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_obtener_marca_inexistente_da_404(client):
    assert client.get("/brands/no-existe").status_code == 404


def test_actualizar_marca_parcialmente(client):
    marca = client.post("/brands", json={
        "name": "Karol", "brand_voice": "voz original"}).json()
    r = client.patch(f"/brands/{marca['id']}",
                     json={"brand_voice": "voz afinada"})
    assert r.status_code == 200
    assert r.json()["brand_voice"] == "voz afinada"


def test_crear_proyecto_con_marca_valida(client):
    marca = client.post("/brands", json={"name": "Karol"}).json()
    r = client.post("/projects", json={
        "code": "UGC-0001", "brand_name": "Karol", "product_name": "Seytu",
        "brand_id": marca["id"]})
    assert r.status_code == 201
    assert r.json()["brand_id"] == marca["id"]


def test_crear_proyecto_con_marca_inexistente_da_422(client):
    r = client.post("/projects", json={
        "code": "UGC-0001", "brand_name": "X", "product_name": "Y",
        "brand_id": "no-existe"})
    assert r.status_code == 422


def test_proyecto_sin_marca_sigue_funcionando(client):
    r = client.post("/projects", json={
        "code": "UGC-0001", "brand_name": "Texto libre", "product_name": "Y"})
    assert r.status_code == 201
    assert r.json()["brand_id"] is None


def test_historial_de_campanas_de_una_marca(client):
    marca = client.post("/brands", json={"name": "Karol"}).json()
    client.post("/projects", json={"code": "UGC-0001", "brand_name": "Karol",
                                   "product_name": "Base", "brand_id": marca["id"]})
    client.post("/projects", json={"code": "UGC-0002", "brand_name": "Karol",
                                   "product_name": "Labial", "brand_id": marca["id"]})
    client.post("/projects", json={"code": "UGC-0003", "brand_name": "Otra",
                                   "product_name": "Z"})

    r = client.get(f"/brands/{marca['id']}/projects")
    assert r.status_code == 200
    codigos = {p["code"] for p in r.json()}
    assert codigos == {"UGC-0001", "UGC-0002"}


def test_historial_de_marca_inexistente_da_404(client):
    assert client.get("/brands/no-existe/projects").status_code == 404


# --------------------------------------------------- listar proyectos


def test_listar_proyectos_vacio(client):
    assert client.get("/projects").json() == []


def test_listar_proyectos_los_mas_recientes_primero(client):
    client.post("/projects", json={"code": "UGC-0001", "brand_name": "A",
                                   "product_name": "X"})
    client.post("/projects", json={"code": "UGC-0002", "brand_name": "B",
                                   "product_name": "Y"})
    codigos = [p["code"] for p in client.get("/projects").json()]
    assert codigos == ["UGC-0002", "UGC-0001"]


def test_listar_proyectos_incluye_los_de_cualquier_marca_o_sin_marca(client):
    marca = client.post("/brands", json={"name": "Karol"}).json()
    client.post("/projects", json={"code": "UGC-0001", "brand_name": "Karol",
                                   "product_name": "X", "brand_id": marca["id"]})
    client.post("/projects", json={"code": "UGC-0002", "brand_name": "Suelto",
                                   "product_name": "Y"})
    codigos = {p["code"] for p in client.get("/projects").json()}
    assert codigos == {"UGC-0001", "UGC-0002"}
