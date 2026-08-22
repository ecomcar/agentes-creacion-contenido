"""
Diagnósticos de calidad de prompts.

Las 207 pruebas verifican que el sistema **funciona**. Esto mide si los
prompts producen **buen trabajo**, que es otra cosa y no la detecta ningún
test con proveedores falsos.

Cada función mide un modo de fallo concreto que sólo aparece con un modelo
real:

  - El Estratega entregando tres versiones del mismo ángulo.
  - El generador de hooks puntuando todo entre 85 y 95, lo que deja el
    ranking inservible.
  - El Guionista "mejorando" el hook elegido en vez de usarlo literal.
  - Los agentes rellenando huecos en vez de declararlos.

Ninguno de estos produce un error. Todos producen anuncios peores.
"""

from __future__ import annotations

import statistics

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import Hooks, ResearchBrief, Strategy, UGCScript
from ..contracts.base import too_similar


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check: str
    passed: bool
    value: str
    expectation: str
    detail: str = ""

    @property
    def icon(self) -> str:
        return "✓" if self.passed else "✗"


class StageDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    model_used: str = ""
    cost_usd: float = 0.0
    latency_ms: int = 0
    repairs: int = 0
    findings: list[Finding] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(f.passed for f in self.findings)


# ------------------------------------------------------ Agente 1


def diagnose_brief(brief: ResearchBrief) -> list[Finding]:
    f: list[Finding] = []

    # El fallo del Investigador es inventar en vez de declarar. Un brief sin
    # ningún error declarado y con todos los campos llenos es sospechoso
    # cuando el material de entrada era incompleto.
    campos_opcionales = [brief.audience_signals.age_range,
                         brief.audience_signals.location,
                         brief.product.price_range]
    llenos = sum(1 for c in campos_opcionales if c)
    f.append(Finding(
        check="huecos declarados",
        passed=True,   # informativo: depende del material de entrada
        value=f"{len(brief.errors)} errores declarados, {llenos}/3 campos "
              f"opcionales rellenos",
        expectation="lo no aportado debería estar en 'errors', no inventado",
        detail="; ".join(e.code for e in brief.errors) or "ninguno",
    ))

    beneficio = brief.product.core_benefit
    es_beneficio = not any(t in beneficio.lower() for t in
                           ("servicio de", "producto de", "empresa de"))
    f.append(Finding(
        check="beneficio, no característica",
        passed=es_beneficio,
        value=f'"{beneficio[:70]}"',
        expectation="lo que el cliente gana, no lo que el producto hace",
    ))
    return f


# ------------------------------------------------------ Agente 2


def diagnose_strategy(strategy: Strategy) -> list[Finding]:
    f: list[Finding] = []

    # El modo de fallo característico: tres ángulos que son uno.
    pares = []
    for i in range(len(strategy.angles)):
        for j in range(i + 1, len(strategy.angles)):
            a, b = strategy.angles[i], strategy.angles[j]
            pares.append((f"{a.angle_id}/{b.angle_id}",
                          _jaccard(a.premise, b.premise),
                          too_similar(a.premise, b.premise)))

    peor = max(pares, key=lambda p: p[1])
    f.append(Finding(
        check="ángulos distintos",
        passed=not any(p[2] for p in pares),
        value=f"similitud máxima {peor[1]:.2f} ({peor[0]})",
        expectation="por debajo de 0.50 entre todas las parejas",
        detail=" · ".join(f"{p[0]}={p[1]:.2f}" for p in pares),
    ))

    # Un mecanismo que es un eslogan no le sirve al guionista.
    mec = strategy.unique_mechanism
    tiene_porque = any(t in mec.lower() for t in
                       ("porque", "gracias a", "ya que", "mediante", "sin "))
    f.append(Finding(
        check="mecanismo, no eslogan",
        passed=tiene_porque and len(mec) > 30,
        value=f'"{mec[:70]}"',
        expectation="explica POR QUÉ funciona, no que es el mejor",
    ))

    f.append(Finding(
        check="objeciones identificadas",
        passed=len(strategy.objections) >= 2,
        value=f"{len(strategy.objections)}",
        expectation="al menos 2; el guion las necesita para el giro",
    ))
    return f


# ------------------------------------------------------ Agente 3


