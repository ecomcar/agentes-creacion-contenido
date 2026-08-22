"""
Demostración del pipeline de la fase 3: `python demo_pipeline.py`

Recorre brief → estrategia → hooks → guion con FakeProvider —sin red, sin
clave, sin gasto— y muestra las cuatro conductas del orquestador:

  1. Las compuertas humanas detienen el pipeline donde importa.
  2. Un artefacto válido que no cumple los criterios se reintenta con
     feedback, sin perder el trabajo del agente.
  3. Los topes bloquean en vez de seguir gastando.
  4. El enrutamiento de correcciones elige la cadena mínima.
"""

from __future__ import annotations

import json

from app.agents import (
    HooksAgent,
    ProductInput,
    ResearcherAgent,
    ScriptwriterAgent,
    StrategistAgent,
)
from app.contracts import IssueCategory
from app.gateway import AIGateway, FakeProvider
from app.orchestrator import (
    Orchestrator,
    ProjectState,
    RetryLimits,
    RetryPolicy,
    Stage,
    StageStatus,
    cheapest_first,
    route_correction,
)

LINE = "─" * 72

BRIEF = {
    "artifact": "research_brief", "created_by": "agent_01",
    "product": {"name": "Party Voom", "category": "decoración infantil",
                "core_benefit": "La fiesta queda montada sin organizar nada"},
    "audience_signals": {"age_range": "25-40", "location": "Guayaquil",
                         "known_pain_points": ["falta de tiempo"]},
    "competitors": [{"name": "Globos Express", "angle_observed": "precio bajo"}],
}

STRATEGY = {
    "artifact": "strategy", "created_by": "agent_02",
    "awareness_level": "problem_aware",
    "primary_pain": "Organizar la fiesta consume semanas",
    "primary_desire": "Que salga bonita sin esfuerzo",
    "objections": ["precio", "confianza"],
    "unique_mechanism": "Montaje llave en mano en tres horas",
    "angles": [
        {"angle_id": "A01", "name": "Mamá sola",
         "premise": "Intenta hacerlo todo sola", "emotion": "alivio",
         "recommended_format": "ugc"},
        {"angle_id": "A02", "name": "Precio oculto",
         "premise": "Nadie cuenta lo que cuesta improvisar",
         "emotion": "sorpresa", "recommended_format": "ugc"},
        {"angle_id": "A03", "name": "Antes y después",
         "premise": "Transformación visible del salón", "emotion": "orgullo",
         "recommended_format": "reel"},
    ],
}
STRATEGY_FLOJA = {**STRATEGY, "unique_mechanism": "por definir"}

HOOKS = {
    "artifact": "hooks", "created_by": "agent_03", "angle_id": "A01",
    "hooks": [
        {"hook_id": "H01", "type": "problema",
         "text": "Llevo tres semanas organizando un cumpleaños de cuatro horas",
         "scores": {"curiosidad": 82, "claridad": 91, "pattern_interrupt": 78,
                    "relevancia": 94, "ugc_fit": 89, "visual_ease": 86}},
        {"hook_id": "H02", "type": "confesion",
         "text": "Casi cancelo el cumpleaños de mi hija por esto",
         "scores": {"curiosidad": 95, "claridad": 84, "pattern_interrupt": 93,
                    "relevancia": 90, "ugc_fit": 96, "visual_ease": 88}},
        {"hook_id": "H03", "type": "curiosidad",
         "text": "Nadie te cuenta lo que cuesta de verdad organizar una fiesta",
         "scores": {"curiosidad": 93, "claridad": 71, "pattern_interrupt": 88,
                    "relevancia": 85, "ugc_fit": 87, "visual_ease": 79}},
        {"hook_id": "H04", "type": "contrarian",
         "text": "Hacerlo tú misma no sale más barato",
         "scores": {"curiosidad": 79, "claridad": 88, "pattern_interrupt": 84,
                    "relevancia": 81, "ugc_fit": 83, "visual_ease": 80}},
        {"hook_id": "H05", "type": "testimonial",
         "text": "Llegaron a las nueve y a las doce estaba todo montado",
         "scores": {"curiosidad": 68, "claridad": 92, "pattern_interrupt": 61,
                    "relevancia": 88, "ugc_fit": 85, "visual_ease": 90}},
        {"hook_id": "H06", "type": "demostracion",
         "text": "Mira cómo quedó el salón en tres horas",
         "scores": {"curiosidad": 74, "claridad": 90, "pattern_interrupt": 70,
                    "relevancia": 83, "ugc_fit": 80, "visual_ease": 95}},
        {"hook_id": "H07", "type": "visual",
         "text": "Este era el salón esta mañana",
         "scores": {"curiosidad": 86, "claridad": 76, "pattern_interrupt": 90,
                    "relevancia": 78, "ugc_fit": 82, "visual_ease": 93}},
        {"hook_id": "H08", "type": "problema",
         "text": "Cada año prometo que el siguiente lo organizo con tiempo",
         "scores": {"curiosidad": 71, "claridad": 83, "pattern_interrupt": 65,
                    "relevancia": 87, "ugc_fit": 88, "visual_ease": 74}},
    ],
}

