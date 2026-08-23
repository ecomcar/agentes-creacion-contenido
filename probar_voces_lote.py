"""
Prueba en lote las voces curadas — español latino, acento neutro.

    python probar_voces_lote.py                    # las 7 voces usables
    python probar_voces_lote.py --genero femenino
    python probar_voces_lote.py --genero masculino
    python probar_voces_lote.py --nombre Daniela

Genera una línea corta idéntica para cada voz, en español latinoamericano
neutro, para poder compararlas de oído una tras otra. Barato: ~$0.006 por
voz con la línea de prueba por defecto.
"""

from __future__ import annotations

import argparse
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if not os.getenv("FAL_KEY"):
    sys.exit(
        "Falta FAL_KEY.\n\n"
        "  1. Crea una cuenta en https://fal.ai\n"
        "  2. Genera una clave en https://fal.ai/dashboard/keys\n"
        "  3. Agrégala a .env:  FAL_KEY=tu-clave-aqui\n"
    )

from app.gateway.providers.fal_voice_provider import (
    FalVoiceProvider,
    FalVoiceProviderError,
)
from app.gateway.providers.voice_provider import VoiceRequest
from app.services.voice_library import (
    VoiceGender,
    find_duplicate_ids,
    get_by_name,
    list_by_gender,
    usable_voices,
)

LINE = "─" * 66

# Español latinoamericano neutro a propósito: sin regionalismos, sin
# voseo, sin modismos de un país específico — la línea debe sonar igual de
# natural leída por cualquiera de las voces, sea de donde sea.
TEXTO_DE_PRUEBA = (
    "Hola, soy {nombre}. Esta es una prueba de voz en español "
    "latinoamericano, con acento neutro."
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--genero", choices=["femenino", "masculino"])
    ap.add_argument("--nombre", help="Probar sólo una voz por nombre")
    args = ap.parse_args()

    # El chequeo automático que hubiera cazado el error de copiado sin
    # depender de que alguien lo note al escuchar.
    duplicados = find_duplicate_ids()
    if duplicados:
        print(f"{LINE}\n⚠ IDs duplicados detectados en la biblioteca\n{LINE}")
        for vid, nombres in duplicados.items():
            print(f"  {vid}  compartido por: {', '.join(nombres)}")
        print("  Esas voces se excluyen de esta prueba hasta confirmarse.\n")

    if args.nombre:
        voz = get_by_name(args.nombre)
        if voz is None:
            sys.exit(f"No existe ninguna voz curada llamada '{args.nombre}'.")
        if not voz.verified:
            sys.exit(f"'{voz.name}' no está verificada ({voz.note}). "
                     f"Usa --nombre con otra voz.")
        voces = [voz]
    elif args.genero:
        genero = VoiceGender(args.genero)
        voces = [v for v in list_by_gender(genero) if v.verified]
    else:
        voces = usable_voices()

    if not voces:
        sys.exit("No hay voces que probar con esos filtros.")

    costo_aprox = sum(len(TEXTO_DE_PRUEBA.format(nombre=v.name)) for v in voces) \
                  / 1000 * 0.10
    print(f"{LINE}\nProbando {len(voces)} voz(es) — costo aproximado: "
          f"${costo_aprox:.4f}\n{LINE}")

    provider = FalVoiceProvider()
    resultados = []

    for voz in voces:
        texto = TEXTO_DE_PRUEBA.format(nombre=voz.name)
        try:
            r = provider.synthesize(VoiceRequest(
                text=texto, voice_id=voz.voice_id, language="es-419"))
            resultados.append((voz, r, None))
            print(f"✓ {voz.name:10} ({voz.gender.value})  ${r.cost_usd:.4f}")
        except FalVoiceProviderError as exc:
            resultados.append((voz, None, str(exc)))
            print(f"✗ {voz.name:10} ({voz.gender.value})  FALLÓ: {exc}")

    print(f"\n{LINE}\nURLs para escuchar y comparar\n{LINE}")
    for voz, r, error in resultados:
        if r is not None:
            print(f"  {voz.name:10} {r.audio_url}")
    fallidas = [v.name for v, r, e in resultados if r is None]
    if fallidas:
        print(f"\n  Fallaron: {', '.join(fallidas)}")

    print(f"\nEscucha las URLs y decide cuál va con cada personaje. Guarda tu")
    print(f"elección en .env como FAL_VOICE_DEFAULT=el-voice-id, o pásalo por")
    print(f"clip específico cuando se integre a la biblioteca de avatares.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
