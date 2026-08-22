"""
Demostración de la fase 4: `python demo_imagen.py`

Del guion a las imágenes base, con proveedores falsos: sin red, sin claves,
sin créditos. Muestra las cuatro conductas nuevas de esta fase.
"""

from __future__ import annotations

import json

from app.agents import IdentityArchitectAgent, ImagePromptAgent, VisualDirectorAgent
from app.contracts import ImagePrompt, Storyboard, UGCScript
from app.gateway import AIGateway, BudgetExceeded, FakeProvider
from app.gateway.providers import (
    FakeImageProvider,
    image_provider,
    unverified_image_providers,
)
from app.services import AvatarLibrary, GenerationBlocked, ImageGenerationService

LINE = "─" * 72

SCRIPT = {
    "artifact": "ugc_script", "created_by": "agent_04", "hook_id": "H02",
    "target_duration_sec": 30.0, "total_duration_sec": 30.0,
    "clips": [
        {"clip_id": "C01", "start": 0, "end": 4, "role": "hook",
         "dialogue": "Casi cancelo el cumpleaños de mi hija por esto"},
        {"clip_id": "C02", "start": 4, "end": 18, "role": "problema",
         "dialogue": "Llevaba semanas con listas y presupuestos"},
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
         "props": [], "product_visible": False},
        {"clip_id": "C02", "shot_type": "selfie", "scenario": "sala de casa",
         "action_summary": "señala unos papeles sobre la mesa",
         "props": ["papeles", "portátil"], "product_visible": False},
        {"clip_id": "C03", "shot_type": "plano_general",
         "scenario": "salón decorado",
         "action_summary": "muestra el salón montado detrás de ella",
         "props": ["globos", "mesa de dulces"], "product_visible": True},
    ],
}

BIBLE = {
    "artifact": "character_bible", "created_by": "agent_06",
    "avatar_id": "AV-FEMALE-EC-001", "display_name": "Sofía — mamá joven",
    "physical": {"age_range": "31-34", "origin": "Ecuador / Guayaquil",
                 "face": "ovalado, pómulos marcados, mentón suave",
                 "hair": "castaño oscuro, media melena, raya al lado, sin peinar del todo",
                 "skin": "oliva clara, textura y poros visibles",
                 "build": "normal, hombros estrechos",
                 "distinguishing_features": ["lunar bajo el ojo izquierdo"]},
    "personality": "habla rápido cuando se emociona, se ríe de sí misma",
    "speech_style": "frases cortas, muletilla 'o sea', se corta a media idea",
    "wardrobe_allowed": ["camiseta blanca", "jeans", "cárdigan gris"],
    "wardrobe_forbidden": ["branding visible", "ropa de pasarela", "uniformes"],
    "natural_imperfections": ["sonrisa ligeramente asimétrica",
                              "mechón que se sale siempre", "ojeras leves"],
    "frequent_scenarios": ["sala de casa", "salón decorado"],
}

PROMPTS = {
    "C01": {"artifact": "image_prompt", "created_by": "agent_07", "clip_id": "C01",
            "avatar_id": "AV-FEMALE-EC-001", "template_code": "NB_SELFIE_UGC",
            "template_version": 3, "scene": "selfie",
            "prompt_text": ("Vertical smartphone selfie of the reference woman, "
                            "living room, natural window light from the left, "
                            "slightly cluttered sofa behind her"),
            "identity_reference_used": True,
            "imperfections_included": ["visible skin texture and pores",
                                       "flyaway hair strand"],
            "negative_constraints": ["studio setup", "empty background"]},
}

PROMPT_MALO = {**PROMPTS["C01"], "clip_id": "C02",
               "identity_reference_used": False,
               "prompt_text": ("Beautiful latina woman, 31 years old, perfect "
                               "skin, cinematic lighting, 8k")}


def gw(responses):
    p = FakeProvider(responses=[json.dumps(r) for r in responses])
    return AIGateway(provider=p), p


# ══ 1 · Del guion al storyboard y la identidad ═══════════════════════════
print(f"{LINE}\n1 · Guion → storyboard → ficha de identidad\n{LINE}")
g, _ = gw([STORYBOARD, BIBLE])

sb = VisualDirectorAgent().run(g, UGCScript.model_validate(SCRIPT))
print("  Storyboard:")
for c in sb.clips:
    prod = "producto" if c.product_visible else "—"
    print(f"    {c.clip_id}  {c.shot_type.value:14} {c.scenario:16} {prod:9} "
          f"{c.action_summary[:34]}")
