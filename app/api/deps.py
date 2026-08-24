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

from fastapi import Depends
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ..agents import AGENT_REGISTRY
from ..config import Settings, get_settings
from ..db import engine_for, session_factory
from ..gateway import AIGateway
from ..gateway.providers.anthropic_provider import AnthropicProvider
from ..orchestrator import Orchestrator


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
    Sólo los agentes 1-4 (texto): son los validados y optimizados. Imagen,
    video y voz se orquestan por sus propios servicios (Image/Video/Audio
    GenerationService), no por este Orchestrator basado en agentes.
    """
    agentes = {n: cls() for n, cls in AGENT_REGISTRY.items() if n in (1, 2, 3, 4)}
    return Orchestrator(gateway=gateway, agents=agentes)
