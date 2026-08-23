"""
Pruebas del servicio de generación de audio.

Todo con FakeVoiceProvider: sin red, sin claves, sin gasto. Mismo patrón que
image_generation y video_generation — compuertas y presupuesto se
comprueban antes de llamar al proveedor.
"""

from __future__ import annotations

import pytest

from app.contracts import VoiceDirection
from app.gateway.providers.voice_provider import FakeVoiceProvider, voice_price
from app.gateway.types import BudgetExceeded
from app.services import AudioBlocked, AudioGenerationService

DIRECTION_OK = {
    "artifact": "voice_direction", "created_by": "agent_09", "clip_id": "C01",
    "profile": {"language": "es-419", "accent": "latinoamericano-neutro",
               "age_perception": "27-34", "pace": "medio_rapido",
               "tone": "conversacional con leve entusiasmo",
               "voice_id": "ajOR9IDAaubDK5qtLUqQ"},
    "pauses_before": ["casi", "cumpleaños"],
    "emphasis_words": ["cancelo"],
    "pacing_notes": ("Arranca rápido, frena en 'casi', y el cierre lo dice "
                     "de lado como quien no quiere insistir."),
    "avoid": ["entonación de locutor publicitario"],
}

DIRECTION_SIN_VOZ = {**DIRECTION_OK, "profile": {**DIRECTION_OK["profile"],
                                                 "voice_id": None}}

DIRECTION_ROTA = {**DIRECTION_OK, "pacing_notes": "normal", "avoid": ["gritar"]}


def _direction(data=None) -> VoiceDirection:
    return VoiceDirection.model_validate(data or DIRECTION_OK)


def _service(**kw) -> tuple[AudioGenerationService, FakeVoiceProvider]:
    p = FakeVoiceProvider()
    return AudioGenerationService(provider=p, **kw), p


TEXTO = "Casi cancelo el cumpleaños de mi hija por esto"


# --------------------------------------------------------- compuertas


def test_una_direccion_invalida_no_llega_a_generar():
    """Sin restricción explícita contra el locutor y notas genéricas: se
    corta antes de gastar."""
    svc, provider = _service()
    with pytest.raises(AudioBlocked) as exc:
        svc.generate(_direction(DIRECTION_ROTA), text=TEXTO,
                    project_code="UGC-0001")
    codigos = {i.code for i in exc.value.issues}
    assert "generic_pacing" in codigos and "no_announcer_guard" in codigos
    assert provider.calls == []


def test_sin_voz_asignada_no_se_genera():
    svc, provider = _service()
    with pytest.raises(AudioBlocked, match="no tiene ninguna voz asignada"):
        svc.generate(_direction(DIRECTION_SIN_VOZ), text=TEXTO,
                    project_code="UGC-0001")
    assert provider.calls == []


def test_una_voz_pasada_explicita_sustituye_a_la_del_direction():
    svc, provider = _service()
    direction = _direction(DIRECTION_SIN_VOZ)   # sin voz en el profile
    svc.generate(direction, text=TEXTO, project_code="UGC-0001",
                voice_id="otra-voz-explicita")
    assert provider.calls[0].voice_id == "otra-voz-explicita"


# ------------------------------------------------------------- gasto


def test_el_tope_por_clip_corta_antes_de_generar(monkeypatch):
    from app.gateway.providers import voice_provider
    monkeypatch.setenv("PRICE_VOICE_FAKE_VOICE", "1.0")
    voice_provider._load_voice_price_overrides()

    svc, provider = _service(max_cost_per_clip_usd=0.01)
    with pytest.raises(BudgetExceeded, match="C01"):
        svc.generate(_direction(), text=TEXTO, project_code="UGC-0001")
    assert provider.calls == []

    monkeypatch.delenv("PRICE_VOICE_FAKE_VOICE")
    voice_provider.VOICE_PRICES["fake_voice"].usd_per_1k_chars = 0.0


def test_el_gasto_se_acumula_por_proyecto(monkeypatch):
    from app.gateway.providers import voice_provider
    monkeypatch.setenv("PRICE_VOICE_FAKE_VOICE", "0.10")
    voice_provider._load_voice_price_overrides()

    svc, _ = _service()
    svc.generate(_direction({**DIRECTION_OK, "clip_id": "C01"}), text=TEXTO,
                project_code="UGC-0001")
    svc.generate(_direction({**DIRECTION_OK, "clip_id": "C02"}), text=TEXTO,
                project_code="UGC-0001")
    assert svc.cost_report("UGC-0001")["project_usd"] > 0

    monkeypatch.delenv("PRICE_VOICE_FAKE_VOICE")
    voice_provider.VOICE_PRICES["fake_voice"].usd_per_1k_chars = 0.0


# -------------------------------------------------------- resultado


def test_genera_un_asset_de_audio():
    svc, _ = _service()
    asset = svc.generate(_direction(), text=TEXTO, project_code="UGC-0001")
    assert asset.kind == "audio" and asset.clip_id == "C01"


def test_el_asset_de_audio_nace_seleccionado():
    """
    A diferencia de imagen/video, la voz no tiene variantes que un humano
    elija después — se genera una y es la que se usa.
    """
    svc, _ = _service()
    asset = svc.generate(_direction(), text=TEXTO, project_code="UGC-0001")
    assert asset.is_selected is True


def test_regenerar_crea_version_nueva_no_sobrescribe():
    svc, _ = _service()
    a1 = svc.generate(_direction(), text=TEXTO, project_code="UGC-0001")
    a2 = svc.generate(_direction(), text=TEXTO, project_code="UGC-0001")
    assert (a1.version, a2.version) == (1, 2)


def test_for_clip_devuelve_el_ultimo_generado():
    svc, _ = _service()
    svc.generate(_direction(), text=TEXTO, project_code="UGC-0001")
    ultimo = svc.generate(_direction(), text=TEXTO, project_code="UGC-0001")
    assert svc.for_clip("UGC-0001", "C01").version == ultimo.version


def test_la_duracion_del_asset_viene_del_proveedor():
    svc, _ = _service()
    asset = svc.generate(_direction(), text=" ".join(["palabra"] * 25),
                        project_code="UGC-0001")
    assert asset.duration_sec == 10.0   # 25 palabras / 2.5 por segundo
