"""
Pruebas del proveedor de voz fal.ai (ElevenLabs Multilingual v2).

Todo con `requests.post` interceptado — sin red, sin clave real, sin gasto.
"""

from __future__ import annotations

import pytest

from app.gateway.providers.fal_voice_provider import (
    MODEL_ID,
    VOZ_POR_DEFECTO,
    WORDS_PER_SECOND,
    FalVoiceProvider,
    FalVoiceProviderError,
)
from app.gateway.providers.voice_provider import VoiceRequest


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


class PostFalso:
    def __init__(self, respuesta: RespuestaFalsa):
        self.respuesta = respuesta
        self.llamadas: list[dict] = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.llamadas.append({"url": url, "headers": headers, "json": json})
        return self.respuesta


RESPUESTA_OK = {"audio": {"url": "https://fal.media/files/abc/voz.mp3"}}


def _provider(monkeypatch, respuesta_json=None, status=200) -> tuple[FalVoiceProvider, PostFalso]:
    monkeypatch.setenv("FAL_KEY", "fal-clave-de-prueba")
    p = FalVoiceProvider()
    post_falso = PostFalso(RespuestaFalsa(
        respuesta_json if respuesta_json is not None else RESPUESTA_OK,
        status=status))
    monkeypatch.setattr("requests.post", post_falso)
    return p, post_falso


def _request(**over) -> VoiceRequest:
    base = dict(text="Casi cancelo el cumpleaños de mi hija por esto",
               voice_id="")
    base.update(over)
    return VoiceRequest(**base)


# ------------------------------------------------------------ setup


def test_exige_clave_fal(monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FAL_KEY"):
        FalVoiceProvider()


def test_model_id_por_defecto_es_multilingual_v2(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "x")
    p = FalVoiceProvider()
    assert p._model_id == MODEL_ID
    assert "multilingual-v2" in MODEL_ID


def test_model_id_configurable_por_entorno(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "x")
    monkeypatch.setenv("FAL_MODEL_ID_VOICE", "fal-ai/elevenlabs/tts/turbo-v2.5")
    p = FalVoiceProvider()
    assert p._model_id == "fal-ai/elevenlabs/tts/turbo-v2.5"


# ------------------------------------------------------------ payload


def test_usa_el_endpoint_sincrono_no_la_cola(monkeypatch):
    """A diferencia del video, la voz no necesita submit/poll."""
    p, post = _provider(monkeypatch)
    p.synthesize(_request())
    assert post.llamadas[0]["url"] == f"https://fal.run/{MODEL_ID}"


def test_envia_el_texto_tal_cual(monkeypatch):
    p, post = _provider(monkeypatch)
    p.synthesize(_request(text="texto de prueba"))
    assert post.llamadas[0]["json"]["text"] == "texto de prueba"


def test_usa_la_voz_pedida_si_se_especifica(monkeypatch):
    p, post = _provider(monkeypatch)
    p.synthesize(_request(voice_id="Charlotte"))
    assert post.llamadas[0]["json"]["voice"] == "Charlotte"


def test_usa_la_voz_por_defecto_si_no_se_especifica(monkeypatch):
    p, post = _provider(monkeypatch)
    p.synthesize(_request(voice_id=""))
    assert post.llamadas[0]["json"]["voice"] == VOZ_POR_DEFECTO


def test_la_clave_va_en_el_header_authorization(monkeypatch):
    p, post = _provider(monkeypatch)
    p.synthesize(_request())
    assert post.llamadas[0]["headers"]["Authorization"] == "Key fal-clave-de-prueba"


# --------------------------------------------------------- respuesta


def test_traduce_la_respuesta_a_voice_response(monkeypatch):
    p, _ = _provider(monkeypatch)
    resultado = p.synthesize(_request())
    assert resultado.audio_url == "https://fal.media/files/abc/voz.mp3"
    assert resultado.provider == "fal_elevenlabs_multilingual_v2"


def test_sin_audio_en_la_respuesta_lanza_error_explicito(monkeypatch):
    p, _ = _provider(monkeypatch, respuesta_json={"audio": None})
    with pytest.raises(FalVoiceProviderError, match="no devolvió audio"):
        p.synthesize(_request())


def test_error_http_se_traduce(monkeypatch):
    p, _ = _provider(monkeypatch, status=401)
    with pytest.raises(FalVoiceProviderError, match="Fallo llamando a fal.ai"):
        p.synthesize(_request())


def test_respuesta_no_json_da_error_legible(monkeypatch):
    p, post = _provider(monkeypatch)
    post.respuesta = RespuestaFalsa(None, status=200, texto="<html>error</html>")
    with pytest.raises(FalVoiceProviderError, match="no JSON"):
        p.synthesize(_request())


# ------------------------------------------------ duración y coste


def test_la_duracion_se_estima_al_mismo_ritmo_que_el_guionista(monkeypatch):
    """
    2,5 palabras/segundo es la misma cifra que usa el prompt del Agente 4
    para dimensionar los clips — si difiriera, el guion y la voz real
    quedarían desincronizados por diseño.
    """
    p, _ = _provider(monkeypatch)
    texto = " ".join(["palabra"] * 25)   # 25 palabras
    resultado = p.synthesize(_request(text=texto, speed=1.0))
    assert resultado.duration_sec == round(25 / WORDS_PER_SECOND, 2)


def test_la_velocidad_ajusta_la_duracion_estimada(monkeypatch):
    p, _ = _provider(monkeypatch)
    texto = " ".join(["palabra"] * 25)
    normal = p.synthesize(_request(text=texto, speed=1.0)).duration_sec
    rapido = p.synthesize(_request(text=texto, speed=1.25)).duration_sec
    assert rapido < normal


def test_el_costo_usa_el_precio_verificado(monkeypatch):
    p, _ = _provider(monkeypatch)
    texto = "x" * 500  # 500 caracteres
    resultado = p.synthesize(_request(text=texto))
    assert resultado.cost_usd == 0.05   # 500/1000 × $0.10