SCRIPT = {
    "artifact": "ugc_script", "created_by": "agent_04", "hook_id": "H02",
    "target_duration_sec": 35.0, "total_duration_sec": 35.0,
    "clips": [
        {"clip_id": "C01", "start": 0, "end": 4, "role": "hook",
         "dialogue": "Casi cancelo el cumpleaños de mi hija por esto"},
        {"clip_id": "C02", "start": 4, "end": 14, "role": "problema",
         "dialogue": "Llevaba semanas con listas, presupuestos, cotizaciones. Y yo trabajo."},
        {"clip_id": "C03", "start": 14, "end": 26, "role": "demostracion",
         "dialogue": "Llegaron a las nueve. A las doce estaba esto montado. Yo no hice nada."},
        {"clip_id": "C04", "start": 26, "end": 35, "role": "cta",
         "dialogue": "Si te pasa lo mismo, escríbeles antes de volverte loca"},
    ],
    "cta": "Escríbenos por WhatsApp",
}


def build(responses):
    provider = FakeProvider(responses=[json.dumps(r) for r in responses])
    gw = AIGateway(provider=provider)
    agents = {1: ResearcherAgent(), 2: StrategistAgent(),
              3: HooksAgent(), 4: ScriptwriterAgent()}
    return Orchestrator(gateway=gw, agents=agents), provider, gw


ICON = {StageStatus.APPROVED: "🟢", StageStatus.PENDING_HUMAN_APPROVAL: "🟡",
        StageStatus.FAILED: "🔴", StageStatus.BLOCKED: "⛔"}


def show(out):
    print(f"  {ICON.get(out.status, '⚪')} {out.stage.value:11} "
          f"{out.status.value:24} ${out.cost_usd:.6f}   {out.message}")
    for i in out.issues:
        marca = "✗" if i.severity.value == "blocking" else "!"
        print(f"       {marca} {i.code}: {i.message}")


# ══ 1 · Pipeline con compuertas humanas ═════════════════════════════════
print(f"{LINE}\n1 · Pipeline completo: brief → estrategia → hooks → guion\n{LINE}")
orch, _, gw = build([BRIEF, STRATEGY, HOOKS, SCRIPT])
state = ProjectState(project_code="UGC-0001")

r1 = orch.run_stage(state, Stage.RESEARCH, ProductInput(
    product_name="Party Voom", brand_name="Party Voom",
    description="Decoración y montaje de fiestas infantiles a domicilio",
    known_audience="Madres 25-40 en Guayaquil y Samborondón"))
show(r1)
orch.approve_and_advance(state)

r2 = orch.run_stage(state, Stage.STRATEGY, r1.artifact)
show(r2)
print("       → El humano elige entre tres ángulos:")
for a in r2.artifact.angles:
    print(f"         {a.angle_id}  {a.name:18} {a.premise}")
