"""
Revisa la versión más reciente de un artefacto bloqueado contra las reglas
ACTUALES del sistema — sin llamar a ningún proveedor, sin gastar nada — y,
si ahora sí califica, la aprueba y avanza el proyecto.

Existe para casos como éste: se recalibró un umbral con datos reales
(ver hooks.py, MIN_AVERAGE) y el trabajo que ya se pagó y quedó bloqueado
bajo la regla vieja puede que ya sea válido bajo la regla nueva.

    python revalidar_y_desbloquear.py UGC-0002
"""

from __future__ import annotations

import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

if len(sys.argv) < 2:
    sys.exit("Uso: python revalidar_y_desbloquear.py <codigo-de-proyecto>")

code = sys.argv[1]

from app.contracts import ArtifactType, Hooks
from app.db import ArtifactRepository, ProjectRepository, engine_for, session_factory
from app.orchestrator import Stage, StageStatus

session = session_factory(engine_for())()
proyecto = ProjectRepository(session).by_code(code)
if proyecto is None:
    sys.exit(f"No existe el proyecto '{code}'.")

if proyecto.stage_status != "blocked":
    sys.exit(f"'{code}' no está bloqueado ahora mismo (estado: "
             f"{proyecto.stage_status}). Nada que hacer aquí.")

artifact_repo = ArtifactRepository(session)
etapa = Stage(proyecto.current_stage)

# Sólo cubre hooks por ahora — es el caso real que motivó el script. Se
# puede ampliar a otras etapas cuando haga falta.
if etapa is not Stage.HOOKS:
    sys.exit(f"Este script sólo sabe revisar la etapa 'hooks' por ahora; "
             f"'{code}' está bloqueado en '{etapa.value}'.")

fila = artifact_repo.latest(proyecto.id, ArtifactType.HOOKS)
if fila is None:
    sys.exit("No hay ningún artefacto de hooks guardado para revisar.")

hooks = Hooks.model_validate(fila.payload)
issues = hooks.blocking_issues()

print(f"Revisando hooks v{fila.version} de {code} contra las reglas actuales "
      f"(umbral: {Hooks.MIN_AVERAGE}, mínimo: {Hooks.MIN_QUALIFIED})...\n")

calificados = hooks.qualified()
print(f"Hooks que califican: {len(calificados)} de {len(hooks.hooks)}")
for h in sorted(calificados, key=lambda h: h.average, reverse=True):
    print(f"  ✓ {h.hook_id}  {h.average:.1f}  \"{h.text[:55]}\"")

if issues:
    print(f"\n✗ Sigue sin calificar bajo las reglas actuales:")
    for i in issues:
        print(f"  - {i.code}: {i.message}")
    print(f"\nNo se aprobó nada. Hará falta generar hooks de nuevo (eso sí")
    print(f"tendría costo) o revisar el umbral otra vez.")
    session.close()
    sys.exit(0)

print(f"\n✓ Ahora SÍ califica. Aprobando sin gastar nada más...")

artifact_repo.approve(fila.id)
proyecto.current_stage = Stage.SCRIPT.value
proyecto.stage_status = StageStatus.PENDING.value
proyecto.retry_counts = {k: v for k, v in (proyecto.retry_counts or {}).items()
                         if k != "hooks"}
session.commit()

print(f"✓ Listo. {code} avanzó a la etapa 'script'.")
print(f"  Puedes seguir desde el panel normalmente.")
session.close()
