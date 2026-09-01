"""
Orquestador de Proveedores Multi-Tier con Fallback Automático.

Diseño: **Un proyecto completo cuesta $0 usando solo APIs gratuitas**.

IMAGEN:
  1. Gemini Nano Flash (500/día, gratis)
  2. Cloudflare Workers AI (~2,000/día, gratis)
  3. Pollinations (∞, gratis)

VIDEO:
  1. Kling AI 3.0 (66 créditos/día ≈ 6-7 videos 5seg @ 720p, gratis + renovable)
  2. Pika 2.1 (150 créditos/día, gratis + renovable)
  3. Seedance 2.0 (100 créditos/día, gratis + renovable)

VOZ:
  1. Kokoro TTS 82M (ilimitado, open-source, Apache 2.0, gratis)
  2. ElevenLabs (10K chars/mes gratis, renovable)

La orquestación:
- Intenta cada proveedor en orden de prioridad
- Si uno falla → pasa automáticamente al siguiente
- Registra cuál proveedor se usó y por qué
- Permite "forzar" un proveedor específico (para tests o desarrollo)
- Audita el costo real vs presupuesto
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# Tipos y Enums
# ============================================================================

class ProviderTier(str, Enum):
    """Nivel de cada proveedor: qué tan crítico es para la operación."""

    COMPLETELY_FREE = "completely_free"    # Sin tarjeta, cuota renovable
    FREE_INITIAL_CREDIT = "free_initial_credit"  # Crédito gratis inicial
    PAID = "paid"                          # Pago real


class ProviderStatus(str, Enum):
    """Estado del proveedor en una invocación."""

    SUCCESS = "success"                    # Funcionó
    FAILED = "failed"                      # Error recoverable (sin gastar)
    RATE_LIMITED = "rate_limited"         # Cuota agotada
    BUDGET_EXCEEDED = "budget_exceeded"   # Presupuesto excedido
    INVALID_CONFIG = "invalid_config"     # No está configurado
    SKIPPED = "skipped"                   # Se saltó (forzado/no prioritario)


class ProviderInvocation(BaseModel):
    """Registro de un intento de proveedor."""

    provider_name: str
    tier: ProviderTier
    priority: int
    status: ProviderStatus
    reason: str | None = None
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    result_id: str | None = None         # ID del asset/job generado


class ProviderConfig(BaseModel):
    """Configuración de un proveedor."""

    name: str
    tier: ProviderTier
    priority: int
    api_key_env: str | None = None
    enabled: bool = True
    max_retries: int = 1
    timeout_seconds: int = 30
    metadata: dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# Configuración por defecto (se puede sobrescribir con .env o config.json)
# ============================================================================

DEFAULT_IMAGE_PROVIDERS = [
    ProviderConfig(
        name="gemini_nano_flash_image",
        tier=ProviderTier.COMPLETELY_FREE,
        priority=1,
        api_key_env="GOOGLE_GENERATIVE_AI_KEY",
        metadata={"quota_per_day": 500, "model": "gemini-2.5-flash-image"}
    ),
    ProviderConfig(
        name="cloudflare_workers_ai_flux",
        tier=ProviderTier.COMPLETELY_FREE,
        priority=2,
        api_key_env="CLOUDFLARE_API_TOKEN",
        metadata={"quota_per_day": 2000, "neurons_per_day": 10000}
    ),
    ProviderConfig(
        name="pollinations_flux",
        tier=ProviderTier.COMPLETELY_FREE,
        priority=3,
        api_key_env=None,  # No requiere key
        metadata={"quota_per_day": "unlimited"}
    ),
]

DEFAULT_VIDEO_PROVIDERS = [
    ProviderConfig(
        name="kling_ai_3_0",
        tier=ProviderTier.COMPLETELY_FREE,
        priority=1,
        api_key_env="KLING_API_KEY",
        metadata={"quota_per_day": 66, "credits_per_5sec_video": 10}
    ),
    ProviderConfig(
        name="pika_2_1",
        tier=ProviderTier.COMPLETELY_FREE,
        priority=2,
        api_key_env="PIKA_API_KEY",
        metadata={"quota_per_day": 150}
    ),
    ProviderConfig(
        name="seedance_2_0",
        tier=ProviderTier.COMPLETELY_FREE,
        priority=3,
        api_key_env="SEEDANCE_API_KEY",
        metadata={"quota_per_day": 100}
    ),
]

DEFAULT_VOICE_PROVIDERS = [
    ProviderConfig(
        name="kokoro_tts_82m_open_source",
        tier=ProviderTier.COMPLETELY_FREE,
        priority=1,
        api_key_env=None,  # Open-source, no key
        metadata={
            "quota_per_day": "unlimited",
            "voices": ["es_Ana", "es_Diego", "es_Elena"],
            "quality": "high",
            "latin_american_neutral": True
        }
    ),
    ProviderConfig(
        name="elevenlabs_spanish",
        tier=ProviderTier.COMPLETELY_FREE,
        priority=2,
        api_key_env="ELEVENLABS_API_KEY",
        metadata={"quota_per_month_chars": 10000}
    ),
]


# ============================================================================
# Orquestador Multi-Proveedor
# ============================================================================

class ProviderOrchestrator:
    """
    Gestiona el intento automático de múltiples proveedores en cascada.

    Cada tipo de generación (imagen, video, voz) tiene su propia lista de
    proveedores ordenada por prioridad. Si uno falla (sin gastar dinero),
    se pasa al siguiente.

    Uso típico:

    ```python
    orchestrator = ProviderOrchestrator()

    # Generar imagen: intenta Gemini → Cloudflare → Pollinations
    result = await orchestrator.generate_image(
        prompt=image_prompt,
        project_code="UGC-0002",
        clip_id="C01"
    )
    # result.provider_name = "gemini_nano_flash_image"
    # result.cost_usd = 0.0
    # result.images = [...]

    # Generar video: intenta Kling → Pika → Seedance
    result = await orchestrator.generate_video(
        prompt=video_prompt,
        project_code="UGC-0002",
        clip_id="C01"
    )
    # result.provider_name = "kling_ai_3_0"
    # result.cost_usd = 0.0
    ```
    """

    def __init__(self,
                 image_providers: list[ProviderConfig] | None = None,
                 video_providers: list[ProviderConfig] | None = None,
                 voice_providers: list[ProviderConfig] | None = None,
                 force_provider_for_tests: str | None = None):
        """
        Args:
            image_providers: Lista de proveedores de imagen (en orden de prioridad)
            video_providers: Lista de proveedores de video
            voice_providers: Lista de proveedores de voz
            force_provider_for_tests: Si se especifica, SOLO usa este proveedor
                (útil para tests). Ej: "gemini_nano_flash_image"
        """
        self.image_providers = image_providers or DEFAULT_IMAGE_PROVIDERS
        self.video_providers = video_providers or DEFAULT_VIDEO_PROVIDERS
        self.voice_providers = voice_providers or DEFAULT_VOICE_PROVIDERS

        self.force_provider = force_provider_for_tests

        # Historial de invocaciones
        self.invocation_log: list[ProviderInvocation] = []

        # Contadores de cuota por día (reset manual o automático)
        self.quota_usage: dict[str, dict[str, int]] = {}

        logger.info(
            f"ProviderOrchestrator inicializado con "
            f"{len(self.image_providers)} proveedores de imagen, "
            f"{len(self.video_providers)} de video, "
            f"{len(self.voice_providers)} de voz"
        )

    # ========================================================================
    # Métodos de Orquestación
    # ========================================================================

    def get_providers_for(self, modality: Literal["image", "video", "voice"],
                        exclude: list[str] | None = None) -> list[ProviderConfig]:
        """
        Obtiene la lista de proveedores para una modalidad, en orden de
        prioridad, excluyendo los especificados.
        """
        if modality == "image":
            candidates = self.image_providers
        elif modality == "video":
            candidates = self.video_providers
        elif modality == "voice":
            candidates = self.voice_providers
        else:
            raise ValueError(f"Modalidad desconocida: {modality}")

        exclude = exclude or []
        return sorted(
            [p for p in candidates if p.enabled and p.name not in exclude],
            key=lambda p: p.priority
        )

    def log_invocation(self, invocation: ProviderInvocation) -> None:
        """Registra un intento de proveedor."""
        self.invocation_log.append(invocation)
        logger.info(
            f"[{invocation.provider_name}] {invocation.status.value}: "
            f"{invocation.reason or 'OK'} "
            f"(cost=${invocation.cost_usd:.4f}, "
            f"duration={invocation.duration_seconds:.2f}s)"
        )

    def get_audit_trail_for(self, project_code: str,
                           modality: str | None = None) -> list[ProviderInvocation]:
        """Obtiene el historial de invocaciones para un proyecto."""
        invocations = self.invocation_log
        if modality:
            # Filtrar por modalidad (si la invocación tiene ese campo)
            invocations = [i for i in invocations if getattr(i, 'modality', None) == modality]
        return invocations

    def cost_report(self, project_code: str) -> dict[str, float]:
        """Suma el costo de todas las invocaciones de un proyecto."""
        return {
            "total_usd": sum(
                i.cost_usd for i in self.invocation_log
                if hasattr(i, 'project_code') and i.project_code == project_code
            ),
            "by_provider": {
                name: sum(
                    i.cost_usd for i in self.invocation_log
                    if i.provider_name == name
                )
                for name in {i.provider_name for i in self.invocation_log}
            }
        }

    # ========================================================================
    # Métodos simulados (en producción, estos llamarían a los servicios reales)
    # ========================================================================

    async def generate_image(
        self,
        prompt_text: str,
        project_code: str,
        clip_id: str,
        n_variants: int = 3,
        exclude_providers: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Intenta generar una imagen usando múltiples proveedores en cascada.

        Retorna un dict con:
        - provider_name: str (qué proveedor generó)
        - cost_usd: float
        - images: list[dict] (URLs)
        - invocation: ProviderInvocation (el registro)
        """
        modality = "image"
        candidates = self.get_providers_for(modality, exclude=exclude_providers)

        if self.force_provider:
            candidates = [p for p in candidates if p.name == self.force_provider]
            if not candidates:
                raise ValueError(
                    f"Proveedor forzado {self.force_provider} no disponible "
                    f"para {modality}"
                )

        for provider_config in candidates:
            start = datetime.now(timezone.utc)

            try:
                # En producción, aquí iría el llamado real al proveedor
                # Por ahora, simulamos un resultado exitoso
                images = await self._simulate_image_generation(
                    provider_name=provider_config.name,
                    prompt=prompt_text,
                    n_variants=n_variants
                )

                duration = (datetime.now(timezone.utc) - start).total_seconds()
                cost = 0.0  # Todos los proveedores de imagen son gratis

                invocation = ProviderInvocation(
                    provider_name=provider_config.name,
                    tier=provider_config.tier,
                    priority=provider_config.priority,
                    status=ProviderStatus.SUCCESS,
                    cost_usd=cost,
                    duration_seconds=duration,
                    result_id=f"{project_code}_{clip_id}_img",
                )

                self.log_invocation(invocation)

                return {
                    "provider_name": provider_config.name,
                    "tier": provider_config.tier,
                    "cost_usd": cost,
                    "images": images,
                    "invocation": invocation,
                }

            except Exception as e:
                duration = (datetime.now(timezone.utc) - start).total_seconds()

                invocation = ProviderInvocation(
                    provider_name=provider_config.name,
                    tier=provider_config.tier,
                    priority=provider_config.priority,
                    status=ProviderStatus.FAILED,
                    reason=str(e),
                    duration_seconds=duration,
                )

                self.log_invocation(invocation)
                logger.warning(f"Proveedor {provider_config.name} falló: {e}")
                continue

        # Si llegamos aquí, todos fallaron
        raise RuntimeError(
            f"Todos los proveedores de {modality} fallaron para "
            f"{project_code}/{clip_id}"
        )

    async def generate_video(
        self,
        prompt_text: str,
        project_code: str,
        clip_id: str,
        reference_image_url: str | None = None,
        exclude_providers: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Intenta generar un video usando múltiples proveedores en cascada.

        Retorna un dict con:
        - provider_name: str
        - cost_usd: float
        - job_id: str (para sondeo)
        - invocation: ProviderInvocation
        """
        modality = "video"
        candidates = self.get_providers_for(modality, exclude=exclude_providers)

        if self.force_provider:
            candidates = [p for p in candidates if p.name == self.force_provider]
            if not candidates:
                raise ValueError(
                    f"Proveedor forzado {self.force_provider} no disponible "
                    f"para {modality}"
                )

        for provider_config in candidates:
            start = datetime.now(timezone.utc)

            try:
                # En producción, aquí iría el llamado real al proveedor
                job_id = await self._simulate_video_submission(
                    provider_name=provider_config.name,
                    prompt=prompt_text,
                    reference_url=reference_image_url
                )

                duration = (datetime.now(timezone.utc) - start).total_seconds()
                cost = 0.0  # Todos los proveedores de video son gratis (crédito renovable)

                invocation = ProviderInvocation(
                    provider_name=provider_config.name,
                    tier=provider_config.tier,
                    priority=provider_config.priority,
                    status=ProviderStatus.SUCCESS,
                    cost_usd=cost,
                    duration_seconds=duration,
                    result_id=job_id,
                )

                self.log_invocation(invocation)

                return {
                    "provider_name": provider_config.name,
                    "tier": provider_config.tier,
                    "cost_usd": cost,
                    "job_id": job_id,
                    "invocation": invocation,
                }

            except Exception as e:
                duration = (datetime.now(timezone.utc) - start).total_seconds()

                invocation = ProviderInvocation(
                    provider_name=provider_config.name,
                    tier=provider_config.tier,
                    priority=provider_config.priority,
                    status=ProviderStatus.FAILED,
                    reason=str(e),
                    duration_seconds=duration,
                )

                self.log_invocation(invocation)
                logger.warning(f"Proveedor {provider_config.name} falló: {e}")
                continue

        raise RuntimeError(
            f"Todos los proveedores de {modality} fallaron para "
            f"{project_code}/{clip_id}"
        )

    async def generate_voice(
        self,
        text: str,
        project_code: str,
        clip_id: str,
        voice_name: str = "es_Ana",
        exclude_providers: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Intenta generar voz usando múltiples proveedores en cascada.

        Retorna un dict con:
        - provider_name: str
        - cost_usd: float
        - audio_url: str
        - invocation: ProviderInvocation
        """
        modality = "voice"
        candidates = self.get_providers_for(modality, exclude=exclude_providers)

        if self.force_provider:
            candidates = [p for p in candidates if p.name == self.force_provider]
            if not candidates:
                raise ValueError(
                    f"Proveedor forzado {self.force_provider} no disponible "
                    f"para {modality}"
                )

        for provider_config in candidates:
            start = datetime.now(timezone.utc)

            try:
                audio_url = await self._simulate_voice_generation(
                    provider_name=provider_config.name,
                    text=text,
                    voice_name=voice_name
                )

                duration = (datetime.now(timezone.utc) - start).total_seconds()
                cost = 0.0  # Todos los proveedores de voz son gratis

                invocation = ProviderInvocation(
                    provider_name=provider_config.name,
                    tier=provider_config.tier,
                    priority=provider_config.priority,
                    status=ProviderStatus.SUCCESS,
                    cost_usd=cost,
                    duration_seconds=duration,
                    result_id=f"{project_code}_{clip_id}_audio",
                )

                self.log_invocation(invocation)

                return {
                    "provider_name": provider_config.name,
                    "tier": provider_config.tier,
                    "cost_usd": cost,
                    "audio_url": audio_url,
                    "invocation": invocation,
                }

            except Exception as e:
                duration = (datetime.now(timezone.utc) - start).total_seconds()

                invocation = ProviderInvocation(
                    provider_name=provider_config.name,
                    tier=provider_config.tier,
                    priority=provider_config.priority,
                    status=ProviderStatus.FAILED,
                    reason=str(e),
                    duration_seconds=duration,
                )

                self.log_invocation(invocation)
                logger.warning(f"Proveedor {provider_config.name} falló: {e}")
                continue

        raise RuntimeError(
            f"Todos los proveedores de {modality} fallaron para "
            f"{project_code}/{clip_id}"
        )

    # ========================================================================
    # Simuladores (en producción se reemplazan con llamadas a APIs reales)
    # ========================================================================

    async def _simulate_image_generation(
        self, provider_name: str, prompt: str, n_variants: int
    ) -> list[dict[str, str]]:
        """Simula generación de imagen."""
        return [
            {"url": f"https://fake.local/{provider_name}/img_{i}.png"}
            for i in range(n_variants)
        ]

    async def _simulate_video_submission(
        self, provider_name: str, prompt: str, reference_url: str | None
    ) -> str:
        """Simula envío de video (retorna job_id)."""
        return f"job_{provider_name}_{hash(prompt) % 10000}"

    async def _simulate_voice_generation(
        self, provider_name: str, text: str, voice_name: str
    ) -> str:
        """Simula generación de voz."""
        return f"https://fake.local/{provider_name}/{voice_name}/audio.mp3"
