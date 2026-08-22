"""
Configuración central.

Todo se lee de `.env`. La única variable obligatoria sigue siendo
ANTHROPIC_API_KEY; el resto tiene valores por defecto conservadores.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore",
                                      case_sensitive=False)

    # -- modelos --
    anthropic_api_key: str = ""
    force_model: str | None = None

    # -- base de datos --
    # El valor por defecto apunta al docker-compose incluido.
    database_url: str = Field(
        default="postgresql+psycopg://ugc:ugc@localhost:5432/ugc")
    db_echo: bool = False

    # -- topes de gasto --
    max_cost_per_call_usd: float = 0.50
    max_cost_per_project_usd: float = 5.00
    max_cost_per_session_usd: float = 25.00
    max_image_cost_per_clip_usd: float = 1.00
    max_image_cost_per_project_usd: float = 10.00
    max_video_cost_per_clip_usd: float = 2.00
    max_video_cost_per_project_usd: float = 20.00

    # -- topes de reintento --
    max_retry_strategy: int = 2
    max_retry_hooks: int = 2
    max_retry_script: int = 2
    max_retry_storyboard: int = 2
    max_retry_image: int = 3
    max_retry_video: int = 3
    max_audit_cycles: int = 3
    max_polls_per_job: int = 120

    # -- memoria creativa --
    creative_memory_ttl_days: int = 180

    # -- proveedores de generación (fases 4-5) --
    nano_banana_api_key: str | None = None
    kling_api_key: str | None = None
    voice_api_key: str | None = None
    storage_bucket: str | None = None

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def missing_required(self) -> list[str]:
        """Qué falta para poder ejecutar de verdad."""
        faltan = []
        if not self.anthropic_api_key:
            faltan.append("ANTHROPIC_API_KEY")
        return faltan


@lru_cache
def get_settings() -> Settings:
    return Settings()
