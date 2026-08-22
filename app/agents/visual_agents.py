"""
Agentes 5-7: del guion a la imagen base.

A partir de aquí el pipeline empieza a costar créditos además de tokens. Por
eso el Agente 7 concentra las compuertas más estrictas del sistema: un prompt
que redescribe al personaje o que suena a comercial se rechaza **antes** de
generar nada.
"""

from __future__ import annotations

from ..contracts import CharacterBible, ImagePrompt, Storyboard, UGCScript
from ..gateway import Quality, TaskKind, TaskSpec
from .base import Agent
from .text_agents import _json


class VisualDirectorAgent(Agent[Storyboard]):
    number = 5
    name = "visual_director"
    contract = Storyboard
    spec = TaskSpec(task=TaskKind.CREATIVE)

    def build_user(self, payload: UGCScript) -> str:
        ids = [c.clip_id for c in payload.clips]
        return (
            f"Construye el storyboard de este guion.\n\n"
            f"{_json(payload)}\n\n"
            f"Un clip del storyboard por cada clip del guion, exactamente "
            f"estos: {', '.join(ids)}.\n"
            f"Usa script_clip_ids = {ids}.\n"
            f"Repite escenarios salvo que la narrativa exija cambiarlos."
        )


class IdentityArchitectAgent(Agent[CharacterBible]):
    number = 6
    name = "identity_architect"
    contract = CharacterBible
    # La identidad se reutiliza en decenas de clips: un error aquí se
    # multiplica. Calidad alta aunque sea una sola llamada por avatar.
    spec = TaskSpec(task=TaskKind.REASONING, quality=Quality.HIGH,
                    reference_consistency_critical=True)

    def build_user(self, payload: tuple[Storyboard, str, str]) -> str:
        storyboard, avatar_id, descripcion = payload
        escenarios = sorted({c.scenario for c in storyboard.clips})
        return (
            f"Construye la ficha de identidad del avatar.\n\n"
            f"AVATAR ID: {avatar_id}\n"
            f"DESCRIPCIÓN PEDIDA: {descripcion}\n\n"
            f"ESCENARIOS QUE TENDRÁ QUE HABITAR:\n"
            + "\n".join(f"- {e}" for e in escenarios) + "\n\n"
            f"ACCIONES DEL STORYBOARD:\n"
            + "\n".join(f"- {c.clip_id}: {c.action_summary}"
                        for c in storyboard.clips) + "\n\n"
            f"Usa avatar_id '{avatar_id}'. Ningún rasgo físico puede quedar "
            f"vago: si no tienes el dato, decídelo tú con precisión."
        )


class ImagePromptAgent(Agent[ImagePrompt]):
    number = 7
    name = "image_prompt_engineer"
    contract = ImagePrompt
    spec = TaskSpec(task=TaskKind.STRUCTURED,
                    reference_consistency_critical=True)
    temperature = 0.7
    max_tokens = 2048

    def build_user(self, payload: tuple[CharacterBible, Storyboard, str]) -> str:
        bible, storyboard, clip_id = payload
        clip = next((c for c in storyboard.clips if c.clip_id == clip_id), None)
        if clip is None:
            raise ValueError(
                f"El clip {clip_id} no existe en el storyboard "
                f"v{storyboard.version}."
            )

        return (
            f"Escribe el prompt de imagen para un clip.\n\n"
            f"CLIP {clip.clip_id}:\n{clip.model_dump_json(indent=2)}\n\n"
            f"IDENTIDAD DEL AVATAR (ya tiene referencias generadas; "
            f"ancla en ellas, no la redescribas):\n{_json(bible)}\n\n"
            f"Usa avatar_id '{bible.avatar_id}' y clip_id '{clip_id}'.\n"
            f"Toma al menos dos imperfecciones de natural_imperfections o "
            f"propias de la escena."
        )
