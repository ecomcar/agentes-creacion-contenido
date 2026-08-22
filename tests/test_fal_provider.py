"""
Pruebas del proveedor fal.ai.

Todo con `requests.post` interceptado — sin red, sin clave real, sin gasto.
Lo que se prueba es que el proveedor arma bien el payload y traduce
correctamente la respuesta, no que fal.ai funcione (eso sólo se confirma
contra la API real, ver `probar_fal.py`).
"""

from __future__ import annotations

import pytest

from app.gateway.providers.fal_provider import FalImageProvider, FalProviderError
from app.gateway.providers.image_provider import ImageRequest


class RespuestaFalsa:
    """Sustituto mínimo de requests.Response."""

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
    """Sustituto de requests.post que graba la llamada y devuelve lo pedido."""

    def __init__(self, respuesta: RespuestaFalsa):
        self.respuesta = respuesta
        self.llamadas: list[dict] = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.llamadas.append({"url": url, "headers": headers, "json": json,
                             "timeout": timeout})
        return self.respuesta


RESPUESTA_OK = {
    "images": [
        {"url": "https://fal.media/files/abc/img1.png", "width": 1080,
         "height": 1920},
        {"url": "https://fal.media/files/abc/img2.png", "width": 1080,
         "height": 1920},
    ],
    "seed": 42,
}


def _provider(monkeypatch, respuesta_json=None, status=200) -> tuple[FalImageProvider, PostFalso]:
    monkeypatch.setenv("FAL_KEY", "fal-clave-de-prueba")
    p = FalImageProvider()
    post_falso = PostFalso(RespuestaFalsa(
        respuesta_json if respuesta_json is not None else RESPUESTA_OK,
        status=status))
    monkeypatch.setattr("requests.post", post_falso)
    return p, post_falso


def _request(**over) -> ImageRequest:
    base = dict(prompt="the reference woman in her kitchen", n_variants=2)
    base.update(over)
    return ImageRequest(**base)


# ------------------------------------------------------------ setup


def test_exige_clave_fal(monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FAL_KEY"):
        FalImageProvider()


def test_usa_model_id_configurable_por_entorno(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "x")
    monkeypatch.setenv("FAL_MODEL_ID_IMAGE", "fal-ai/otro-modelo")
    p = FalImageProvider()
    assert p._endpoint == "https://fal.run/fal-ai/otro-modelo"


def test_model_id_por_defecto_es_nano_banana_pro(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "x")
    monkeypatch.delenv("FAL_MODEL_ID_IMAGE", raising=False)
    p = FalImageProvider()
    assert "nano-banana/pro" in p._endpoint


# ------------------------------------------------------- payload


def test_arma_el_payload_con_prompt_y_variantes(monkeypatch):
    p, post = _provider(monkeypatch)
    p.generate(_request(prompt="texto del prompt", n_variants=3))

    enviado = post.llamadas[0]["json"]
    assert enviado["prompt"] == "texto del prompt"
    assert enviado["num_images"] == 3


def test_la_clave_va_en_el_header_authorization(monkeypatch):
    p, post = _provider(monkeypatch)
    p.generate(_request())
    assert post.llamadas[0]["headers"]["Authorization"] == "Key fal-clave-de-prueba"


def test_las_referencias_anclan_la_identidad(monkeypatch):
    """
    Sin esto, cada generación redescribe al personaje en vez de anclarse en
    sus referencias — el fallo de deriva de rostro que el método evita.
    """
    p, post = _provider(monkeypatch)
    refs = ["https://ref/frontal.png", "https://ref/perfil.png"]
    p.generate(_request(reference_urls=refs))
    assert post.llamadas[0]["json"]["image_urls"] == refs


def test_sin_referencias_no_se_manda_el_campo(monkeypatch):
    p, post = _provider(monkeypatch)
    p.generate(_request(reference_urls=[]))
    assert "image_urls" not in post.llamadas[0]["json"]


def test_aspect_ratio_se_traduce_a_dimensiones(monkeypatch):
    p, post = _provider(monkeypatch)
    p.generate(_request(aspect_ratio="9:16"))
    tam = post.llamadas[0]["json"]["image_size"]
    assert tam == {"width": 1080, "height": 1920}


def test_seed_se_incluye_cuando_se_pide(monkeypatch):
    p, post = _provider(monkeypatch)
    p.generate(_request(seed=7))
    assert post.llamadas[0]["json"]["seed"] == 7


# --------------------------------------------------------- respuesta


def test_traduce_la_respuesta_a_generated_image(monkeypatch):
    p, _ = _provider(monkeypatch)
    resultado = p.generate(_request(n_variants=2))

    assert len(resultado.images) == 2
    assert resultado.images[0].url == "https://fal.media/files/abc/img1.png"
    assert resultado.images[0].provider == "fal_nano_banana_pro"
    assert resultado.provider == "fal_nano_banana_pro"


def test_las_semillas_de_las_variantes_son_consecutivas(monkeypatch):
    p, _ = _provider(monkeypatch)
    resultado = p.generate(_request(n_variants=2))
    assert resultado.images[1].seed == resultado.images[0].seed + 1


def test_sin_imagenes_en_la_respuesta_lanza_error_explicito(monkeypatch):
    p, _ = _provider(monkeypatch, respuesta_json={"images": []})
    with pytest.raises(FalProviderError, match="no devolvió imágenes"):
        p.generate(_request())


def test_error_http_se_traduce_a_falproviderrerror(monkeypatch):
    p, _ = _provider(monkeypatch, status=401)
    with pytest.raises(FalProviderError, match="Fallo llamando a fal.ai"):
        p.generate(_request())


def test_respuesta_no_json_da_error_legible(monkeypatch):
    p, post = _provider(monkeypatch)
    # Sustituir la respuesta por una que falla al parsear JSON.
    post.respuesta = RespuestaFalsa(None, status=200, texto="<html>error</html>")
    with pytest.raises(FalProviderError, match="no JSON"):
        p.generate(_request())


def test_el_coste_se_calcula_por_precio_configurado(monkeypatch):
    monkeypatch.setenv("PRICE_IMAGE_FAL_NANO_BANANA_PRO", "0.05")
    from app.gateway.providers import image_provider
    image_provider._load_image_price_overrides()

    p, _ = _provider(monkeypatch)
    resultado = p.generate(_request(n_variants=2))
    assert resultado.cost_usd == 0.10

    image_provider.IMAGE_PRICES["fal_nano_banana_pro"].usd_per_image = 0.0
    image_provider.IMAGE_PRICES["fal_nano_banana_pro"].verified = False
