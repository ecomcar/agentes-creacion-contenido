"""
Validación de prompts con un modelo real.

    python validar_prompts.py --producto producto.json
    python validar_prompts.py --producto producto.json --forzar claude-sonnet-5

Corre los agentes 1→4 sobre un producto real y mide si los prompts producen
buen trabajo. Sólo texto: no genera imagen ni video, así que cuesta centavos.

Requiere ANTHROPIC_API_KEY. Sin ella, explica qué falta y no hace nada.

Para comparar modelos, correr dos veces con `--forzar` y contrastar tanto el
coste como los diagnósticos. Es la forma de saber si el modelo caro se
justifica en el Estratega o si Sonnet produce ángulos igual de distintos.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Cargar .env ANTES de leer variables de entorno. Sin esto, la clave puede
# estar perfectamente configurada en .env y el script igual reportaría que
# falta, porque os.getenv() sólo ve el entorno del proceso, no el archivo.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv no es una dependencia dura: si falta, se sigue igual
    # siempre que ANTHROPIC_API_KEY esté exportada en la sesión de la
    # terminal (export/set), sólo que entonces hay que ponerla ahí cada vez.
    pass

LINE = "─" * 74

EJEMPLO = {
    "product_name": "Party Voom",
    "brand_name": "Party Voom",
    "description": ("Decoración y montaje de fiestas infantiles a domicilio. "
                    "El equipo llega con todo prearmado del taller y monta el "
                    "salón completo en unas tres horas."),
    "known_audience": "Madres de 25 a 40 años en Guayaquil y Samborondón",
    "competitors_known": ["Globos Express", "Fiestas Kids"],
    "brand_voice": "Cercana, sin corporativismo",
}


def cargar_producto(ruta: str | None) -> dict:
    if ruta is None:
        print("  Sin --producto: se usa el ejemplo de Party Voom.\n")
        return EJEMPLO
    p = Path(ruta)
    if not p.is_file():
        sys.exit(f"No existe el archivo {ruta}")
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--producto", help="JSON con los datos del producto")
    ap.add_argument("--forzar", help="Fijar un modelo para todas las etapas")
    ap.add_argument("--duracion", type=float, default=35.0)
    ap.add_argument("--angulo", default=None,
                    help="Ángulo a usar (por defecto, el primero)")
    ap.add_argument("--hook", default=None,
                    help="Hook a usar (por defecto, el mejor puntuado)")
    ap.add_argument("--ejemplo", action="store_true",
                    help="Escribe producto.json de ejemplo y sale")
    # Permiten comparar versiones de un prompt sin tocar las demás etapas:
    # 'crea v2.md y compara' es exactamente lo que estos flags habilitan.
    # default=None, NO default=1: si no se especifica el flag, debe dejarse
    # que cada agente use su propia versión por defecto (HooksAgent ya usa
    # v2). Forzar 1 aquí pisaría esa decisión sin que el usuario lo pidiera
    # — que es exactamente el bug que corrigió esta versión del script.
    ap.add_argument("--version-investigacion", type=int, default=None)
    ap.add_argument("--version-estrategia", type=int, default=None)
    ap.add_argument("--version-hooks", type=int, default=None)
    ap.add_argument("--version-guion", type=int, default=None)
    args = ap.parse_args()

    if args.ejemplo:
        Path("producto.json").write_text(
            json.dumps(EJEMPLO, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Escrito producto.json. Edítalo y vuelve a ejecutar.")
        return 0

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Falta ANTHROPIC_API_KEY.\n")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        print("  pip install anthropic")
        print("\nEs la única clave necesaria: esta validación no genera")
        print("imagen ni video.")
        return 1

    if args.forzar:
        os.environ["FORCE_MODEL"] = args.forzar

    # Los topes por defecto son conservadores; una validación completa de
    # cuatro etapas cabe de sobra, pero lo dejamos explícito.
    os.environ.setdefault("MAX_COST_PER_PROJECT_USD", "2.00")

    from app.agents import (
        HooksAgent,
        ProductInput,
        ResearcherAgent,
        ScriptwriterAgent,
        StrategistAgent,
    )
    from app.gateway import AIGateway
    from app.gateway.providers.anthropic_provider import AnthropicProvider
    from app.orchestrator import Orchestrator, ProjectState, Stage, StageStatus
    from app.services.diagnostics import (
        StageDiagnostics,
        diagnose_brief,
        diagnose_hooks,
        diagnose_script,
        diagnose_strategy,
    )

    gw = AIGateway(provider=AnthropicProvider())
    agentes = {
        1: ResearcherAgent(prompt_version=args.version_investigacion),
        2: StrategistAgent(prompt_version=args.version_estrategia),
        3: HooksAgent(prompt_version=args.version_hooks),
        4: ScriptwriterAgent(prompt_version=args.version_guion),
    }
    orch = Orchestrator(gateway=gw, agents=agentes)
    state = ProjectState(project_code="VALIDACION", auto_mode=True)

    datos = cargar_producto(args.producto)
    print(f"{LINE}\nValidación de prompts — {datos.get('product_name', '?')}")
    if args.forzar:
        print(f"Modelo forzado: {args.forzar}")
    # Se lee de la instancia ya construida, no de args: si el flag venía en
    # None, args.version_hooks no dice qué versión se usó de verdad — sólo
    # agentes[3].prompt_version lo sabe con certeza.
    print(f"Versiones de prompt: investigación=v{agentes[1].prompt_version} "
          f"estrategia=v{agentes[2].prompt_version} "
          f"hooks=v{agentes[3].prompt_version} "
          f"guion=v{agentes[4].prompt_version}")
    print(LINE)

    reportes: list[StageDiagnostics] = []
    rep_errores: list[str] = []

    def ejecutar(etiqueta, stage, payload):
        """
        Ejecuta una etapa con el mismo reintento que haría el sistema real:
        si la compuerta de calidad rechaza el artefacto (válido para el
        contrato, pero por debajo del criterio editorial — por ejemplo,
        menos de 3 hooks con promedio ≥80), se le devuelve al modelo el
        motivo exacto y se le da otra oportunidad, hasta el tope de la
        etapa.

        Sin este bucle, la validación se detenía en el primer rechazo de
        calidad y hacía parecer roto un comportamiento que en producción es
        correcto: el sistema pidiendo un mejor intento antes de gastar en
        las etapas siguientes.
        """
        tope = orch.retry.limit_for(stage)
        costo_total = 0.0
        reparaciones_total = 0
        feedback = None
        intento = 0

        while True:
            intento += 1
            antes = len(gw.runs)
            out = orch.run_stage(state, stage, payload, feedback=feedback)
            llamadas = gw.runs[antes:]
            exitosa = next((r for r in llamadas if r.status == "success"), None)
            fallidas = [r for r in llamadas if r.status == "failed"]

            costo_total += out.cost_usd
            reparaciones_total += len(fallidas)
            rep_errores.extend(
                f"{etiqueta} (intento {intento}, llamada {r.attempt}): "
                f"{r.error_message}"
                for r in fallidas if r.error_message)

            if out.status in (StageStatus.APPROVED,
                              StageStatus.PENDING_HUMAN_APPROVAL):
                rep = StageDiagnostics(
                    stage=etiqueta,
                    model_used=exitosa.model_used if exitosa else "—",
                    cost_usd=round(costo_total, 6),
                    latency_ms=exitosa.latency_ms if exitosa else 0,
                    repairs=reparaciones_total,
                )
                if intento > 1:
                    print(f"\n  ({etiqueta}: aprobado en el intento {intento} "
                          f"de {tope}, tras corregir con el motivo del "
                          f"rechazo anterior)")
                return out.artifact, rep

            rep = StageDiagnostics(stage=etiqueta, cost_usd=round(costo_total, 6),
                                   repairs=reparaciones_total)

            if out.status is StageStatus.BLOCKED:
                # Tope de reintentos agotado: aquí sí correspondería un
                # humano, igual que en el sistema real.
                print(f"\n✗ {etiqueta}: {out.message}")
                reportes.append(rep)
                return None, rep

            # FAILED con intentos disponibles: se reintenta con el motivo
            # exacto del rechazo, tal como haría el orquestador.
            print(f"\n  ({etiqueta}: intento {intento} de {tope} rechazado, "
                  f"reintentando con el motivo)")
            for i in out.issues:
                if i.severity.value == "blocking":
                    print(f"    {i.code}: {i.message}")
            feedback = Orchestrator.feedback_from(out)

    # ── Agente 1
    brief, rep = ejecutar("1 · Investigación", Stage.RESEARCH,
                          ProductInput(**datos))
    if brief is None:
        return 1
    rep.findings = diagnose_brief(brief)
    reportes.append(rep)
    orch.approve_and_advance(state)

    # ── Agente 2
    strategy, rep = ejecutar("2 · Estrategia", Stage.STRATEGY, brief)
    if strategy is None:
        return 1
    rep.findings = diagnose_strategy(strategy)
    reportes.append(rep)
    orch.approve_and_advance(state)

    angle_id = args.angulo or strategy.angles[0].angle_id
    print(f"\n  Ángulos propuestos:")
    for a in strategy.angles:
        marca = "→" if a.angle_id == angle_id else " "
        print(f"  {marca} {a.angle_id}  {a.name[:24]:24} {a.premise[:44]}")

    # ── Agente 3
    hooks, rep = ejecutar("3 · Hooks", Stage.HOOKS, (strategy, angle_id))
    if hooks is None:
        return 1
    rep.findings = diagnose_hooks(hooks)
    reportes.append(rep)
    orch.approve_and_advance(state)

    hook_id = args.hook or hooks.ranked()[0].hook_id
    print(f"\n  Banco de hooks:")
    for h in hooks.ranked():
        marca = "→" if h.hook_id == hook_id else " "
        print(f"  {marca} {h.hook_id}  {h.type.value:13} {h.average:5.1f}  "
              f'"{h.text[:46]}"')

    # ── Agente 4
    script, rep = ejecutar("4 · Guion", Stage.SCRIPT,
                           (strategy, hooks, hook_id, args.duracion))
    if script is None:
        return 1
    rep.findings = diagnose_script(script, hooks, hook_id)
    reportes.append(rep)

    print(f"\n  Guion ({script.total_duration_sec}s):")
    for c in script.clips:
        print(f"    {c.clip_id}  {c.start:>5.1f}-{c.end:<5.1f} "
              f"{c.role.value:14} \"{c.dialogue[:44]}\"")

    # ── Diagnóstico
    print(f"\n{LINE}\nDIAGNÓSTICO\n{LINE}")
    fallos = 0
    for rep in reportes:
        print(f"\n{rep.stage}  ·  {rep.model_used}  ·  ${rep.cost_usd:.4f}  ·  "
              f"{rep.latency_ms/1000:.1f}s"
              + (f"  ·  {rep.repairs} reparación(es)" if rep.repairs else ""))
        for f in rep.findings:
            print(f"  {f.icon} {f.check}: {f.value}")
            if not f.passed:
                fallos += 1
                print(f"      esperado: {f.expectation}")
                if f.detail:
                    print(f"      {f.detail}")

    if rep_errores:
        print(f"\n{LINE}\nDETALLE DE REPARACIONES "
              f"(el modelo falló el contrato y se le corrigió)\n{LINE}")
        for e in rep_errores:
            print(f"  {e}")

    print(f"\n{LINE}\nCOSTE POR ETAPA\n{LINE}")
    total = sum(r.cost_usd for r in reportes)
    for rep in reportes:
        share = rep.cost_usd / total * 100 if total else 0
        barra = "█" * int(share / 3)
        print(f"  {rep.stage:20} ${rep.cost_usd:.4f}  {share:5.1f}%  {barra}")
    print(f"  {'TOTAL':20} ${total:.4f}")

    caras = sorted(reportes, key=lambda r: r.cost_usd, reverse=True)[:1]
    if caras and total and caras[0].cost_usd / total > 0.5:
        print(f"\n  '{caras[0].stage}' se lleva más de la mitad del coste.")
        print(f"  Vale la pena repetir con --forzar claude-sonnet-5 y comparar")
        print(f"  si los diagnósticos empeoran o se mantienen.")

    print(f"\n{LINE}")
    if fallos:
        print(f"  {fallos} diagnóstico(s) fallaron. Los prompts en "
              f"app/prompts/agent_NN/v1.md son editables:")
        print(f"  crea v2.md y compara antes de dar por buena la versión.")
    else:
        print("  Todos los diagnósticos pasan. Los prompts producen trabajo")
        print("  utilizable con este producto; conviene repetir con dos o tres")
        print("  productos más antes de congelarlos.")
    print(LINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
