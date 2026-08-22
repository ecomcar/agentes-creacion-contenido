"""
Agentes 9-12: voz, montaje, auditoría y cierre del loop.

Con estos cuatro el sistema deja de ser una cadena y se convierte en un
ciclo: el Auditor devuelve el trabajo al agente responsable, y el Analista
alimenta a los agentes 1-3 de la campaña siguiente.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from ..contracts import (
    AuditResult,
    CampaignLearnings,
    CharacterBible,
    EditPlan,
    UGCScript,
    VoiceDirection,
)
from ..gateway import Quality, TaskKind, TaskSpec
from .base import Agent
from .text_agents import _json


class VoiceDirectorAgent(Agent[VoiceDirection]):
    number = 9
    name = "voice_director"
    contract = VoiceDirection
    spec = TaskSpec(task=TaskKind.STRUCTURED)
    temperature = 0.7
    max_tokens = 2048

    def build_user(self, payload: tuple[UGCScript, str, CharacterBible]) -> str:
        script, clip_id, bible = payload
        clip = next((c for c in script.clips if c.clip_id == clip_id), None)
        if clip is None:
            raise ValueError(f"El clip {clip_id} no existe en el guion.")

        return (
            f"Dirige la voz de este clip.\n\n"
            f"CLIP {clip_id} ({clip.role.value}, {clip.duration:.1f}s):\n"
            f"\"{clip.dialogue}\"\n\n"
            f"CÓMO HABLA ESTE AVATAR:\n"
            f"- Estilo: {bible.speech_style}\n"
            f"- Personalidad: {bible.personality}\n"
            f"- Origen: {bible.physical.origin}\n"
            f"- Edad aparente: {bible.physical.age_range}\n\n"
            f"Usa clip_id '{clip_id}'. El perfil de voz debe salir de la ficha "
            f"del avatar, no de lo que suene mejor."
        )


class EditorAgent(Agent[EditPlan]):
    number = 10
    name = "editor"
    contract = EditPlan
    spec = TaskSpec(task=TaskKind.STRUCTURED)

    def build_user(self, payload: tuple[UGCScript, list[str]]) -> str:
        script, clips_listos = payload
        esperados = [c.clip_id for c in script.clips]
        faltan = [c for c in esperados if c not in clips_listos]

        aviso = ""
        if faltan:
            # No se monta en silencio con clips ausentes: se declara.
            aviso = (f"\n\nATENCIÓN: faltan clips sin generar "
                     f"({', '.join(faltan)}). Decláralo en 'errors'.")

        return (
            f"Diseña el montaje.\n\n"
            f"GUION:\n{_json(script)}\n\n"
            f"CLIPS DISPONIBLES: {', '.join(clips_listos)}\n"
            f"Usa expected_clip_ids = {esperados} y "
            f"script_duration_sec {script.total_duration_sec}."
            f"{aviso}"
        )


class AuditorAgent(Agent[AuditResult]):
    number = 11
    name = "auditor"
    contract = AuditResult
    # El Auditor decide si se gasta más dinero o no. No se abarata.
    spec = TaskSpec(task=TaskKind.REASONING, quality=Quality.HIGH)
    temperature = 0.4

    def build_user(self, payload: tuple[str, EditPlan, int, str]) -> str:
        clip_id, edit_plan, cycle, descripcion = payload
        historial = ""
        if cycle > 1:
            historial = (
                f"\n\nÉste es el ciclo {cycle} de corrección de este clip. "
                f"Si el problema anterior persiste, dilo explícitamente en la "
                f"descripción en vez de reportar uno nuevo."
            )
        return (
            f"Audita el clip {clip_id} del anuncio ensamblado.\n\n"
            f"MONTAJE:\n{_json(edit_plan)}\n\n"
            f"OBSERVACIÓN DEL CLIP:\n{descripcion}\n\n"
            f"Usa clip_id '{clip_id}' y cycle {cycle}. Puntúa los doce ejes "
            f"con distancia real entre ellos.{historial}"
        )


class CampaignMetricsInput(BaseModel):
    """Métricas que llegan de la plataforma publicitaria."""

    model_config = ConfigDict(extra="forbid")

    project_code: str
    impressions: int
    ctr: float
    hook_rate: float
    cpa: float | None = None
    roas: float | None = None
    spend_usd: float
    creative_variables: dict[str, str] = Field(default_factory=dict)
    historical_projects: list[str] = Field(default_factory=list)
    historical_impressions: int = 0
    historical_spend_usd: float = 0.0


class AnalystAgent(Agent[CampaignLearnings]):
    number = 12
    name = "analyst"
    contract = CampaignLearnings
    spec = TaskSpec(task=TaskKind.REASONING, quality=Quality.HIGH)
    temperature = 0.4

    def build_user(self, payload: CampaignMetricsInput) -> str:
        evidencia = (
            f"Campañas acumuladas disponibles como evidencia: "
            f"{len(payload.historical_projects)} "
            f"({payload.historical_impressions} impresiones, "
            f"${payload.historical_spend_usd:.2f} de gasto)."
        )
        aviso = ""
        if len(payload.historical_projects) < 3:
            aviso = (
                "\n\nCon menos de 3 campañas de evidencia NINGÚN insight puede "
                "declararse de confianza alta: el contrato lo rechazará. Usa "
                "'media' o 'baja'."
            )

        return (
            f"Analiza los resultados de esta campaña.\n\n"
            f"MÉTRICAS:\n{payload.model_dump_json(indent=2)}\n\n"
            f"{evidencia}\n"
            f"Usa project_code '{payload.project_code}'.{aviso}"
        )
