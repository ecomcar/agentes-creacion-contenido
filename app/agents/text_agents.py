"""
Agentes 1-4: los que sólo necesitan texto.

Con estos cuatro el pipeline ya produce guiones UGC trazables sin haber
gastado un dólar en generación de imagen o video. Es donde conviene validar
los prompts de razonamiento, porque a partir del Agente 7 cada iteración
cuesta créditos.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

from ..contracts import Hooks, ResearchBrief, Strategy, UGCScript
from ..gateway import Quality, TaskKind, TaskSpec
from .base import Agent


def _json(model: BaseModel, exclude=("created_at", "input_ref")) -> str:
    """El artefacto de entrada, sin los metadatos que no aportan al modelo."""
    return model.model_dump_json(indent=2, exclude=set(exclude))


# ---------------------------------------------------------- Agente 1


class ProductInput(BaseModel):
    """Lo único que el humano tiene que aportar para arrancar un proyecto."""

    model_config = ConfigDict(extra="forbid")

    product_name: str
    description: str
    brand_name: str
    website: str | None = None
    known_audience: str | None = None
    competitors_known: list[str] = []
    brand_voice: str | None = None
    extra_material: str | None = None


class ResearcherAgent(Agent[ResearchBrief]):
    number = 1
    name = "researcher"
    contract = ResearchBrief
    # Extracción sobre material ya dado: no requiere juicio estratégico.
    spec = TaskSpec(task=TaskKind.EXTRACTION)
    temperature = 0.3

    def build_user(self, payload: ProductInput) -> str:
        return (
            "Construye el brief de investigación a partir de este material.\n\n"
            f"{_json(payload, exclude=())}\n\n"
            "Recuerda: lo que no esté en el material va en 'errors', no "
            "inventado en el cuerpo del brief."
        )


# ---------------------------------------------------------- Agente 2


class StrategistAgent(Agent[Strategy]):
    number = 2
    name = "strategist"
    contract = Strategy
    # Validado con datos reales sobre dos productos (Party Voom, Karol/
    # Seytu): Sonnet produjo ángulos igual de distintos, mecanismos igual
    # de sólidos y el mismo número de objeciones que Opus, por una fracción
    # del costo — la etapa pasó de ~$0.22-0.30 a ~$0.04 por ejecución, sin
    # que ningún diagnóstico empeorara. Antes se pedía Quality.HIGH (Opus)
    # sin haberlo comparado nunca contra la alternativa barata; ahora sí.
    spec = TaskSpec(task=TaskKind.REASONING)

    def build_user(self, payload: ResearchBrief) -> str:
        memoria = ""
        return (
            "Define la estrategia a partir de este brief.\n\n"
            f"{_json(payload)}\n"
            f"{memoria}\n"
            "Entrega exactamente tres ángulos que puedan convivir en la misma "
            "campaña sin canibalizarse."
        )


class StrategistWithMemoryAgent(StrategistAgent):
    """
    Variante que recibe aprendizajes previos de `creative_memory`.

    Se usará cuando el Agente 12 haya producido insights de confianza alta.
    Hasta entonces el sistema arranca desde cero en cada campaña, que es lo
    correcto: sin datos, un "aprendizaje" es una superstición.
    """

    def build_user(self, payload: tuple[ResearchBrief, list[str]]) -> str:
        brief, insights = payload
        base = super().build_user(brief)
        if not insights:
            return base
        lista = "\n".join(f"- {i}" for i in insights)
        return (
            f"{base}\n\n"
            f"--- APRENDIZAJES DE CAMPAÑAS ANTERIORES ---\n{lista}\n\n"
            f"Son orientativos, no obligatorios: proceden de otras campañas y "
            f"pueden no aplicar a ésta. Si usas uno, marca el ángulo "
            f"correspondiente con 'memory_backed': true."
        )


# ---------------------------------------------------------- Agente 3


class HooksAgent(Agent[Hooks]):
    number = 3
    name = "hooks_generator"
    contract = Hooks
    spec = TaskSpec(task=TaskKind.CREATIVE)
    temperature = 1.0   # aquí la variedad es el producto
    # 10-12 hooks con 6 puntuaciones cada uno se acercaba al límite por
    # defecto (4096) y el modelo cortaba el JSON a mitad de un hook,
    # forzando reparaciones que cuestan dinero y tiempo sin necesidad.
    max_tokens = 6000
    # v2 añade un procedimiento de recorte con ejemplo (v1 solo pedía el
    # límite de palabras en abstracto). Validado con datos reales: v1 dejaba
    # 5 de 10 hooks por encima de 15 palabras en un producto (Karol/Seytu);
    # v2, sobre el mismo producto, dejó 0. v1 sigue en el archivo para
    # comparar si algún día se quiere revisar la decisión.
    default_prompt_version = 2

    def build_user(self, payload: tuple[Strategy, str]) -> str:
        strategy, angle_id = payload
        angle = next((a for a in strategy.angles if a.angle_id == angle_id), None)
        if angle is None:
            raise ValueError(
                f"El ángulo {angle_id} no existe en la estrategia "
                f"v{strategy.version}."
            )
        return (
            f"Genera hooks para el ángulo seleccionado.\n\n"
            f"ÁNGULO ELEGIDO ({angle.angle_id}):\n"
            f"{angle.model_dump_json(indent=2)}\n\n"
            f"CONTEXTO ESTRATÉGICO:\n"
            f"{json.dumps({'awareness_level': strategy.awareness_level.value, 'primary_pain': strategy.primary_pain, 'primary_desire': strategy.primary_desire, 'objections': strategy.objections, 'unique_mechanism': strategy.unique_mechanism}, ensure_ascii=False, indent=2)}\n\n"
            f"Usa angle_id '{angle_id}'. Puntúa con honestidad: debe haber "
            f"distancia real entre el mejor hook y el peor."
        )


# ---------------------------------------------------------- Agente 4


class ScriptwriterAgent(Agent[UGCScript]):
    number = 4
    name = "scriptwriter"
    contract = UGCScript
    spec = TaskSpec(task=TaskKind.CREATIVE)

    def build_user(self, payload: tuple[Strategy, Hooks, str, float]) -> str:
        strategy, hooks, hook_id, target_duration = payload
        hook = next((h for h in hooks.hooks if h.hook_id == hook_id), None)
        if hook is None:
            raise ValueError(f"El hook {hook_id} no existe en el banco.")
        return (
            f"Escribe el guion UGC.\n\n"
            f"HOOK ELEGIDO ({hook.hook_id}, tipo {hook.type.value}) — úsalo "
            f"literal en el primer clip:\n\"{hook.text}\"\n\n"
            f"ESTRATEGIA:\n{_json(strategy)}\n\n"
            f"DURACIÓN OBJETIVO: {target_duration} segundos "
            f"(tolerancia ±10%).\n"
            f"Usa hook_id '{hook_id}' y target_duration_sec {target_duration}."
        )
