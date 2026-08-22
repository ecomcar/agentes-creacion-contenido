"""
Enrutador de correcciones.

El Auditor identifica **qué agente** origina el problema. Pero corregir casi
nunca es un solo agente: si se rehace la identidad del avatar, hay que
regenerar la imagen y después el video. Lo que este módulo devuelve es la
**cadena mínima** que hay que reejecutar.

Ahí está el ahorro real del sistema:

    Movimiento artificial   →  11 → 8 → 11              (1 regeneración)
    Rostro inconsistente    →  11 → 6 → 7 → 8 → 11      (3 regeneraciones)
    Hook débil              →  11 → 3 → 4 → 5 → 7 → 8 → 11

Un rechazo genérico obligaría siempre a la cadena larga. Por eso el contrato
del Agente 11 prohíbe rechazar sin categoría.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..contracts import ERROR_ROUTING, IssueCategory
from .state_machine import Stage

# Cadena mínima de agentes a reejecutar por categoría de problema.
# El primer elemento coincide siempre con ERROR_ROUTING (el responsable);
# el resto son las consecuencias inevitables aguas abajo.
CORRECTION_CHAINS: dict[IssueCategory, list[int]] = {
    IssueCategory.IDENTITY: [6, 7, 8],          # identidad → imagen → video
    IssueCategory.ANATOMY: [7, 8],              # se arregla en la imagen base
    IssueCategory.PRODUCT: [7, 8],
    IssueCategory.MOTION: [8],                  # sólo el video
    IssueCategory.PHYSICS: [8],
    IssueCategory.UGC_REALISM: [8],
    IssueCategory.LIP_SYNC: [9, 10],            # voz → montaje
    IssueCategory.VOICE: [9, 10],
    IssueCategory.CONTINUITY: [5, 7, 8],        # storyboard → imagen → video
    IssueCategory.PACING: [10],                 # sólo el montaje
    IssueCategory.COMMERCIAL_CLARITY: [4, 5, 7, 8],
    IssueCategory.HOOK_VISUAL: [3, 4, 5, 7, 8], # la más cara: vuelve a hooks
}

AGENT_STAGE: dict[int, Stage] = {
    1: Stage.RESEARCH, 2: Stage.STRATEGY, 3: Stage.HOOKS, 4: Stage.SCRIPT,
    5: Stage.STORYBOARD, 6: Stage.IDENTITY, 7: Stage.IMAGE, 8: Stage.VIDEO,
    9: Stage.VOICE, 10: Stage.EDIT, 11: Stage.AUDIT,
}


class CorrectionRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: IssueCategory
    responsible_agent: int
    chain: list[int]
    stages: list[Stage]
    clip_id: str | None = None
    description: str = ""

    @property
    def regenerations(self) -> int:
        """Cuántas etapas hay que reejecutar. Proxy directo del coste."""
        return len(self.chain)

    @property
    def touches_billable(self) -> bool:
        """¿La corrección consume créditos de generación, no sólo tokens?"""
        return any(a in (7, 8, 9) for a in self.chain)

    def as_path(self) -> str:
        return " → ".join(["11", *map(str, self.chain), "11"])


def route_correction(category: IssueCategory, *, clip_id: str | None = None,
                     description: str = "") -> CorrectionRoute:
    chain = CORRECTION_CHAINS[category]
    responsible = ERROR_ROUTING[category]

    # Invariante: el responsable declarado por el contrato del Auditor tiene
    # que ser quien encabeza la cadena. Si divergen, una de las dos tablas se
    # editó sin la otra.
    assert chain[0] == responsible, (
        f"Incoherencia entre ERROR_ROUTING ({responsible}) y "
        f"CORRECTION_CHAINS ({chain[0]}) para '{category.value}'."
    )

    return CorrectionRoute(
        category=category, responsible_agent=responsible, chain=chain,
        stages=[AGENT_STAGE[a] for a in chain],
        clip_id=clip_id, description=description,
    )


def cheapest_first(categories: list[IssueCategory]) -> list[IssueCategory]:
    """
    Ordena problemas por coste de corrección.

    Cuando un clip falla en varios ejes, conviene atacar primero lo barato:
    a veces arreglar el movimiento sube lo suficiente el realismo como para
    que el resto deje de importar, y nos ahorramos la cadena larga.
    """
    return sorted(categories, key=lambda c: len(CORRECTION_CHAINS[c]))
