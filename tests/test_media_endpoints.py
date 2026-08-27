"""
Pruebas de los endpoints nuevos: storyboard, identidad, imagen, video, voz.

Mismo principio que `test_api.py`: SQLite en memoria + `FakeProvider` para
el gateway de texto, más los proveedores falsos de imagen/video/voz
(`FakeImageProvider`, `FakeVideoProvider`, `FakeVoiceProvider`) para no
tocar fal.ai ni gastar un centavo.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_audio_service,
    get_gateway,
    get_image_service,
    get_session,
    get_video_service,
)
from app.api.main import app
from app.db import create_all, engine_for, session_factory
from app.gateway import AIGateway, FakeProvider
from app.gateway.providers.image_provider import FakeImageProvider
from app.gateway.providers.video_provider import FakeVideoProvider
from app.gateway.providers.voice_provider import FakeVoiceProvider
from app.services import AudioGenerationService, ImageGenerationService
from app.services.video_generation import VideoGenerationService
from app.services.job_queue import JobQueue

BRIEF = {
    "artifact": "research_brief", "created_by": "agent_01",
    "product": {"name": "Brillo Labial Diamante", "category": "cosmética",
                "core_benefit": "Brillo real sin pegajosidad"},
    "audience_signals": {"age_range": "20-40", "location": "Guayaquil",
                         "known_pain_points": ["labiales pegajosos"]},
    "competitors": [{"name": "X", "angle_observed": "precio bajo"}],
}
STRATEGY = {
    "artifact": "strategy", "created_by": "agent_02",
    "awareness_level": "problem_aware",
    "primary_pain": "Los labiales brillantes quedan pegajosos",
    "primary_desire": "Brillo cómodo todo el día",
    "objections": ["precio", "confianza"],
    "unique_mechanism": "Fórmula que brilla sin quedar pegajosa",
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
    total = 20.0
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


def _storyboard_payload(clip_ids):
    tipos = ["selfie", "medio", "detalle", "plano_general"]
    return {
        "artifact": "storyboard", "created_by": "agent_05",
        "script_clip_ids": clip_ids,
        "clips": [{"clip_id": cid, "shot_type": tipos[i % len(tipos)],
                  "scenario": f"escenario {i+1}",
                  "action_summary": f"acción del clip {cid} con detalle suficiente",
                  "product_visible": True}
                 for i, cid in enumerate(clip_ids)],
    }


def _bible_payload(avatar_id="AV-FEMALE-EC-001"):
    return {
        "artifact": "character_bible", "created_by": "agent_06",
        "avatar_id": avatar_id, "display_name": "Karol",
        "physical": {"age_range": "30-34", "origin": "Ecuador / Guayaquil",
                    "face": "ovalado, pómulos marcados",
                    "hair": "castaño oscuro, media melena",
                    "skin": "oliva clara, textura visible", "build": "normal"},
        "personality": "cercana, habla como recomendando a una amiga",
        "speech_style": "frases cortas, conversacional",
        "wardrobe_allowed": ["camiseta blanca"],
        "wardrobe_forbidden": ["branding visible"],
        "natural_imperfections": ["sonrisa ligeramente asimétrica",
                                  "mechón que se sale", "ojeras leves"],
    }


def _image_prompt_payload(clip_id, avatar_id="AV-FEMALE-EC-001"):
    return {
        "artifact": "image_prompt", "created_by": "agent_07",
        "clip_id": clip_id, "avatar_id": avatar_id,
        "template_code": "NB_SELFIE_UGC", "template_version": 1,
        "scene": "selfie",
        "prompt_text": ("The reference woman holding the product, vertical "
                       "smartphone selfie framing, natural indoor light, "
                       "casual unposed expression"),
        "identity_reference_used": True,
        "imperfections_included": ["visible skin texture", "flyaway hair"],
        "negative_constraints": ["studio lighting", "empty background"],
    }


def _video_prompt_payload(clip_id, image_asset_id):
    return {
        "artifact": "video_prompt", "created_by": "agent_08",
        "clip_id": clip_id, "image_asset_id": image_asset_id,
        "pattern_code": "KL_TALKING_SELFIE", "pattern_version": 1,
        "duration_sec": 5.0,
        "blocks": {
            "camera": "front smartphone camera, slight handheld movement",
            "subject_action": "holding product up, briefly looks away",
            "microgestures": "natural blinking, small eyebrow movement",
            "performance": "casual, unscripted feeling",
            "physics": "natural gravity on hair and clothing",
            "product_constraint": "product label facing camera",
            "negative_behavior": ("avoid perfect posture, continuous eye "
                                  "contact, exaggerated gestures, "
                                  "cinematic camera movement"),
        },
    }


def _voice_direction_payload(clip_id):
    return {
        "artifact": "voice_direction", "created_by": "agent_09",
        "clip_id": clip_id,
        "profile": {"language": "es-419", "accent": "latinoamericano-neutro",
                   "age_perception": "30-34", "pace": "medio_rapido",
                   "tone": "conversacional, cercana"},
        "pauses_before": ["labial"], "emphasis_words": [],
        "pacing_notes": ("Ritmo natural, pausa breve antes de la palabra "
                        "clave, sin entonación de anuncio."),
        "avoid": ["entonación de locutor publicitario"],
    }


@pytest.fixture
def client():
    """Cliente con SQLite en memoria y TODOS los proveedores falsos."""
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

    image_svc = ImageGenerationService(provider=FakeImageProvider())
    video_svc = VideoGenerationService(
        queue=JobQueue(provider=FakeVideoProvider(polls_until_done=1),
                      poll_interval_s=0))
    audio_svc = AudioGenerationService(provider=FakeVoiceProvider())

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_gateway] = _override_gateway
    app.dependency_overrides[get_image_service] = lambda: image_svc
    app.dependency_overrides[get_video_service] = lambda: video_svc
    app.dependency_overrides[get_audio_service] = lambda: audio_svc

    test_client = TestClient(app)
    test_client._respuestas = respuestas
    yield test_client

    app.dependency_overrides.clear()


def _programar(client, *payloads):
    client._respuestas.clear()
    client._respuestas.extend(payloads)


def _crear_proyecto_hasta_storyboard(client, code="UGC-TEST"):
    """Corre 1-4 con proveedores falsos hasta dejar el proyecto en
    'storyboard', devolviendo los clip_ids del guion aprobado."""
    client.post("/projects", json={"code": code, "brand_name": "Karol",
                                   "product_name": "Brillo Labial Diamante"})
    _programar(client, BRIEF)
    client.post(f"/projects/{code}/stages/research", json={
        "product_name": "Brillo Labial Diamante", "brand_name": "Karol",
        "description": "Brillo labial de larga duración sin pegajosidad"})

    _programar(client, STRATEGY)
    client.post(f"/projects/{code}/stages/strategy", json={})
    client.post(f"/projects/{code}/stages/approve")

    _programar(client, _hooks_payload())
    client.post(f"/projects/{code}/stages/hooks", json={"angle_id": "A01"})
    client.post(f"/projects/{code}/stages/approve")

    script = _script_payload()
    _programar(client, script)
    client.post(f"/projects/{code}/stages/script",
               json={"hook_id": "H01", "target_duration_sec": 20.0})
    client.post(f"/projects/{code}/stages/approve")

    proyecto = client.get(f"/projects/{code}").json()
    assert proyecto["current_stage"] == "storyboard"
    return [c["clip_id"] for c in script["clips"]]


def _hasta_imagen(client, code="UGC-TEST"):
    """Avanza storyboard → identidad → deja el proyecto listo para
    generar la referencia del avatar e imágenes de clip."""
    clip_ids = _crear_proyecto_hasta_storyboard(client, code)

    _programar(client, _storyboard_payload(clip_ids))
    r = client.post(f"/projects/{code}/stages/storyboard", json={})
    assert r.status_code == 200, r.json()
    assert r.json()["status"] == "pending_human_approval"
    r = client.post(f"/projects/{code}/stages/approve")
    assert r.status_code == 200, r.json()

    # aprobar el storyboard debe haber creado las filas de clips
    clips = client.get(f"/projects/{code}/clips").json()
    assert sorted(c["code"] for c in clips) == sorted(clip_ids)

    _programar(client, _bible_payload())
    r = client.post(f"/projects/{code}/stages/identity", json={
        "avatar_id": "AV-FEMALE-EC-001",
        "description": "asesora cercana, tono de amiga"})
    assert r.status_code == 200, r.json()
    assert r.json()["status"] == "approved"

    proyecto = client.get(f"/projects/{code}").json()
    assert proyecto["current_stage"] == "image"
    return clip_ids


# --------------------------------------------------------- storyboard/id


def test_storyboard_crea_clips_al_aprobar(client):
    clip_ids = _crear_proyecto_hasta_storyboard(client)
    _programar(client, _storyboard_payload(clip_ids))
    client.post("/projects/UGC-TEST/stages/storyboard", json={})
    client.post("/projects/UGC-TEST/stages/approve")

    clips = client.get("/projects/UGC-TEST/clips").json()
    assert len(clips) == len(clip_ids)


def test_identidad_auto_avanza_a_imagen(client):
    _hasta_imagen(client)   # las aserciones de avance viven adentro


# --------------------------------------------------------------- imagen


def test_referencia_de_avatar_se_genera_y_reutiliza(client):
    _hasta_imagen(client)
    r = client.post("/projects/UGC-TEST/avatar/reference", json={})
    assert r.status_code == 200, r.json()
    primera = r.json()
    assert primera["is_selected"] is True
    assert primera["kind"] == "image"

    # segunda llamada: reutiliza, no gasta de nuevo
    r2 = client.post("/projects/UGC-TEST/avatar/reference", json={})
    assert r2.json()["id"] == primera["id"]


def test_generar_imagen_de_clip_con_una_variante_autoselecciona(client):
    clip_ids = _hasta_imagen(client)
    client.post("/projects/UGC-TEST/avatar/reference", json={})

    _programar(client, _image_prompt_payload(clip_ids[0]))
    r = client.post(f"/projects/UGC-TEST/clips/{clip_ids[0]}/image",
                    json={"n_variants": 1})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert len(body["assets"]) == 1
    assert body["assets"][0]["is_selected"] is True
    assert body["cost_generation_usd"] >= 0


def test_generar_imagen_sin_referencia_da_409(client):
    _hasta_imagen(client)
    r = client.post("/projects/UGC-TEST/clips/C01/image", json={})
    assert r.status_code == 409


def test_generar_imagen_multiple_variantes_no_autoselecciona(client):
    clip_ids = _hasta_imagen(client)
    client.post("/projects/UGC-TEST/avatar/reference", json={})

    _programar(client, _image_prompt_payload(clip_ids[0]))
    r = client.post(f"/projects/UGC-TEST/clips/{clip_ids[0]}/image",
                    json={"n_variants": 3})
    body = r.json()
    assert len(body["assets"]) == 3
    assert all(a["is_selected"] is False for a in body["assets"])

    # elegir una variante a mano, vía el endpoint genérico de assets
    elegido = body["assets"][1]["id"]
    r2 = client.post(f"/assets/{elegido}/select")
    assert r2.json()["is_selected"] is True


# --------------------------------------------------------------- video


def _clip_con_imagen(client, clip_id="C01"):
    _hasta_imagen(client)
    client.post("/projects/UGC-TEST/avatar/reference", json={})
    _programar(client, _image_prompt_payload(clip_id))
    client.post(f"/projects/UGC-TEST/clips/{clip_id}/image",
               json={"n_variants": 1})


def test_generar_video_encola_y_se_puede_sondear_hasta_exito(client):
    _clip_con_imagen(client)
    image_row = client.get(
        "/projects/UGC-TEST/clips/C01/assets", params={"kind": "image"}
    ).json()[0]

    _programar(client, _video_prompt_payload("C01", image_row["id"]))
    r = client.post("/projects/UGC-TEST/clips/C01/video", json={})
    assert r.status_code == 200, r.json()
    job_id = r.json()["job_id"]
    assert job_id

    # primer sondeo: con polls_until_done=1, ya debería estar listo
    r2 = client.get(f"/projects/UGC-TEST/clips/C01/video/jobs/{job_id}")
    assert r2.status_code == 200, r2.json()
    assert r2.json()["status"] == "succeeded"

    assets = client.get(
        "/projects/UGC-TEST/clips/C01/assets", params={"kind": "video"}
    ).json()
    assert len(assets) == 1
    assert assets[0]["is_selected"] is True


def test_generar_video_sin_imagen_seleccionada_da_409(client):
    _hasta_imagen(client)
    r = client.post("/projects/UGC-TEST/clips/C01/video", json={})
    assert r.status_code == 409


# ----------------------------------------------------------------- voz


def test_generar_voz_de_clip(client):
    _hasta_imagen(client)
    _programar(client, _voice_direction_payload("C01"))
    r = client.post("/projects/UGC-TEST/clips/C01/voice",
                    json={"voice_name": "Daniela"})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert len(body["assets"]) == 1
    assert body["assets"][0]["kind"] == "audio"
    assert body["assets"][0]["is_selected"] is True


# -------------------------------------------------------- avance de etapa


def test_advance_bloquea_si_faltan_clips(client):
    clip_ids = _hasta_imagen(client)
    client.post("/projects/UGC-TEST/avatar/reference", json={})
    # sólo se genera imagen del primer clip
    _programar(client, _image_prompt_payload(clip_ids[0]))
    client.post(f"/projects/UGC-TEST/clips/{clip_ids[0]}/image",
               json={"n_variants": 1})

    r = client.post("/projects/UGC-TEST/stages/advance")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "blocked"
    assert len(body["missing_clips"]) == len(clip_ids) - 1


def test_advance_a_video_cuando_todos_los_clips_tienen_imagen(client):
    clip_ids = _hasta_imagen(client)
    client.post("/projects/UGC-TEST/avatar/reference", json={})
    for cid in clip_ids:
        _programar(client, _image_prompt_payload(cid))
        client.post(f"/projects/UGC-TEST/clips/{cid}/image",
                   json={"n_variants": 1})

    r = client.post("/projects/UGC-TEST/stages/advance")
    assert r.status_code == 200, r.json()
    assert r.json()["status"] == "approved"
    assert r.json()["stage"] == "video"

    proyecto = client.get("/projects/UGC-TEST").json()
    assert proyecto["current_stage"] == "video"
