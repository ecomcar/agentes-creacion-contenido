"""
Pruebas del proveedor de video fal.ai (Kling v3 Standard).

Todo con `requests.post`/`requests.get` interceptados — sin red, sin clave
real, sin gasto. Lo que se prueba es que el proveedor arma bien las
llamadas de la cola y traduce sus estados, no que fal.ai funcione (eso se
confirma con `probar_fal_video.py`).
"""

from __future__ import annotations

import pytest

from app.gateway.providers.fal_video_provider import (
    MODEL_ID,
    FalVideoProvider,
    FalVideoProviderError,
    _redondear_duracion,
)
from app.gateway.providers.video_provider import VideoJobState, VideoRequest


class RespuestaFalsa:
    def __init__(self, json_data, status=200, texto=""):
        self._json = json_data
        self.status_code = status
        self.text = texto or str(json_data)

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._json is None:
            raise ValueError("no es JSON")
        return self._json


class SesionFalsa:
    """Sustituye requests.post y requests.get, grabando cada llamada."""

    def __init__(self):
        self.respuestas_post: list[RespuestaFalsa] = []
        self.respuestas_get: list[RespuestaFalsa] = []
        self.llamadas_post: list[dict] = []
        self.llamadas_get: list[dict] = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.llamadas_post.append({"url": url, "headers": headers, "json": json})
        return self.respuestas_post.pop(0)

    def get(self, url, headers=None, timeout=None):
        self.llamadas_get.append({"url": url, "headers": headers})
        return self.respuestas_get.pop(0)


def _provider(monkeypatch) -> tuple[FalVideoProvider, SesionFalsa]:
    monkeypatch.setenv("FAL_KEY", "fal-clave-de-prueba")
    p = FalVideoProvider()
    sesion = SesionFalsa()
    monkeypatch.setattr("requests.post", sesion.post)
    monkeypatch.setattr("requests.get", sesion.get)
    return p, sesion


def _request(**over) -> VideoRequest:
    base = dict(prompt="she talks to the camera", image_url="https://img/c01.png",
               duration_sec=5.0)
    base.update(over)
    return VideoRequest(**base)


# ------------------------------------------------------------ setup


