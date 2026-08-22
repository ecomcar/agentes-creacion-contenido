"""
Pruebas de la fase 4: agentes 5-7, servicio de imagen y biblioteca de avatares.

Todo con proveedores falsos: sin red, sin claves, sin créditos.
"""

from __future__ import annotations

import json

import pytest

from app.agents import (
    IdentityArchitectAgent,
    ImagePromptAgent,
    VisualDirectorAgent,
    available_versions,
    load_prompt,
)
from app.contracts import CharacterBible, ImagePrompt, Storyboard, UGCScript
from app.gateway import AIGateway, BudgetExceeded, FakeProvider, Quality
from app.gateway.providers import (
    FakeImageProvider,
    HTTPImageProvider,
    image_price,
    unverified_image_providers,
)
from app.services import (
    Asset,
    AvatarLibrary,
    GenerationBlocked,
    ImageGenerationService,
)

# ----------------------------------------------------------- payloads

SCRIPT = {
    "artifact": "ugc_script", "created_by": "agent_04", "hook_id": "H02",
    "target_duration_sec": 30.0, "total_duration_sec": 30.0,
    "clips": [
        {"clip_id": "C01", "start": 0, "end": 4, "role": "hook",
         "dialogue": "Casi cancelo el cumpleaños"},
        {"clip_id": "C02", "start": 4, "end": 18, "role": "problema",
         "dialogue": "Llevaba semanas con listas"},
        {"clip_id": "C03", "start": 18, "end": 30, "role": "cta",
         "dialogue": "Escríbeles antes de volverte loca"},
    ],
    "cta": "Escríbenos por WhatsApp",
}

STORYBOARD = {
    "artifact": "storyboard", "created_by": "agent_05",
    "script_clip_ids": ["C01", "C02", "C03"],
    "clips": [
        {"clip_id": "C01", "shot_type": "selfie", "scenario": "sala de casa",
         "action_summary": "habla a cámara sosteniendo el teléfono",
         "product_visible": False},
        {"clip_id": "C02", "shot_type": "selfie", "scenario": "sala de casa",
         "action_summary": "señala unos papeles sobre la mesa",
         "product_visible": False},
        {"clip_id": "C03", "shot_type": "plano_general",
         "scenario": "salón decorado",
         "action_summary": "muestra el salón montado detrás de ella",
         "product_visible": True},
    ],
}

BIBLE = {
    "artifact": "character_bible", "created_by": "agent_06",
    "avatar_id": "AV-FEMALE-EC-001", "display_name": "Sofía — mamá joven",
    "physical": {"age_range": "31-34", "origin": "Ecuador",
                 "face": "ovalado, pómulos marcados, mentón suave",
                 "hair": "castaño oscuro, media melena hasta el hombro",
                 "skin": "oliva clara con textura visible", "build": "normal"},
    "personality": "habla rápido cuando se emociona, se ríe de sí misma",
    "speech_style": "conversacional, frases cortas, muletilla 'o sea'",
    "wardrobe_allowed": ["camiseta blanca", "jeans", "cárdigan gris"],
    "wardrobe_forbidden": ["branding visible", "ropa de pasarela"],
    "natural_imperfections": ["sonrisa asimétrica", "mechón que se sale",
                              "ojeras leves"],
}

PROMPT_OK = {
    "artifact": "image_prompt", "created_by": "agent_07", "clip_id": "C01",
    "avatar_id": "AV-FEMALE-EC-001", "template_code": "NB_SELFIE_UGC",
    "template_version": 3, "scene": "selfie",
    "prompt_text": ("Vertical smartphone selfie of the reference woman in her "
                    "living room, natural window light from the left, casual "
                    "framing"),
    "identity_reference_used": True,
    "imperfections_included": ["visible skin texture", "flyaway hair strand"],
    "negative_constraints": ["studio setup", "empty background"],
}

PROMPT_REDESCRIBE = {**PROMPT_OK, "identity_reference_used": False}
PROMPT_COMERCIAL = {
    **PROMPT_OK,
    "prompt_text": ("Beautiful latina woman with perfect skin, cinematic "
                    "lighting, professional model, 8k masterpiece"),
}


def _gw(responses):
    provider = FakeProvider(responses=[json.dumps(r) for r in responses])
    return AIGateway(provider=provider), provider


def _bible() -> CharacterBible:
    return CharacterBible.model_validate(BIBLE)


def _prompt(data=None) -> ImagePrompt:
    return ImagePrompt.model_validate(data or PROMPT_OK)


