"""
Demostración del AI Gateway: `python demo_gateway.py`

Corre con FakeProvider — sin red, sin API key, sin gasto real.
Muestra las cuatro conductas que definen esta capa.
"""

from __future__ import annotations

import json

from app.contracts import Strategy
from app.gateway import (
    AIGateway,
    Budget,
    BudgetExceeded,
    BudgetLimits,
    CostGuard,
    FakeProvider,
    ModelRouter,
    Quality,
    TaskKind,
    TaskSpec,
    unverified_models,
)

LINE = "─" * 70

STRATEGY_OK = {
    "artifact": "strategy", "created_by": "agent_02",
    "awareness_level": "problem_aware",
    "primary_pain": "Organizar la fiesta consume semanas",
    "primary_desire": "Que salga bonita sin esfuerzo",
    "objections": ["precio"],
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
STRATEGY_ROTO = {**STRATEGY_OK, "angles": STRATEGY_OK["angles"][:2]}


# 1 ─ El Router decide, el agente no
print(f"{LINE}\n1 · El agente declara necesidad; el Router elige modelo\n{LINE}")
router = ModelRouter()
for etiqueta, spec in [
    ("Agente 1 · extraer datos del producto", TaskSpec(task=TaskKind.EXTRACTION)),
    ("Agente 2 · estrategia exigente",
     TaskSpec(task=TaskKind.REASONING, quality=Quality.HIGH)),
    ("Agente 3 · hooks (presupuesto bajo)",
     TaskSpec(task=TaskKind.CREATIVE, budget=Budget.LOW)),
    ("Agente 11 · auditoría estándar", TaskSpec(task=TaskKind.REASONING)),
]:
    d = router.route(spec)
    print(f"  {etiqueta:38} → {d.model}")
    print(f"  {'':38}   {d.reason}")

print(f"\n  Precios sin verificar: {', '.join(unverified_models())}")
print("  (declarados como tales en vez de fingir precisión)")


# 2 ─ El tope corta antes de gastar
print(f"\n{LINE}\n2 · El tope se comprueba ANTES de llamar\n{LINE}")
guard = CostGuard(BudgetLimits(max_cost_per_call_usd=0.001))
provider = FakeProvider(responses=[json.dumps(STRATEGY_OK)])
gw = AIGateway(provider=provider, cost_guard=guard)
try:
    gw.generate_artifact(
        contract=Strategy, spec=TaskSpec(task=TaskKind.REASONING),
        system="Eres el Estratega.", user="Define tres ángulos.",
        agent_number=2, agent_name="strategist", max_tokens=8000,
    )
except BudgetExceeded as exc:
    print(f"  ✗ {exc}")
print(f"  Llamadas realmente enviadas al proveedor: {len(provider.calls)}")
print(f"  Gasto de sesión: ${guard.session_spent:.6f}")
print("  Un tope que se verifica después de gastar no es un tope.")


# 3 ─ Reparación con los errores exactos
print(f"\n{LINE}\n3 · JSON que incumple el contrato → reparación dirigida\n{LINE}")
provider = FakeProvider(responses=[json.dumps(STRATEGY_ROTO),
                                   json.dumps(STRATEGY_OK)])
gw = AIGateway(provider=provider)
art = gw.generate_artifact(
    contract=Strategy, spec=TaskSpec(task=TaskKind.REASONING),
    system="Eres el Estratega.", user="Define tres ángulos.",
    agent_number=2, agent_name="strategist", project_code="UGC-0001",
)
correccion = provider.calls[1].user.split("--- CORRECCIÓN REQUERIDA ---")[1]
print("  Lo que se le devolvió al modelo tras el fallo:")
for linea in correccion.strip().splitlines()[:3]:
    print(f"    {linea}")
print(f"\n  Resultado: {type(art).__name__} válido con "
      f"{len(art.angles)} ángulos, en {len(provider.calls)} llamadas.")


# 4 ─ La traza tiene la forma de agent_runs
print(f"\n{LINE}\n4 · Traza lista para insertar en `agent_runs`\n{LINE}")
print(f"  {'ag':>3} {'intento':>8} {'estado':>8} {'in':>6} {'out':>6} {'coste':>10}")
for r in gw.runs:
    print(f"  {r.agent_number:>3} {r.attempt:>8} {r.status:>8} "
          f"{r.input_tokens:>6} {r.output_tokens:>6} ${r.cost_usd:>9.6f}")
print(f"\n  Coste total: ${gw.total_cost():.6f}")
print(f"  Intentos fallidos registrados: {len(gw.failed_runs())}")
print("  El desperdicio por reparaciones queda medido, no escondido.")
