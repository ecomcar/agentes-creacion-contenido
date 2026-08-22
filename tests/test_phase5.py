"""
Pruebas de la fase 5: agente 8, cola de trabajos asíncrona y servicio de video.

La cola simula latencia con un contador de sondeos, no con relojes: los tests
corren en milisegundos y son reproducibles.
"""

from __future__ import annotations

import json

import pytest

from app.agents import VideoDirectorAgent, load_prompt
from app.contracts import Storyboard, UGCScript, VideoPrompt
from app.gateway import AIGateway, BudgetExceeded, FakeProvider
from app.gateway.providers import (
    FakeVideoProvider,
    HTTPVideoProvider,
    VideoRequest,
    unverified_video_providers,
    video_price,
    video_provider,
)
from app.services import (
    Asset,
    JobQueue,
    JobStatus,
    VideoBlocked,
    VideoGenerationService,
    idempotency_key,
)

# ----------------------------------------------------------- payloads

SCRIPT = {
    "artifact": "ugc_script", "created_by": "agent_04", "hook_id": "H02",
    "target_duration_sec": 30.0, "total_duration_sec": 30.0,
    "clips": [
        {"clip_id": "C01", "start": 0, "end": 6, "role": "hook",
         "dialogue": "Casi cancelo el cumpleaños"},
        {"clip_id": "C02", "start": 6, "end": 30, "role": "cta",
         "dialogue": "Escríbeles"},   # 24s: por encima del máximo
    ],
    "cta": "Escríbenos por WhatsApp",
}

STORYBOARD = {
    "artifact": "storyboard", "created_by": "agent_05",
    "script_clip_ids": ["C01", "C02"],
    "clips": [
        {"clip_id": "C01", "shot_type": "selfie", "scenario": "sala",
         "action_summary": "habla a cámara", "product_visible": True},
        {"clip_id": "C02", "shot_type": "selfie", "scenario": "sala",
         "action_summary": "señala el salón", "product_visible": True},
    ],
}

BLOCKS = {
    "camera": "front smartphone camera, slight handheld movement",
    "subject_action": ("looks into the lens while speaking, briefly looks away "
                       "while thinking, then looks back"),
    "microgestures": "natural blinking, small eyebrow movement, weight shift",
    "performance": "casual, unscripted feeling",
    "physics": "natural gravity on hair and clothing",
    "product_constraint": "product stays in frame, label readable",
    "negative_behavior": ("avoid perfect posture, continuous eye contact, "
                          "exaggerated gestures, cinematic camera movement"),
}

PROMPT = {
    "artifact": "video_prompt", "created_by": "agent_08", "clip_id": "C01",
    "image_asset_id": "img_c01_v2", "pattern_code": "KL_TALKING_SELFIE",
    "pattern_version": 2, "duration_sec": 6.0, "blocks": BLOCKS,
}
PROMPT_SIN_BLOQUE = {**PROMPT, "blocks": {**BLOCKS, "microgestures": ""}}


def _image_asset(clip_id="C01", selected=True) -> Asset:
    return Asset(project_code="UGC-0001", clip_id=clip_id, kind="image",
                 version=2, storage_url="https://fake/img_c01_v2.png",
                 provider="fake_image", is_selected=selected)


def _prompt(data=None) -> VideoPrompt:
    return VideoPrompt.model_validate(data or PROMPT)


def _svc(polls=2, **kw):
    provider = FakeVideoProvider(polls_until_done=polls)
    queue = JobQueue(provider=provider)
    return VideoGenerationService(queue=queue, **kw), queue, provider


def _request(prompt="p", image="https://fake/i.png", dur=6.0) -> VideoRequest:
    return VideoRequest(prompt=prompt, image_url=image, duration_sec=dur)


# -------------------------------------------------------- agente 8


def test_el_prompt_del_agente_8_existe_y_exige_negativos():
    p = load_prompt(8).lower()
    assert "no son opcionales" in p
    assert "contacto visual continuo" in p


def test_el_agente_8_no_redescribe_al_personaje():
    gw = AIGateway(provider=FakeProvider(responses=[json.dumps(PROMPT)]))
    VideoDirectorAgent().run(gw, (Storyboard.model_validate(STORYBOARD),
                                  UGCScript.model_validate(SCRIPT),
                                  "C01", "img_c01_v2", None))
    enviado = gw.provider.calls[0].user
    assert "No redescribas al personaje" in enviado
    assert "img_c01_v2" in enviado


def test_un_clip_demasiado_largo_se_declara_no_se_corrige_en_silencio():
    """
    El clip C02 dura 24s. El agente debe declararlo para que el problema
    vuelva al guionista, que es quien puede partirlo.
    """
    gw = AIGateway(provider=FakeProvider(responses=[json.dumps(PROMPT)]))
    VideoDirectorAgent().run(gw, (Storyboard.model_validate(STORYBOARD),
                                  UGCScript.model_validate(SCRIPT),
                                  "C02", "img_c02_v1", None))
    enviado = gw.provider.calls[0].user
    assert "ATENCIÓN" in enviado and "errors" in enviado