def diagnose_hooks(hooks: Hooks) -> list[Finding]:
    f: list[Finding] = []
    promedios = [h.average for h in hooks.hooks]
    rango = max(promedios) - min(promedios)
    desviacion = statistics.pstdev(promedios)

    # Si todo puntúa parecido, el ranking no ordena nada y la selección
    # humana pierde su apoyo.
    f.append(Finding(
        check="puntuación con distancia real",
        passed=rango >= 15,
        value=f"rango {rango:.1f} (de {min(promedios):.1f} a "
              f"{max(promedios):.1f}), σ={desviacion:.1f}",
        expectation="rango de al menos 15 puntos entre el mejor y el peor",
        detail="una escala aplanada convierte el ranking en ruido",
    ))

    tipos = {h.type for h in hooks.hooks}
    f.append(Finding(
        check="variedad de tipos",
        passed=len(tipos) >= 4,
        value=f"{len(tipos)} tipos distintos de 7",
        expectation="al menos 4",
        detail=", ".join(sorted(t.value for t in tipos)),
    ))

    # La tensión entre curiosidad y claridad es real; si el modelo le pone
    # 95 a las dos en todos los hooks, no está evaluando.
    tension = [h for h in hooks.hooks
               if h.scores.curiosidad >= 90 and h.scores.claridad >= 90]
    f.append(Finding(
        check="tensión curiosidad/claridad reflejada",
        passed=len(tension) <= len(hooks.hooks) // 3,
        value=f"{len(tension)} de {len(hooks.hooks)} hooks puntúan ≥90 en ambos",
        expectation="pocos; un hook muy intrigante suele ser menos claro",
    ))

    # Lenguaje de marca en un hook que debería sonar a persona.
    marca = ["descubre", "nuestro", "solución integral", "líderes",
             "experiencia única", "no te pierdas"]
    sospechosos = [h.hook_id for h in hooks.hooks
                   if any(t in h.text.lower() for t in marca)]
    f.append(Finding(
        check="suena a persona, no a marca",
        passed=not sospechosos,
        value=f"{len(sospechosos)} hooks con lenguaje de marca",
        expectation="ninguno",
        detail=", ".join(sospechosos) or "—",
    ))

    # El hook ganador se usa literal en el guion (regla del Agente 4). Si es
    # demasiado largo, obliga a leerlo atropellado en un clip de máximo 5s,
    # o a estirar el clip hasta que deje de funcionar como hook. Mejor
    # cazarlo aquí, en la etapa 3, que descubrirlo recién en la etapa 4.
    largos = [(h.hook_id, len(h.text.split())) for h in hooks.hooks
              if len(h.text.split()) > 15]
    f.append(Finding(
        check="hooks decibles en 3-4 segundos",
        passed=not largos,
        value=f"{len(largos)} hooks por encima de 15 palabras",
        expectation="ninguno; ~8-12 palabras por hook",
        detail=", ".join(f"{hid} ({n}p)" for hid, n in largos) or "—",
    ))
    return f


# ------------------------------------------------------ Agente 4


def diagnose_script(script: UGCScript, hooks: Hooks, hook_id: str) -> list[Finding]:
    f: list[Finding] = []
    hook = next((h for h in hooks.hooks if h.hook_id == hook_id), None)

    if hook is not None:
        primero = script.clips[0].dialogue
        literal = hook.text.strip().lower() in primero.strip().lower()
        f.append(Finding(
            check="hook usado literal",
            passed=literal,
            value=f'"{primero[:60]}"',
            expectation=f'debe contener "{hook.text[:45]}"',
            detail="el hook se eligió con datos; 'mejorarlo' descarta esa "
                   "decisión",
        ))

    desvio = abs(script.total_duration_sec - script.target_duration_sec)
    f.append(Finding(
        check="duración en objetivo",
        passed=desvio <= script.target_duration_sec * 0.10,
        value=f"{script.total_duration_sec}s de {script.target_duration_sec}s",
        expectation="±10%",
    ))

    # 2,5 palabras/segundo es el ritmo que el prompt le da al guionista.
    apretados = []
    for c in script.clips:
        palabras = len(c.dialogue.split())
        maximo = c.duration * 2.5
        if palabras > maximo * 1.15:
            apretados.append(f"{c.clip_id} ({palabras}p en {c.duration:.1f}s)")
    f.append(Finding(
        check="diálogo cabe en el tiempo",
        passed=not apretados,
        value=f"{len(apretados)} clips con diálogo apretado",
        expectation="ninguno; ~2,5 palabras por segundo",
        detail=", ".join(apretados) or "—",
    ))

    folleto = ["solución integral", "experiencia única", "líderes del sector",
               "increíble", "espectacular", "el mejor"]
    con_folleto = [c.clip_id for c in script.clips
                   if any(t in c.dialogue.lower() for t in folleto)]
    f.append(Finding(
        check="habla como persona",
        passed=not con_folleto,
        value=f"{len(con_folleto)} clips con vocabulario de folleto",
        expectation="ninguno",
        detail=", ".join(con_folleto) or "—",
    ))
    return f


def _jaccard(a: str, b: str) -> float:
    wa = {w for w in a.lower().split() if len(w) > 3}
    wb = {w for w in b.lower().split() if len(w) > 3}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)
