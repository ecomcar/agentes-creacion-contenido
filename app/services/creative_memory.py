"""
Memoria creativa.

Cierra el ciclo: el Agente 12 escribe aquí y los Agentes 1, 2 y 3 leen al
empezar la campaña siguiente.

**El riesgo de esta pieza es que convierta ruido en doctrina.** Un aprendizaje
sacado de una campaña, tratado como ley por los agentes de estrategia, hace
que el sistema repita un acierto casual durante meses.

Tres defensas, en orden de fuerza:

1. El contrato del Agente 12 rechaza confianza alta sin 3 campañas y 10.000
   impresiones de evidencia.
2. Sólo los insights de confianza alta entran aquí.
3. Un insight puede caducar o desactivarse: lo que funcionó hace un año en
   una plataforma puede no funcionar hoy.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import CampaignLearnings, Confidence, Insight

# Un aprendizaje de hace más de seis meses en publicidad digital es
# arqueología: las plataformas y los formatos cambian demasiado rápido.
DEFAULT_TTL_DAYS = 180


class MemoryEntry(BaseModel):
    """Forma de la tabla `creative_memory`."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    scope: str = "brand"                 # brand | category | global
    scope_value: str | None = None
    insight: str
    confidence: Confidence
    applies_to: list[str] = Field(default_factory=list)
    evidence_projects: list[str] = Field(default_factory=list)
    evidence_impressions: int = 0
    source_project: str | None = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def is_stale(self, ttl_days: int = DEFAULT_TTL_DAYS,
                 now: datetime | None = None) -> bool:
        ahora = now or datetime.now(timezone.utc)
        return ahora - self.created_at > timedelta(days=ttl_days)


class CreativeMemory:
    """Almacén en memoria. Las mismas operaciones sobre `creative_memory`."""

    def __init__(self, ttl_days: int = DEFAULT_TTL_DAYS):
        self.entries: list[MemoryEntry] = []
        self.ttl_days = ttl_days

    def write(self, learnings: CampaignLearnings, *,
              scope_value: str | None = None) -> list[MemoryEntry]:
        """
        Escribe sólo los insights de confianza alta.

        Devuelve lo escrito, que puede ser una lista vacía. Que una campaña no
        produzca memoria es un resultado normal, no un fallo.
        """
        nuevas = []
        for ins in learnings.writable_to_memory():
            entrada = MemoryEntry(
                scope=ins.scope, scope_value=ins.scope_value or scope_value,
                insight=ins.text, confidence=ins.confidence,
                applies_to=list(ins.applies_to),
                evidence_projects=list(ins.evidence.project_codes),
                evidence_impressions=ins.evidence.total_impressions,
                source_project=learnings.project_code,
            )
            self.entries.append(entrada)
            nuevas.append(entrada)
        return nuevas

    def query(self, *, scope_value: str | None = None,
              applies_to: str | None = None,
              now: datetime | None = None) -> list[MemoryEntry]:
        """
        Lo que un agente recibe al empezar una campaña.

        Filtra por marca o categoría, por variable afectada, y descarta lo
        caducado y lo desactivado.
        """
        resultado = []
        for e in self.entries:
            if not e.is_active or e.is_stale(self.ttl_days, now):
                continue
            if scope_value is not None and e.scope_value not in (None, scope_value):
                continue
            if applies_to is not None and applies_to not in e.applies_to:
                continue
            resultado.append(e)
        # Más evidencia primero: si dos aprendizajes se contradicen, que el
        # agente vea antes el que se apoya en más datos.
        return sorted(resultado, key=lambda e: e.evidence_impressions,
                      reverse=True)

    def as_prompt_lines(self, **kw) -> list[str]:
        """Formato que consume `StrategistWithMemoryAgent`."""
        return [f"{e.insight} (evidencia: {len(e.evidence_projects)} campañas, "
                f"{e.evidence_impressions:,} impresiones)"
                for e in self.query(**kw)]

    def deactivate(self, entry_id: str, reason: str = "") -> MemoryEntry:
        """
        Un aprendizaje puede dejar de ser cierto. Desactivar, no borrar: el
        histórico explica decisiones pasadas.
        """
        entrada = next((e for e in self.entries if e.id == entry_id), None)
        if entrada is None:
            raise KeyError(f"No existe la entrada {entry_id}.")
        entrada.is_active = False
        return entrada

    def stats(self, now: datetime | None = None) -> dict[str, int]:
        activas = self.query(now=now)
        return {
            "total": len(self.entries),
            "activas": len(activas),
            "caducadas": sum(1 for e in self.entries
                             if e.is_stale(self.ttl_days, now)),
            "desactivadas": sum(1 for e in self.entries if not e.is_active),
        }
