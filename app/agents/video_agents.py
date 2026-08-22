"""Agente 8 — Director de video (Kling o equivalente)."""

from __future__ import annotations

from ..contracts import CharacterBible, Storyboard, UGCScript, VideoPrompt
from ..gateway import TaskKind, TaskSpec
from .base import Agent

MAX_CLIP_SECONDS = 15.0


class VideoDirectorAgent(Agent[VideoPrompt]):
    number = 8
    name = "video_director"
    contract = VideoPrompt
    spec = TaskSpec(task=TaskKind.STRUCTURED)
    temperature = 0.7
    max_tokens = 2048

    def build_user(
        self,
        payload: tuple[Storyboard, UGCScript, str, str, CharacterBible | None],
    ) -> str:
        storyboard, script, clip_id, image_asset_id, bible = payload

        sb_clip = next((c for c in storyboard.clips if c.clip_id == clip_id), None)
        sc_clip = next((c for c in script.clips if c.clip_id == clip_id), None)
        if sb_clip is None or sc_clip is None:
            raise ValueError(
                f"El clip {clip_id} no existe en el storyboard y el guion."
            )

        duracion = round(sc_clip.duration, 2)
        aviso = ""
        if duracion > MAX_CLIP_SECONDS:
            # No se corrige en silencio: el agente debe declararlo para que
            # el problema vuelva al guionista, que es quien puede resolverlo.
            aviso = (
                f"\n\nATENCIÓN: el clip dura {duracion}s, por encima del "
                f"máximo de {MAX_CLIP_SECONDS}s que sostienen los modelos "
                f"actuales. Declara el problema en 'errors' y usa "
                f"duration_sec {MAX_CLIP_SECONDS}."
            )

        gestos = ""
        if bible is not None and bible.natural_imperfections:
            gestos = ("\n\nIMPERFECCIONES DEL AVATAR (úsalas en microgestures):\n"
                      + "\n".join(f"- {i}" for i in bible.natural_imperfections))

        return (
            f"Escribe el prompt de movimiento para este clip.\n\n"
            f"IMAGEN BASE YA APROBADA: {image_asset_id}\n"
            f"No redescribas al personaje, la ropa ni el fondo: ya existen en "
            f"esa imagen.\n\n"
            f"CLIP {clip_id} ({sb_clip.shot_type.value}, "
            f"{sb_clip.scenario}):\n"
            f"Acción: {sb_clip.action_summary}\n"
            f"Diálogo: \"{sc_clip.dialogue}\"\n"
            f"Duración: {duracion}s"
            f"{gestos}{aviso}\n\n"
            f"Usa clip_id '{clip_id}' e image_asset_id '{image_asset_id}'. "
            f"Rellena los siete bloques; negative_behavior es obligatorio."
        )