def _service(**kw) -> tuple[ImageGenerationService, FakeImageProvider]:
    p = FakeImageProvider()
    return ImageGenerationService(provider=p, **kw), p


# ------------------------------------------------------------ prompts


def test_los_prompts_5_6_7_existen():
    for n in (5, 6, 7):
        assert len(load_prompt(n)) > 200
        assert available_versions(n) == [1]


def test_el_prompt_del_arquitecto_prioriza_la_imperfeccion():
    p = load_prompt(6).lower()
    assert "menos sospechosamente perfecto" in p


def test_el_prompt_del_agente_7_prohibe_redescribir_al_personaje():
    p = load_prompt(7).lower()
    assert "ancla en la referencia" in p or "no redescribas" in p


def test_el_prompt_del_director_visual_defiende_la_continuidad():
    p = load_prompt(5).lower()
    assert "repite escenarios" in p


# ------------------------------------------------------------ agentes


def test_el_director_visual_fija_los_clips_del_guion():
    gw, provider = _gw([STORYBOARD])
    VisualDirectorAgent().run(gw, UGCScript.model_validate(SCRIPT))
    enviado = provider.calls[0].user
    assert "C01, C02, C03" in enviado


def test_el_arquitecto_recibe_los_escenarios_del_storyboard():
    """Necesita saber qué tendrá que habitar el avatar para el vestuario."""
    gw, provider = _gw([BIBLE])
    IdentityArchitectAgent().run(
        gw, (Storyboard.model_validate(STORYBOARD), "AV-FEMALE-EC-001",
             "Madre de 32 años en Guayaquil"))
    enviado = provider.calls[0].user
    assert "sala de casa" in enviado and "salón decorado" in enviado


def test_el_arquitecto_pide_calidad_alta():
    """La identidad se reutiliza en decenas de clips; un error se multiplica."""
    assert IdentityArchitectAgent.spec.quality is Quality.HIGH
    assert IdentityArchitectAgent.spec.reference_consistency_critical


def test_el_agente_7_falla_si_el_clip_no_existe():
    gw, _ = _gw([])
    with pytest.raises(ValueError, match="C09"):
        ImagePromptAgent().run(
            gw, (_bible(), Storyboard.model_validate(STORYBOARD), "C09"))


def test_el_agente_7_recibe_la_instruccion_de_anclar():
    gw, provider = _gw([PROMPT_OK])
    ImagePromptAgent().run(
        gw, (_bible(), Storyboard.model_validate(STORYBOARD), "C01"))
    enviado = provider.calls[0].user
    assert "ancla en ellas" in enviado
    assert "no la redescribas" in enviado


# ------------------------------------------------------- precios


def test_ningun_precio_de_imagen_esta_verificado():
    """
    No tenemos cifras confirmadas de proveedores de imagen. Se declara en
    vez de inventar una estimación que parezca precisa.
    """
    sin_verificar = unverified_image_providers()
    assert "nano_banana_pro" in sin_verificar
    assert image_price("nano_banana_pro").usd_per_image == 0.0
    assert "SIN VERIFICAR" in image_price("nano_banana_pro").note


def test_el_precio_se_puede_configurar_por_entorno(monkeypatch):
    monkeypatch.setenv("PRICE_IMAGE_NANO_BANANA_PRO", "0.04")
    from app.gateway.providers import image_provider
    image_provider._load_image_price_overrides()
    p = image_provider.image_price("nano_banana_pro")
    assert p.usd_per_image == 0.04 and p.verified


def test_proveedor_desconocido_no_inventa_precio():
    p = image_price("proveedor_inexistente")
    assert p.usd_per_image == 0.0 and "SIN PRECIO" in p.note


