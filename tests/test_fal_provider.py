"""
Pruebas del proveedor fal.ai.

Todo con `requests.post` interceptado — sin red, sin clave real, sin gasto.
Lo que se prueba es que el proveedor arma bien el payload y elige el
endpoint correcto según el esquema real de fal.ai, no que fal.ai funcione
(eso sólo se confirma contra la API real, ver `probar_fal.py`).
"""

from __future__ import annotations

import pytest

from app.gateway.providers.fal_provider import (
    MODEL_EDIT,
    MODEL_TEXT_TO_IMAGE,
    FalImageProvider,
    FalProviderError,
)
from app.gateway.providers.image_provider import ImageRequest


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
        self.llamadas.append({"url": url, "headers": headers, "json": json,
                             "timeout": timeout})
        return self.respuesta


RESPUESTA_OK = {
    "images": [
        {"url": "https://fal.media/files/abc/img1.png", "width": 1024,
         "height": 1820},
        {"url": "https://fal.media/files/abc/img2.png", "width": 1024,
         "height": 1820},
    ],
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


def test_model_id_por_defecto_es_el_verificado(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "x")
    monkeypatch.delenv("FAL_MODEL_ID_IMAGE", raising=False)
    p = FalImageProvider()
    assert p._model_t2i == "fal-ai/nano-banana-pro"
    assert p._model_edit == "fal-ai/nano-banana-pro/edit"


def test_model_id_configurable_por_entorno(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "x")
    monkeypatch.setenv("FAL_MODEL_ID_IMAGE", "fal-ai/otro-modelo")
    p = FalImageProvider()
    assert p._model_t2i == "fal-ai/otro-modelo"


# --------------------------------------------- selección de endpoint


def test_sin_referencias_usa_el_endpoint_de_texto_a_imagen(monkeypatch):
    p, post = _provider(monkeypatch)
    p.generate(_request(reference_urls=[]))
    assert post.llamadas[0]["url"] == f"https://fal.run/{MODEL_TEXT_TO_IMAGE}"


def test_con_referencias_usa_el_endpoint_de_edicion(monkeypatch):
    """
    Es el mecanismo real que ancla la identidad del avatar: sin esto, la
    referencia se ignoraría y cada clip reinventaría el rostro.
    """
    p, post = _provider(monkeypatch)
    p.generate(_request(reference_urls=["https://ref/frontal.png"]))
    assert post.llamadas[0]["url"] == f"https://fal.run/{MODEL_EDIT}"


def test_sin_referencias_no_se_manda_image_urls(monkeypatch):
    p, post = _provider(monkeypatch)
    p.generate(_request(reference_urls=[]))
    assert "image_urls" not in post.llamadas[0]["json"]


def test_con_referencias_se_mandan_las_urls_exactas(monkeypatch):
    p, post = _provider(monkeypatch)
    refs = ["https://ref/frontal.png", "https://ref/perfil.png"]
    p.generate(_request(reference_urls=refs))
    assert post.llamadas[0]["json"]["image_urls"] == refs


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


def test_aspect_ratio_se_manda_directo_sin_convertir(monkeypatch):
    """La API acepta '9:16' literal — no hace falta traducirlo a píxeles."""
    p, post = _provider(monkeypatch)
    p.generate(_request(aspect_ratio="9:16"))
    assert post.llamadas[0]["json"]["aspect_ratio"] == "9:16"


def test_aspect_ratio_invalido_cae_a_auto(monkeypatch):
    p, post = _provider(monkeypatch)
    p.generate(_request(aspect_ratio="7:3"))
    assert post.llamadas[0]["json"]["aspect_ratio"] == "auto"


def test_seed_se_incluye_cuando_se_pide(monkeypatch):
    p, post = _provider(monkeypatch)
    p.generate(_request(seed=7))
    assert post.llamadas[0]["json"]["seed"] == 7


def test_negative_prompt_se_pliega_en_el_prompt(monkeypatch):
    """
    Nano Banana Pro no tiene campo de prompt negativo separado (no es un
    modelo de difusión clásico); se incorpora como instrucción en el texto.
    """
    p, post = _provider(monkeypatch)
    p.generate(_request(negative_prompt="studio lighting, perfect skin"))
    enviado = post.llamadas[0]["json"]
    assert "negative_prompt" not in enviado
    assert "studio lighting, perfect skin" in enviado["prompt"]


def test_resolucion_por_defecto_es_1k(monkeypatch):
    p, post = _provider(monkeypatch)
    p.generate(_request())
    assert post.llamadas[0]["json"]["resolution"] == "1K"


# --------------------------------------------------------- respuesta


def test_traduce_la_respuesta_a_generated_image(monkeypatch):
    p, _ = _provider(monkeypatch)
    resultado = p.generate(_request(n_variants=2))

    assert len(resultado.images) == 2
    assert resultado.images[0].url == "https://fal.media/files/abc/img1.png"
    assert resultado.provider == "fal_nano_banana_pro"


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
    post.respuesta = RespuestaFalsa(None, status=200, texto="<html>error</html>")
    with pytest.raises(FalProviderError, match="no JSON"):
        p.generate(_request())


# ------------------------------------------------------------ coste


def test_el_coste_usa_el_precio_verificado(monkeypatch):
    p, _ = _provider(monkeypatch)
    resultado = p.generate(_request(n_variants=2))
    assert resultado.cost_usd == 0.30   # 2 imágenes × $0.15


def test_4k_duplica_el_precio(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "x")
    monkeypatch.setenv("FAL_IMAGE_RESOLUTION", "4K")
    p = FalImageProvider()
    post = PostFalso(RespuestaFalsa(RESPUESTA_OK))
    monkeypatch.setattr("requests.post", post)

    resultado = p.generate(_request(n_variants=1))
    # RESPUESTA_OK trae 2 imágenes (el conteo real lo decide la respuesta,
    # no lo pedido): 2 × $0.15 × 2 (por 4K) = $0.60.
    assert resultado.cost_usd == 0.60
    assert post.llamadas[0]["json"]["resolution"] == "4K"
