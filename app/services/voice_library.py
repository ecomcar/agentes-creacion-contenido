"""
Biblioteca de voces curadas — español latinoamericano, acento neutro.

Igual que `AvatarLibrary` conserva la identidad visual de un avatar entre
campañas, esto conserva su identidad de voz: una vez que Karol habla con la
voz de Daniela, debería seguir siendo Daniela en la próxima campaña — no una
voz distinta elegida al azar cada vez.

IDs curados a mano en https://elevenlabs.io/voice-library, filtrados a
Español-Latinoamericano, Redes sociales, acento neutro, femenino/masculino
joven.
"""

from __future__ import annotations

from collections import defaultdict
from enum import Enum

from pydantic import BaseModel, ConfigDict


class VoiceGender(str, Enum):
    FEMENINO = "femenino"
    MASCULINO = "masculino"


class CuratedVoice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    voice_id: str
    name: str
    gender: VoiceGender
    age_range: str = "joven"
    style: str = "redes_sociales"
    language: str = "es-LATAM-neutro"
    verified: bool = True
    note: str = ""


VOCES_FEMENINAS: list[CuratedVoice] = [
    CuratedVoice(voice_id="ajOR9IDAaubDK5qtLUqQ", name="Daniela",
                gender=VoiceGender.FEMENINO),
    CuratedVoice(voice_id="22VndfJPBU7AZORAZZTT", name="Valeria",
                gender=VoiceGender.FEMENINO),
    # El ID que originalmente se había asignado por error a Daniela (ver
    # historial: la lista entregada tenía a Daniela y Sandra con el mismo
    # id) en realidad era el de Sandra. Confirmado por el usuario — ya no
    # es un duplicado, cada nombre tiene su id real y distinto.
    CuratedVoice(voice_id="rEVYTKPqwSMhytFPayIb", name="Sandra",
                gender=VoiceGender.FEMENINO),
    CuratedVoice(voice_id="qWWAqFomnJ99VwQLREfT", name="Kate",
                gender=VoiceGender.FEMENINO),
]

VOCES_MASCULINAS: list[CuratedVoice] = [
    CuratedVoice(voice_id="VvYiNBPylZtUh8Bf6u8l", name="Juan",
                gender=VoiceGender.MASCULINO),
    CuratedVoice(voice_id="U9TSK9KHMlMU2qkeXlQP", name="Brian",
                gender=VoiceGender.MASCULINO),
    CuratedVoice(voice_id="xXmo2BFwhd1KUag3K5Qz", name="Luis",
                gender=VoiceGender.MASCULINO),
    CuratedVoice(voice_id="4XUsiqPDK4UACIM2BILe", name="JC",
                gender=VoiceGender.MASCULINO),
]

TODAS_LAS_VOCES: list[CuratedVoice] = VOCES_FEMENINAS + VOCES_MASCULINAS


def find_duplicate_ids(voces: list[CuratedVoice] | None = None
                       ) -> dict[str, list[str]]:
    """
    IDs que aparecen repetidos bajo nombres distintos.

    Es el chequeo que hubiera cazado el caso Daniela/Sandra automáticamente.
    Ignora cadenas vacías: una voz marcada como pendiente de confirmar
    (voice_id="") no cuenta como duplicado de otra vacía.
    """
    voces = voces if voces is not None else TODAS_LAS_VOCES
    por_id: dict[str, list[str]] = defaultdict(list)
    for v in voces:
        if v.voice_id:
            por_id[v.voice_id].append(v.name)
    return {vid: nombres for vid, nombres in por_id.items() if len(nombres) > 1}


def get_by_name(name: str) -> CuratedVoice | None:
    return next((v for v in TODAS_LAS_VOCES
                if v.name.lower() == name.lower()), None)


def get_by_id(voice_id: str) -> CuratedVoice | None:
    return next((v for v in TODAS_LAS_VOCES if v.voice_id == voice_id), None)


def list_by_gender(gender: VoiceGender) -> list[CuratedVoice]:
    return [v for v in TODAS_LAS_VOCES if v.gender is gender]


def usable_voices() -> list[CuratedVoice]:
    """Sólo las verificadas y con id real — Sandra queda fuera hasta arreglarse."""
    return [v for v in TODAS_LAS_VOCES if v.verified and v.voice_id]
