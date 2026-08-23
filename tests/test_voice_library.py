"""Pruebas de la biblioteca de voces curadas."""

from __future__ import annotations

from app.services.voice_library import (
    TODAS_LAS_VOCES,
    VOCES_FEMENINAS,
    VOCES_MASCULINAS,
    VoiceGender,
    find_duplicate_ids,
    get_by_id,
    get_by_name,
    list_by_gender,
    usable_voices,
)


def test_hay_ocho_voces_curadas_en_total():
    assert len(TODAS_LAS_VOCES) == 8
    assert len(VOCES_FEMENINAS) == 4
    assert len(VOCES_MASCULINAS) == 4


def test_no_hay_ids_duplicados():
    """
    Daniela y Sandra compartían id por error en la lista original — el
    usuario confirmó que el id en cuestión era el de Sandra, y le asignó a
    Daniela el suyo propio. find_duplicate_ids() debe quedar en cero ahora.
    """
    assert find_duplicate_ids() == {}


def test_sandra_ya_esta_verificada_con_su_id_correcto():
    sandra = get_by_name("Sandra")
    assert sandra is not None
    assert sandra.verified
    assert sandra.voice_id == "rEVYTKPqwSMhytFPayIb"


def test_todas_las_voces_estan_verificadas():
    for nombre in ("Daniela", "Valeria", "Sandra", "Kate", "Juan", "Brian",
                  "Luis", "JC"):
        voz = get_by_name(nombre)
        assert voz is not None and voz.verified and voz.voice_id


def test_usable_voices_incluye_las_ocho():
    """Ya no hay ninguna voz pendiente de confirmar."""
    assert len(usable_voices()) == 8


def test_get_by_name_no_distingue_mayusculas():
    assert get_by_name("valeria") is get_by_name("Valeria")


def test_get_by_name_inexistente_devuelve_none():
    assert get_by_name("Nombre Que No Existe") is None


def test_get_by_id_encuentra_la_voz_correcta():
    voz = get_by_id("VvYiNBPylZtUh8Bf6u8l")
    assert voz is not None and voz.name == "Juan"


def test_list_by_gender_separa_correctamente():
    femeninas = list_by_gender(VoiceGender.FEMENINO)
    masculinas = list_by_gender(VoiceGender.MASCULINO)
    assert all(v.gender is VoiceGender.FEMENINO for v in femeninas)
    assert all(v.gender is VoiceGender.MASCULINO for v in masculinas)
    assert len(femeninas) + len(masculinas) == len(TODAS_LAS_VOCES)


def test_todas_las_voces_son_es_latam_neutro():
    """El pedido explícito: español latino, acento neutro, sin excepciones."""
    for v in TODAS_LAS_VOCES:
        assert v.language == "es-LATAM-neutro"