print("       → Elegido: A01")
orch.approve_and_advance(state)

r3 = orch.run_stage(state, Stage.HOOKS, (r2.artifact, "A01"))
show(r3)
print("       → Banco de hooks ordenado por promedio:")
for h in r3.artifact.ranked()[:4]:
    print(f"         {h.hook_id}  {h.type.value:13} {h.average:5.1f}   \"{h.text[:44]}…\"")
print(f"       → Calificados (≥80): {len(r3.artifact.qualified())} de "
      f"{len(r3.artifact.hooks)} · Elegido: H02")
orch.approve_and_advance(state)

r4 = orch.run_stage(state, Stage.SCRIPT, (r2.artifact, r3.artifact, "H02", 35.0))
show(r4)
for c in r4.artifact.clips:
    print(f"         {c.clip_id}  {c.start:>5.1f}-{c.end:<5.1f} {c.role.value:13} "
          f"\"{c.dialogue[:42]}…\"")

print(f"\n  Etapa actual: {state.current_stage.value} · "
      f"Coste acumulado: ${state.total_cost_usd:.6f} · "
      f"Llamadas: {len(gw.runs)}")


# ══ 2 · Artefacto válido que no supera los criterios ════════════════════
print(f"\n{LINE}\n2 · Válido para el contrato, rechazado por los criterios\n{LINE}")
orch, provider, _ = build([STRATEGY_FLOJA, STRATEGY])
state = ProjectState(project_code="UGC-0002", current_stage=Stage.STRATEGY)
from app.contracts import ResearchBrief
brief = ResearchBrief.model_validate(BRIEF)

fallo = orch.run_stage(state, Stage.STRATEGY, brief)
show(fallo)
print(f"       El artefacto NO se pierde: {type(fallo.artifact).__name__} "
      f"v{fallo.artifact.version} queda como borrador.")

feedback = Orchestrator.feedback_from(fallo)
print(f"\n       Feedback que se le devuelve al agente:\n       {feedback}")

ok = orch.run_stage(state, Stage.STRATEGY, brief, feedback=feedback)
show(ok)
print(f"       Reintentos pendientes tras lograrlo: "
      f"{state.retry_counts.get('strategy', 0)}")


# ══ 3 · El tope bloquea en vez de seguir gastando ═══════════════════════
print(f"\n{LINE}\n3 · Topes de reintento: bloquear antes que quemar créditos\n{LINE}")
orch, provider, _ = build([STRATEGY_FLOJA] * 5)
orch.retry = RetryPolicy(RetryLimits(strategy=2))
state = ProjectState(project_code="UGC-0003", current_stage=Stage.STRATEGY)
for n in (1, 2, 3):
    out = orch.run_stage(state, Stage.STRATEGY, brief)
    print(f"  Intento {n}: {ICON[out.status]} {out.status.value}")
    if out.status is StageStatus.BLOCKED:
        print(f"       {out.message}")
print(f"  Llamadas realmente enviadas al modelo: {len(provider.calls)} de 3.")


# ══ 4 · Enrutamiento de correcciones ════════════════════════════════════
print(f"\n{LINE}\n4 · Cadena mínima de corrección por tipo de problema\n{LINE}")
print(f"  {'problema':22} {'ruta':30} {'etapas':>7}  créditos")
for cat in cheapest_first([IssueCategory.HOOK_VISUAL, IssueCategory.IDENTITY,
                           IssueCategory.MOTION, IssueCategory.PACING,
                           IssueCategory.VOICE]):
    r = route_correction(cat, clip_id="C03")
    print(f"  {cat.value:22} {r.as_path():30} {r.regenerations:>7}  "
          f"{'sí' if r.touches_billable else 'no'}")
print("\n  Un rechazo genérico obligaría siempre a la cadena más larga.")
print("  Por eso el contrato del Auditor prohíbe rechazar sin categoría.")