escenarios = {c.scenario for c in sb.clips}
print(f"    Escenarios distintos: {len(escenarios)} para {len(sb.clips)} clips "
      f"— repetir es lo que hace que parezca real.")

bible = IdentityArchitectAgent().run(
    g, (sb, "AV-FEMALE-EC-001", "Madre de 32 años en Guayaquil"))
print(f"\n  Ficha {bible.avatar_id} — {bible.display_name}")
print(f"    Imperfecciones declaradas ({len(bible.natural_imperfections)}):")
for i in bible.natural_imperfections:
    print(f"      · {i}")
print(f"    Vestuario prohibido: {', '.join(bible.wardrobe_forbidden)}")


# ══ 2 · El avatar no está listo hasta tener referencias ═════════════════
print(f"\n{LINE}\n2 · Un avatar sin referencias no puede anclar nada\n{LINE}")
lib = AvatarLibrary()
lib.save(bible)
print(f"  ¿Listo? {lib.is_ready(bible.avatar_id)} — "
      f"faltan {len(lib.missing_references(bible.avatar_id))} ángulos: "
      f"{', '.join(lib.missing_references(bible.avatar_id))}")
for angle in bible.reference_angles_needed:
    lib.add_reference(bible.avatar_id, angle, f"https://ref/{angle}.png")
print(f"  ¿Listo? {lib.is_ready(bible.avatar_id)} — "
      f"{len(lib.references(bible.avatar_id))} referencias generadas.")
print("  Generar clips antes de esto produce la deriva de rostro que todo el")
print("  diseño intenta evitar.")


# ══ 3 · Las compuertas cortan antes de gastar créditos ══════════════════
print(f"\n{LINE}\n3 · Prompt rechazado: no se genera nada\n{LINE}")
provider_img = FakeImageProvider()
svc = ImageGenerationService(provider=provider_img)

try:
    svc.generate(ImagePrompt.model_validate(PROMPT_MALO),
                 project_code="UGC-0001")
except GenerationBlocked as exc:
    print(f"  ✗ {exc}")
    for i in exc.issues:
        print(f"      · {i.code}: {i.message}")
print(f"  Llamadas al generador de imagen: {len(provider_img.calls)}")
print("  Un fallo de imagen cuesta lo mismo que un acierto; por eso la")
print("  compuerta está antes y no después.")


# ══ 4 · Variantes, selección y coste ════════════════════════════════════
print(f"\n{LINE}\n4 · Variantes y selección única por clip\n{LINE}")
image_provider.IMAGE_PRICES["fake_image"].usd_per_image = 0.03  # precio simulado

svc = ImageGenerationService(provider=FakeImageProvider(),
                             max_cost_per_clip_usd=0.15)
assets = svc.generate(ImagePrompt.model_validate(PROMPTS["C01"]),
                      project_code="UGC-0001",
                      reference_urls=lib.references(bible.avatar_id),
                      n_variants=3)
print(f"  Generadas {len(assets)} variantes del clip C01 "
      f"(prompt {assets[0].source_prompt_id}):")
for a in assets:
    print(f"    v{a.version}  {a.storage_url[-16:]}  ${a.cost_usd:.4f}  "
          f"{'✓ elegida' if a.is_selected else ''}")

print("\n  El humano elige la v2, luego cambia de opinión y elige la v3:")
svc.select(assets[1].id)
svc.select(assets[2].id)
for a in svc.variants_for("UGC-0001", "C01"):
    print(f"    v{a.version}  {'✓ elegida' if a.is_selected else '—'}")
print("  Sólo una puede estar seleccionada: sin esa garantía el Editor")
print("  termina ensamblando dos versiones del mismo clip.")

print(f"\n  Coste en imagen del proyecto: "
      f"${svc.cost_report('UGC-0001')['project_usd']:.4f}")
try:
    svc.generate(ImagePrompt.model_validate(PROMPTS["C01"]),
                 project_code="UGC-0001", n_variants=3)
except BudgetExceeded as exc:
    print(f"  ⛔ {exc}")

print(f"\n  Proveedores de imagen sin precio verificado: "
      f"{', '.join(unverified_image_providers())}")
print("  Las cifras de arriba son simuladas. Configurar PRICE_IMAGE_* en .env")
print("  con los precios reales antes de presupuestar una campaña.")