def test_exige_clave_fal(monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FAL_KEY"):
        FalVideoProvider()


def test_model_id_por_defecto_es_kling_v3_standard(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "x")
    p = FalVideoProvider()
    assert p._model_id == MODEL_ID


# --------------------------------------------------- redondeo de duración


@pytest.mark.parametrize("pedido,esperado", [
    (3.0, 5), (5.0, 5), (6.0, 5), (7.4, 5),
    (7.6, 10), (9.0, 10), (10.0, 10), (14.0, 10),
])
def test_redondea_a_la_duracion_permitida_mas_cercana(pedido, esperado):
    assert _redondear_duracion(pedido) == esperado


# ------------------------------------------------------------ submit


def test_submit_envia_start_image_url_no_image_url(monkeypatch):
    """
    Campo específico de los endpoints v3 de Kling — el endpoint O3 usa
    'image_url' en cambio; usar el nombre equivocado no daría error de
    validación, simplemente el modelo ignoraría la imagen.
    """
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_post = [RespuestaFalsa({"request_id": "req_1"})]

    p.submit(_request(image_url="https://img/c01.png"))
    enviado = sesion.llamadas_post[0]["json"]
    assert enviado["start_image_url"] == "https://img/c01.png"
    assert "image_url" not in enviado


def test_submit_redondea_y_envia_como_texto(monkeypatch):
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_post = [RespuestaFalsa({"request_id": "req_1"})]

    p.submit(_request(duration_sec=6.5))
    assert sesion.llamadas_post[0]["json"]["duration"] == "5"


def test_submit_no_pide_audio_por_defecto(monkeypatch):
    """
    La voz del anuncio la genera el Agente 9 por separado; el audio nativo
    de Kling duplicaría el trabajo y subiría el precio un 50%.
    """
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_post = [RespuestaFalsa({"request_id": "req_1"})]
    p.submit(_request())
    assert sesion.llamadas_post[0]["json"]["generate_audio"] is False


def test_submit_devuelve_el_request_id(monkeypatch):
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_post = [RespuestaFalsa({"request_id": "abc-123"})]
    assert p.submit(_request()) == "abc-123"


def test_submit_sin_request_id_lanza_error_explicito(monkeypatch):
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_post = [RespuestaFalsa({"status": "error"})]
    with pytest.raises(FalVideoProviderError, match="no devolvió request_id"):
        p.submit(_request())


def test_submit_usa_el_endpoint_de_cola_no_el_sincrono(monkeypatch):
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_post = [RespuestaFalsa({"request_id": "req_1"})]
    p.submit(_request())
    assert sesion.llamadas_post[0]["url"].startswith("https://queue.fal.run/")


def test_submit_usa_el_model_id_completo_con_subpath(monkeypatch):
    """El envío sí necesita el path completo, incluido el subpath."""
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_post = [RespuestaFalsa({"request_id": "req_1"})]
    p.submit(_request())
    assert sesion.llamadas_post[0]["url"] == f"https://queue.fal.run/{MODEL_ID}"


def test_poll_usa_solo_el_namespace_base_no_el_subpath(monkeypatch):
    """
    El bug real que encontramos con una llamada de verdad: usar el model_id
    completo para consultar el estado da 405 Method Not Allowed, no 404 —
    la ruta existe pero no acepta ese verbo con ese subpath. fal.ai separa
    'dónde se envía' de 'dónde se consulta': el subpath sólo aplica al
    envío.
    """
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_get = [RespuestaFalsa({"status": "IN_QUEUE"})]
    p.poll("req_1")
    url_consultada = sesion.llamadas_get[0]["url"]
    assert url_consultada == (
        "https://queue.fal.run/fal-ai/kling-video/requests/req_1/status")
    assert "v3/standard/image-to-video" not in url_consultada


# ------------------------------------------------------------- poll


def test_poll_en_cola_devuelve_queued(monkeypatch):
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_get = [RespuestaFalsa({"status": "IN_QUEUE"})]
    estado = p.poll("req_1")
    assert estado.state is VideoJobState.QUEUED


def test_poll_en_progreso_devuelve_running(monkeypatch):
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_get = [RespuestaFalsa({"status": "IN_PROGRESS"})]
    estado = p.poll("req_1")
    assert estado.state is VideoJobState.RUNNING


def test_poll_completado_pide_el_resultado_y_devuelve_url(monkeypatch):
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_get = [
        RespuestaFalsa({"status": "COMPLETED"}),                     # /status
        RespuestaFalsa({"video": {"url": "https://fal.media/out.mp4"}}),  # resultado
    ]
    estado = p.poll("req_1")
    assert estado.state is VideoJobState.SUCCEEDED
    assert estado.video_url == "https://fal.media/out.mp4"


def test_poll_completado_calcula_el_costo_con_la_duracion_recordada(monkeypatch):
    """El costo depende de la duración pedida en submit(), no en poll()."""
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_post = [RespuestaFalsa({"request_id": "req_1"})]
    p.submit(_request(duration_sec=10.0))   # redondea a 10s

    sesion.respuestas_get = [
        RespuestaFalsa({"status": "COMPLETED"}),
        RespuestaFalsa({"video": {"url": "https://fal.media/out.mp4"}}),
    ]
    estado = p.poll("req_1")
    assert estado.cost_usd == round(10 * 0.084, 6)


def test_poll_estado_desconocido_se_marca_como_fallo(monkeypatch):
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_get = [RespuestaFalsa({"status": "ERROR"})]
    estado = p.poll("req_1")
    assert estado.state is VideoJobState.FAILED
    assert "ERROR" in estado.error_message


def test_poll_completado_sin_video_en_la_respuesta_es_fallo(monkeypatch):
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_get = [
        RespuestaFalsa({"status": "COMPLETED"}),
        RespuestaFalsa({"video": None}),
    ]
    estado = p.poll("req_1")
    assert estado.state is VideoJobState.FAILED


def test_error_http_al_encolar_se_traduce(monkeypatch):
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_post = [RespuestaFalsa({}, status=401)]
    with pytest.raises(FalVideoProviderError, match="Fallo al encolar"):
        p.submit(_request())


def test_error_http_al_sondear_se_traduce(monkeypatch):
    p, sesion = _provider(monkeypatch)
    sesion.respuestas_get = [RespuestaFalsa({}, status=500)]
    with pytest.raises(FalVideoProviderError, match="Fallo al consultar"):
        p.poll("req_1")