def test_el_contrato_rechaza_duraciones_imposibles():
    with pytest.raises(Exception):
        VideoPrompt.model_validate({**PROMPT, "duration_sec": 40})


# ------------------------------------------------------- precios


def test_ningun_precio_de_video_esta_verificado():
    assert "kling_3" in unverified_video_providers()
    assert video_price("kling_3").usd_per_second == 0.0


def test_el_coste_de_video_va_por_segundo(monkeypatch):
    monkeypatch.setenv("PRICE_VIDEO_KLING_3", "0.05")
    video_provider._load_video_price_overrides()
    p = video_provider.video_price("kling_3")
    assert p.cost(6.0) == 0.30 and p.cost(12.0) == 0.60


def test_el_proveedor_de_video_exige_clave(monkeypatch):
    monkeypatch.delenv("KLING_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="KLING_API_KEY"):
        HTTPVideoProvider()


# ------------------------------------------- cola: idempotencia


def test_la_clave_de_idempotencia_deriva_del_contenido():
    a = idempotency_key("UGC-0001", "C01", "prompt", "img.png", 6.0)
    b = idempotency_key("UGC-0001", "C01", "prompt", "img.png", 6.0)
    assert a == b


def test_cambiar_el_prompt_produce_otro_trabajo():
    a = idempotency_key("UGC-0001", "C01", "prompt A", "img.png", 6.0)
    b = idempotency_key("UGC-0001", "C01", "prompt B", "img.png", 6.0)
    assert a != b


def test_variar_la_semilla_produce_un_trabajo_nuevo():
    """
    Pedir otra variante del mismo clip es el caso más normal cuando la
    primera no convence. Si la semilla no entrara en la clave, el sistema
    devolvería el trabajo anterior y no generaría nada.
    """
    _, queue, provider = _svc()
    j1 = queue.submit(project_code="UGC-0001", clip_id="C01",
                      request=VideoRequest(prompt="p", image_url="i.png",
                                           duration_sec=6.0, seed=1))
    j2 = queue.submit(project_code="UGC-0001", clip_id="C01",
                      request=VideoRequest(prompt="p", image_url="i.png",
                                           duration_sec=6.0, seed=2))
    assert j1.id != j2.id
    assert len(provider.submissions) == 2


def test_enviar_dos_veces_lo_mismo_no_cobra_dos_veces():
    """El usuario pulsa 'generar' dos veces; el proveedor recibe una."""
    _, queue, provider = _svc()
    j1 = queue.submit(project_code="UGC-0001", clip_id="C01", request=_request())
    j2 = queue.submit(project_code="UGC-0001", clip_id="C01", request=_request())
    assert j1.id == j2.id
    assert len(provider.submissions) == 1


def test_un_trabajo_fallido_si_puede_reintentarse():
    provider = FakeVideoProvider(fail_submit=True)
    queue = JobQueue(provider=provider)
    j1 = queue.submit(project_code="UGC-0001", clip_id="C01", request=_request())
    assert j1.status is JobStatus.FAILED

    queue.provider = FakeVideoProvider(polls_until_done=1)
    j2 = queue.submit(project_code="UGC-0001", clip_id="C01", request=_request())
    assert j2.id != j1.id and j2.status is JobStatus.SUBMITTED


# ------------------------------------------- cola: ciclo de vida


def test_el_envio_devuelve_enseguida_sin_esperar():
    _, queue, _ = _svc(polls=5)
    job = queue.submit(project_code="UGC-0001", clip_id="C01", request=_request())
    assert job.status is JobStatus.SUBMITTED
    assert job.result_url is None      # todavía no hay nada


def test_el_sondeo_reporta_progreso():
    _, queue, _ = _svc(polls=4)
    job = queue.submit(project_code="UGC-0001", clip_id="C01", request=_request())
    queue.poll(job.id)
    assert job.status is JobStatus.RUNNING
    assert 0 < job.progress < 1


def test_el_trabajo_termina_con_url():
    _, queue, _ = _svc(polls=2)
    job = queue.submit(project_code="UGC-0001", clip_id="C01", request=_request())
    terminado = queue.wait(job.id)
    assert terminado.status is JobStatus.SUCCEEDED
    assert terminado.result_url.endswith(".mp4")


def test_un_fallo_del_proveedor_termina_el_trabajo():
    queue = JobQueue(provider=FakeVideoProvider(polls_until_done=1, fail_job=True))
    job = queue.submit(project_code="UGC-0001", clip_id="C01", request=_request())
    terminado = queue.wait(job.id)
    assert terminado.status is JobStatus.FAILED
    assert terminado.error_message


def test_el_sondeo_infinito_tiene_tope():
    """Un trabajo que nunca termina no puede consumir sondeos para siempre."""
    queue = JobQueue(provider=FakeVideoProvider(polls_until_done=9999),
                     max_polls=5)
    job = queue.submit(project_code="UGC-0001", clip_id="C01", request=_request())
    terminado = queue.wait(job.id, max_polls=20)
    assert terminado.status is JobStatus.ABANDONED
    assert "pagar dos veces" in terminado.error_message


# ------------------------------------------- cola: recuperación


def test_un_trabajo_en_vuelo_se_detecta_como_huerfano():
    """
    Si el proceso muere aquí, el proveedor sigue generando y cobrando.
    Al arrancar hay que poder encontrarlo.
    """
    _, queue, _ = _svc(polls=5)
    queue.submit(project_code="UGC-0001", clip_id="C01", request=_request())
    huerfanos = queue.orphans()
    assert len(huerfanos) == 1
    assert huerfanos[0].provider_job_id is not None


def test_reconciliar_recoge_los_huerfanos():
    _, queue, _ = _svc(polls=1)
    queue.submit(project_code="UGC-0001", clip_id="C01", request=_request())
    recuperados = queue.reconcile()
    assert recuperados[0].status is JobStatus.SUCCEEDED
    assert queue.orphans() == []


def test_un_trabajo_terminado_ya_no_es_huerfano():
    _, queue, _ = _svc(polls=1)
    job = queue.submit(project_code="UGC-0001", clip_id="C01", request=_request())
    queue.wait(job.id)
    assert queue.orphans() == []


# --------------------------------------- servicio de video


def test_no_se_anima_un_clip_sin_imagen_seleccionada():
    """Animar una variante no elegida produce un clip que nadie aprobó."""
    svc, _, provider = _svc()
    with pytest.raises(VideoBlocked, match="no está seleccionada"):
        svc.submit(_prompt(), project_code="UGC-0001",
                   image_asset=_image_asset(selected=False))
    assert provider.submissions == []


def test_no_se_anima_con_la_imagen_de_otro_clip():
    svc, _, provider = _svc()
    with pytest.raises(VideoBlocked, match="C02"):
        svc.submit(_prompt(), project_code="UGC-0001",
                   image_asset=_image_asset(clip_id="C02"))
    assert provider.submissions == []


def test_un_prompt_con_bloque_vacio_no_se_encola():
    svc, _, provider = _svc()
    with pytest.raises(VideoBlocked) as exc:
        svc.submit(_prompt(PROMPT_SIN_BLOQUE), project_code="UGC-0001",
                   image_asset=_image_asset())
    assert "empty_block" in {i.code for i in exc.value.issues}
    assert provider.submissions == []


def test_el_tope_de_video_corta_antes_de_encolar(monkeypatch):
    monkeypatch.setenv("PRICE_VIDEO_FAKE_VIDEO", "0.10")
    video_provider._load_video_price_overrides()

    svc, _, provider = _svc(polls=1, max_cost_per_clip_usd=1.00)
    job = svc.submit(_prompt(), project_code="UGC-0001",
                     image_asset=_image_asset(), seed=1)
    svc.wait_and_collect(job)                       # 6s × $0.10 = $0.60

    with pytest.raises(BudgetExceeded, match="C01"):        # sumaría $1.20
        svc.submit(_prompt(), project_code="UGC-0001",
                   image_asset=_image_asset(), seed=2)
    assert len(provider.submissions) == 1

    monkeypatch.delenv("PRICE_VIDEO_FAKE_VIDEO")
    video_provider.VIDEO_PRICES["fake_video"].usd_per_second = 0.0


def test_recoger_produce_un_asset_de_video():
    svc, _, _ = _svc(polls=1)
    job = svc.submit(_prompt(), project_code="UGC-0001",
                     image_asset=_image_asset())
    asset = svc.wait_and_collect(job)
    assert asset is not None and asset.kind == "video"
    assert asset.clip_id == "C01"


def test_recoger_dos_veces_no_duplica_el_asset_ni_el_gasto():
    """La idempotencia también aplica a la recogida."""
    svc, queue, _ = _svc(polls=1)
    job = svc.submit(_prompt(), project_code="UGC-0001",
                     image_asset=_image_asset())
    terminado = queue.wait(job.id)
    a1 = svc.collect(terminado)
    a2 = svc.collect(terminado)
    assert a1.id == a2.id
    assert len(svc.variants_for("UGC-0001", "C01")) == 1


def test_recoger_un_trabajo_sin_terminar_devuelve_nada():
    svc, _, _ = _svc(polls=5)
    job = svc.submit(_prompt(), project_code="UGC-0001",
                     image_asset=_image_asset())
    assert svc.collect(job) is None


def test_solo_un_video_seleccionado_por_clip():
    svc, queue, _ = _svc(polls=1)
    assets = []
    for seed in (1, 2):
        job = svc.submit(_prompt(), project_code="UGC-0001",
                         image_asset=_image_asset(), seed=seed)
        assets.append(svc.wait_and_collect(job))

    assert assets[0].id != assets[1].id      # dos variantes reales
    svc.select(assets[0].id)
    svc.select(assets[1].id)
    seleccionados = [a for a in svc.variants_for("UGC-0001", "C01")
                     if a.is_selected]
    assert len(seleccionados) == 1
