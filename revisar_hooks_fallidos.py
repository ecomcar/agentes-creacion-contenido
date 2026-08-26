"""
Diagnóstico SIN COSTO de por qué falló una etapa de hooks.

Lee lo que ya está guardado en tu base de datos (no llama a ningún
proveedor, no gasta nada) y vuelve a correr las mismas reglas de
validación que usa el sistema, para mostrar exactamente qué pasó.

    python revisar_hooks_fallidos.py UGC-0002
"""

from __future__ import annotations

import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if len(sys.argv) < 2:
    sys.exit("Uso: python revisar_hooks_fallidos.py <codigo-de-proyecto>")

code = sys.argv[1]

from app.contracts import ArtifactType, Hooks
from app.db import ArtifactRepository, ProjectRepository, engine_for, session_factory

session = session_factory(engine_for())()
proyecto = ProjectRepository(session).by_code(code)
if proyecto is None:
    sys.exit(f"No existe el proyecto '{code}'.")

artifact_repo = ArtifactRepository(session)
versiones = artifact_repo.history(proyecto.id, ArtifactType.HOOKS)

if not versiones:
    sys.exit(f"'{code}' no tiene ningún artefacto de hooks guardado.")

print(f"Proyecto {code} — etapa actual: {proyecto.current_stage} "
      f"({proyecto.stage_status})")
print(f"Costo total acumulado del proyecto: ${proyecto.total_cost_usd:.4f}\n")

for fila in reversed(versiones):   # de la más vieja a la más nueva
    print("─" * 72)
    print(f"hooks v{fila.version} — estado en base: {fila.status}")
    print("─" * 72)

    try:
        hooks = Hooks.model_validate(fila.payload)
    except Exception as exc:
        print(f"  ✗ El payload guardado ni siquiera cumple el contrato: {exc}")
        continue

    print(f"  Ángulo: {hooks.angle_id}  ·  {len(hooks.hooks)} hooks generados\n")
    for h in sorted(hooks.hooks, key=lambda h: h.average, reverse=True):
        marca = "✓" if h.average >= 80 else " "
        print(f"  {marca} {h.hook_id}  {h.type.value:13} promedio={h.average:5.1f}  "
              f"\"{h.text[:50]}\"")

    calificados = hooks.qualified()
    print(f"\n  Hooks con promedio ≥80: {len(calificados)} de {len(hooks.hooks)} "
          f"(se necesitan al menos 3)")

    issues = hooks.blocking_issues()
    if issues:
        print(f"\n  ✗ POR QUÉ SE BLOQUEÓ:")
        for i in issues:
            print(f"    - {i.code}: {i.message}")
    else:
        print(f"\n  ✓ Este artefacto SÍ cumple los criterios — no debería haber bloqueado.")
    print()

session.close()

print("─" * 72)
print("Nada de esto llamó a Claude ni gastó dinero: es sólo relectura de lo")
print("que ya está guardado, con la misma validación que usa el sistema.")