def test_el_proveedor_http_exige_clave(monkeypatch):
    monkeypatch.delenv("NANO_BANANA_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="NANO_BANANA_API_KEY"):
        HTTPImageProvider()


# ------------------------------------- servicio de generación


def test_genera_las_variantes_pedidas():
    svc, provider = _service()
    assets = svc.generate(_prompt(), project_code="UGC-0001", n_variants=3)
    assert len(assets) == 3
    assert all(isinstance(a, Asset) and a.clip_id == "C01" for a in assets)
    assert provider.calls[0].n_variants == 3


def test_ninguna_variante_nace_seleccionada():
    """La elección es del humano, no del sistema."""
    svc, _ = _service()
    assets = svc.generate(_prompt(), project_code="UGC-0001")
    assert not any(a.is_selected for a in assets)


def test_un_prompt_que_redescribe_al_personaje_no_llega_a_generar():
    """La compuerta corta antes de gastar créditos."""
    svc, provider = _service()
    with pytest.raises(GenerationBlocked) as exc:
        svc.generate(_prompt(PROMPT_REDESCRIBE), project_code="UGC-0001")
    assert "identity_not_anchored" in {i.code for i in exc.value.issues}
    assert provider.calls == []


def test_un_prompt_con_lenguaje_de_comercial_tampoco():
    svc, provider = _service()
    with pytest.raises(GenerationBlocked) as exc:
        svc.generate(_prompt(PROMPT_COMERCIAL), project_code="UGC-0001")
    assert "commercial_language" in {i.code for i in exc.value.issues}
    assert provider.calls == []


def test_el_tope_por_clip_corta_antes_de_generar(monkeypatch):
    monkeypatch.setenv("PRICE_IMAGE_FAKE_IMAGE", "0.10")
    from app.gateway.providers import image_provider
    image_provider._load_image_price_overrides()

    svc, provider = _service(max_cost_per_clip_usd=0.20)
    svc.generate(_prompt(), project_code="UGC-0001", n_variants=2)  # $0.20
    with pytest.raises(BudgetExceeded, match="C01"):
        svc.generate(_prompt(), project_code="UGC-0001", n_variants=2)
    assert len(provider.calls) == 1

    monkeypatch.delenv("PRICE_IMAGE_FAKE_IMAGE")
    image_provider.IMAGE_PRICES["fake_image"].usd_per_image = 0.0


def test_solo_una_variante_seleccionada_por_clip():
    """
    Equivalente en memoria del índice parcial único del esquema. Sin esto,
    el Editor puede ensamblar dos versiones del mismo clip.
    """
    svc, _ = _service()
    assets = svc.generate(_prompt(), project_code="UGC-0001", n_variants=3)

    svc.select(assets[0].id)
    svc.select(assets[2].id)

    seleccionadas = [a for a in svc.variants_for("UGC-0001", "C01")
                     if a.is_selected]
    assert len(seleccionadas) == 1
    assert seleccionadas[0].id == assets[2].id


def test_seleccionar_un_asset_inexistente_falla():
    svc, _ = _service()
    with pytest.raises(KeyError):
        svc.select("no-existe")


def test_las_versiones_de_asset_no_se_reutilizan():
    """Regenerar crea versiones nuevas; no sobrescribe las anteriores."""
    svc, _ = _service()
    v1 = svc.generate(_prompt(), project_code="UGC-0001", n_variants=2)
    v2 = svc.generate(_prompt(), project_code="UGC-0001", n_variants=2)
    versiones = [a.version for a in v1 + v2]
    assert len(set(versiones)) == 4


def test_cada_asset_sabe_que_prompt_lo_generó():
    svc, _ = _service()
    assets = svc.generate(_prompt(), project_code="UGC-0001")
    assert assets[0].source_prompt_id == "NB_SELFIE_UGC_V3"


def test_un_fallo_del_proveedor_se_propaga():
    svc = ImageGenerationService(provider=FakeImageProvider(fail_times=1))
    with pytest.raises(ConnectionError):
        svc.generate(_prompt(), project_code="UGC-0001")


# ------------------------------------------ biblioteca de avatares


def test_un_avatar_sin_referencias_no_esta_listo():
    """
    Generar clips antes de tener las referencias produce exactamente la
    deriva de rostro que todo el diseño evita.
    """
    lib = AvatarLibrary()
    lib.save(_bible())
    assert not lib.is_ready("AV-FEMALE-EC-001")
    assert len(lib.missing_references("AV-FEMALE-EC-001")) == 5


def test_el_avatar_queda_listo_con_los_cinco_angulos():
    lib = AvatarLibrary()
    bible = _bible()
    lib.save(bible)
    for angle in bible.reference_angles_needed:
        lib.add_reference(bible.avatar_id, angle, f"https://fake/{angle}.png")
    assert lib.is_ready(bible.avatar_id)
    assert len(lib.references(bible.avatar_id)) == 5


def test_el_avatar_se_reutiliza_entre_campanas():
    """La biblioteca vive fuera del proyecto: ése es el activo real."""
    lib = AvatarLibrary()
    lib.save(_bible())
    assert lib.get("AV-FEMALE-EC-001") is not None
    assert lib.get("AV-FEMALE-EC-002") is None
