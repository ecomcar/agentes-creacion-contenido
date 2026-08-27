"""
Dependencias de FastAPI.

Todo lo que la API necesita se pide por inyección, nunca se construye
directo dentro de un endpoint. Es lo que permite que las pruebas reemplacen
la base de datos real por SQLite en memoria y el proveedor real de
Anthropic por uno falso, sin tocar el código de los endpoints.
"""

from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from fastapi import Depends, HTTPException
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..agents import AGENT_REGISTRY
from ..config import Settings, get_settings
from ..db import engine_for, session_factory
from ..gateway import AIGateway
from ..gateway.providers.anthropic_provider import AnthropicProvider
from ..gateway.providers.fal_provider import FalImageProvider
from ..gateway.providers.fal_video_provider import FalVideoProvider
from ..gateway.providers.fal_voice_provider import FalVoiceProvider
from ..gateway.providers.image_provider import ImageProvider
from ..gateway.providers.video_provider import VideoProvider
from ..gateway.providers.voice_provider import VoiceProvider
from ..orchestrator import Orchestrator
from ..services import (
    AudioGenerationService,
    ImageGenerationService,
    JobQueue,
    VideoGenerationService,
)


@lru_cache
def get_engine() -> Engine:
    """
    Un solo engine por proceso. `lru_cache` es lo que permite a las
    pruebas reemplazarlo por completo con `app.dependency_overrides`,
    sin que este engine real (Postgres) llegue a construirse.
    """
    return engine_for()


def get_session(engine: Engine = Depends(get_engine)
                ) -> Generator[Session, None, None]:
    """
    Una sesión por request. Se hace commit si el endpoint termina bien,
    rollback si lanza una excepción — el mismo patrón que `session_scope`,
    pero como dependencia de FastAPI en vez de context manager manual.
    """
    factory = session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_gateway() -> AIGateway:
    """
    Gateway con el proveedor real de Anthropic.

    Las pruebas reemplazan esto por completo (FakeProvider) vía
    `app.dependency_overrides[get_gateway]` — nunca llaman a la API real.
    """
    return AIGateway(provider=AnthropicProvider())


def get_orchestrator(gateway: AIGateway = Depends(get_gateway)) -> Orchestrator:
    """
    Agentes 1-6: texto puro, un artefacto por proyecto (no por clip). Se
    apoyan en la máquina de estados para aprobar/avanzar igual que
    investigación/estrategia/hooks/guion.

    Agentes 7-9 (ImagePrompt, VideoPrompt, VoiceDirection) se ejecutan
    aparte, vía `get_media_agents()`: son por clip, y la aprobación
    humana real ahí es elegir qué variante generada usar — no el texto
    del prompt — así que no encajan en el avance lineal de una sola
    `current_stage` por proyecto. Imagen, video y voz en sí (el gasto de
    verdad) los ejecutan Image/Video/AudioGenerationService, nunca este
    Orchestrator.
    """
    agentes = {n: cls() for n, cls in AGENT_REGISTRY.items()
              if n in (1, 2, 3, 4, 5, 6)}
    return Orchestrator(gateway=gateway, agents=agentes)


def get_media_agents() -> dict[int, object]:
    """Agentes 7-9, instanciados sueltos — ver nota en `get_orchestrator`."""
    return {n: cls() for n, cls in AGENT_REGISTRY.items() if n in (7, 8, 9)}


# -- proveedores y servicios de generación real (imagen/video/voz) -------
#
# Un solo proceso, un solo objeto por tipo de servicio durante toda la
# vida del servidor (mismo patrón que `get_engine`): es lo que permite
# que `JobQueue` seguir sondeando un video entre una request de envío y
# la siguiente de sondeo. El presupuesto gastado se re-hidrata desde la
# base en cada llamada (ver `_hydrate_spend` en el router de medios), así
# que un reinicio del servidor no hace que los topes dejen de proteger.
#
# Las pruebas nunca llegan a construir estos objetos reales: sobreescriben
# la función completa vía `app.dependency_overrides`.


def get_image_provider() -> ImageProvider:
    try:
        return FalImageProvider()
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc


def get_video_provider() -> VideoProvider:
    try:
        return FalVideoProvider()
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc


def get_voice_provider() -> VoiceProvider:
    try:
        return FalVoiceProvider()
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc


@lru_cache
def get_image_service() -> ImageGenerationService:
    settings = get_settings()
    return ImageGenerationService(
        provider=get_image_provider(),
        max_cost_per_clip_usd=settings.max_image_cost_per_clip_usd,
        max_cost_per_project_usd=settings.max_image_cost_per_project_usd,
    )


@lru_cache
def get_job_queue() -> JobQueue:
    settings = get_settings()
    return JobQueue(provider=get_video_provider(),
                    max_polls=settings.max_polls_per_job)


@lru_cache
def get_video_service() -> VideoGenerationService:
    settings = get_settings()
    return VideoGenerationService(
        queue=get_job_queue(),
        max_cost_per_clip_usd=settings.max_video_cost_per_clip_usd,
        max_cost_per_project_usd=settings.max_video_cost_per_project_usd,
    )


@lru_cache
def get_audio_service() -> AudioGenerationService:
    return AudioGenerationService(provider=get_voice_provider())
