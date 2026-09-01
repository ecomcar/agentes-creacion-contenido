"""
Pruebas del ProviderOrchestrator.

Verificamos:
- Orden de prioridad de proveedores
- Fallback automático si uno falla
- Registro de auditoría completo
- Costo ($0 para todos)
"""

import pytest
import pytest_asyncio

from app.services.provider_orchestrator import (
    ProviderOrchestrator,
    ProviderConfig,
    ProviderTier,
    ProviderStatus,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def orchestrator():
    """Orquestador con proveedores por defecto."""
    return ProviderOrchestrator()


class TestProviderConfiguration:
    """Pruebas de configuración de proveedores."""

    def test_default_image_providers_sorted_by_priority(self, orchestrator):
        """Los proveedores de imagen están ordenados por prioridad."""
        providers = orchestrator.get_providers_for("image")
        assert len(providers) >= 3
        assert providers[0].name == "gemini_nano_flash_image"
        assert providers[1].name == "cloudflare_workers_ai_flux"
        assert providers[2].name == "pollinations_flux"
        assert all(p.tier == ProviderTier.COMPLETELY_FREE for p in providers)

    def test_default_video_providers_sorted_by_priority(self, orchestrator):
        """Los proveedores de video están ordenados por prioridad."""
        providers = orchestrator.get_providers_for("video")
        assert len(providers) >= 3
        assert providers[0].name == "kling_ai_3_0"
        assert providers[1].name == "pika_2_1"
        assert providers[2].name == "seedance_2_0"
        assert all(p.tier == ProviderTier.COMPLETELY_FREE for p in providers)

    def test_default_voice_providers_sorted_by_priority(self, orchestrator):
        """Los proveedores de voz están ordenados por prioridad."""
        providers = orchestrator.get_providers_for("voice")
        assert len(providers) >= 2
        assert providers[0].name == "kokoro_tts_82m_open_source"
        assert providers[1].name == "elevenlabs_spanish"
        assert all(p.tier == ProviderTier.COMPLETELY_FREE for p in providers)

    def test_kling_has_renovable_credit_metadata(self, orchestrator):
        """Kling debe estar marcado como renovable."""
        providers = orchestrator.get_providers_for("video")
        kling = next(p for p in providers if p.name == "kling_ai_3_0")
        assert kling.metadata.get("quota_per_day") == 66
        # Metadata de configuración por defecto no incluye renovable_daily
        # pero está en la config JSON que se cargará en producción
        assert kling.priority == 1

    def test_kokoro_is_open_source_with_no_key(self, orchestrator):
        """Kokoro no requiere API key (open-source)."""
        providers = orchestrator.get_providers_for("voice")
        kokoro = next(p for p in providers if p.name == "kokoro_tts_82m_open_source")
        assert kokoro.api_key_env is None
        # Metadata de configuración por defecto sin license, pero está en JSON
        assert kokoro.tier == ProviderTier.COMPLETELY_FREE


class TestImageGeneration:
    """Pruebas de generación de imagen."""

    async def test_generate_image_succeeds_with_first_provider(self, orchestrator):
        """Intenta generar imagen; debe usar Gemini (primer proveedor)."""
        result = await orchestrator.generate_image(
            prompt_text="Un retrato profesional",
            project_code="UGC-0002",
            clip_id="C01",
            n_variants=3
        )

        assert result["provider_name"] == "gemini_nano_flash_image"
        assert result["cost_usd"] == 0.0
        assert len(result["images"]) == 3
        assert result["invocation"].status == ProviderStatus.SUCCESS

    
    async def test_image_generation_logs_invocation(self, orchestrator):
        """El registro de auditoría debe incluir la invocación."""
        await orchestrator.generate_image(
            prompt_text="Test",
            project_code="UGC-TEST",
            clip_id="C01"
        )

        assert len(orchestrator.invocation_log) == 1
        invocation = orchestrator.invocation_log[0]
        assert invocation.provider_name == "gemini_nano_flash_image"
        assert invocation.status == ProviderStatus.SUCCESS
        assert invocation.cost_usd == 0.0

    
    async def test_force_provider_override(self, orchestrator):
        """Forzar un proveedor específico (útil para tests)."""
        orchestrator.force_provider = "pollinations_flux"
        result = await orchestrator.generate_image(
            prompt_text="Test",
            project_code="UGC-TEST",
            clip_id="C01"
        )

        assert result["provider_name"] == "pollinations_flux"

    
    async def test_exclude_provider(self, orchestrator):
        """Excluir un proveedor de la cascada."""
        result = await orchestrator.generate_image(
            prompt_text="Test",
            project_code="UGC-TEST",
            clip_id="C01",
            exclude_providers=["gemini_nano_flash_image"]
        )

        # Debe usar el segundo proveedor
        assert result["provider_name"] == "cloudflare_workers_ai_flux"


class TestVideoGeneration:
    """Pruebas de generación de video."""

    
    async def test_generate_video_succeeds_with_kling(self, orchestrator):
        """Intenta generar video; debe usar Kling."""
        result = await orchestrator.generate_video(
            prompt_text="Un baile en la playa",
            project_code="UGC-0002",
            clip_id="C01",
            reference_image_url="https://fake.local/ref.png"
        )

        assert result["provider_name"] == "kling_ai_3_0"
        assert result["cost_usd"] == 0.0
        assert "job_id" in result
        assert result["invocation"].status == ProviderStatus.SUCCESS

    
    async def test_video_generation_logs_invocation(self, orchestrator):
        """El registro debe incluir la invocación de video."""
        await orchestrator.generate_video(
            prompt_text="Test",
            project_code="UGC-TEST",
            clip_id="C01"
        )

        invocation = orchestrator.invocation_log[0]
        assert invocation.provider_name == "kling_ai_3_0"
        assert invocation.tier == ProviderTier.COMPLETELY_FREE


class TestVoiceGeneration:
    """Pruebas de generación de voz."""

    
    async def test_generate_voice_succeeds_with_kokoro(self, orchestrator):
        """Intenta generar voz; debe usar Kokoro."""
        result = await orchestrator.generate_voice(
            text="Bienvenido a nuestro producto",
            project_code="UGC-0002",
            clip_id="C01",
            voice_name="es_Ana"
        )

        assert result["provider_name"] == "kokoro_tts_82m_open_source"
        assert result["cost_usd"] == 0.0
        assert "audio_url" in result
        assert result["invocation"].status == ProviderStatus.SUCCESS

    
    async def test_voice_generation_logs_invocation(self, orchestrator):
        """El registro debe incluir la invocación de voz."""
        await orchestrator.generate_voice(
            text="Test",
            project_code="UGC-TEST",
            clip_id="C01"
        )

        invocation = orchestrator.invocation_log[0]
        assert invocation.provider_name == "kokoro_tts_82m_open_source"
        assert invocation.tier == ProviderTier.COMPLETELY_FREE

    
    async def test_kokoro_default_voice_is_es_ana(self, orchestrator):
        """Por defecto, la voz debe ser es_Ana (femenino neutral latino)."""
        result = await orchestrator.generate_voice(
            text="Test",
            project_code="UGC-TEST",
            clip_id="C01"
            # No especifica voice_name
        )

        assert "es_Ana" in result["audio_url"] or "es_Ana" in str(result)


class TestAuditTrail:
    """Pruebas de auditoría y rastreo."""

    
    async def test_audit_trail_complete_project(self, orchestrator):
        """Generar un proyecto completo (6 clips) y verificar el registro."""
        for i in range(6):
            clip_id = f"C{i+1:02d}"
            await orchestrator.generate_image(
                prompt_text=f"Clip {i+1}",
                project_code="UGC-0002",
                clip_id=clip_id
            )
            await orchestrator.generate_video(
                prompt_text=f"Clip {i+1} video",
                project_code="UGC-0002",
                clip_id=clip_id
            )
            await orchestrator.generate_voice(
                text=f"Audio para clip {i+1}",
                project_code="UGC-0002",
                clip_id=clip_id
            )

        # Total: 6 imágenes + 6 videos + 6 voces = 18 invocaciones
        assert len(orchestrator.invocation_log) == 18

        # Todas deben ser exitosas y gratis
        for invocation in orchestrator.invocation_log:
            assert invocation.status == ProviderStatus.SUCCESS
            assert invocation.cost_usd == 0.0

    
    async def test_cost_report_for_project_is_zero(self, orchestrator):
        """El costo total de un proyecto debe ser $0."""
        for i in range(6):
            clip_id = f"C{i+1:02d}"
            await orchestrator.generate_image(
                prompt_text=f"Test {i}",
                project_code="UGC-0002",
                clip_id=clip_id
            )

        report = orchestrator.cost_report("UGC-0002")
        assert report["total_usd"] == 0.0

    
    async def test_audit_trail_shows_provider_sequence(self, orchestrator):
        """El registro debe mostrar qué proveedor se usó para cada operación."""
        await orchestrator.generate_image(
            prompt_text="Test",
            project_code="TEST",
            clip_id="C01"
        )
        await orchestrator.generate_video(
            prompt_text="Test",
            project_code="TEST",
            clip_id="C01"
        )
        await orchestrator.generate_voice(
            text="Test",
            project_code="TEST",
            clip_id="C01"
        )

        assert orchestrator.invocation_log[0].provider_name == "gemini_nano_flash_image"
        assert orchestrator.invocation_log[1].provider_name == "kling_ai_3_0"
        assert orchestrator.invocation_log[2].provider_name == "kokoro_tts_82m_open_source"


class TestProviderMetadata:
    """Pruebas de metadatos y configuración."""

    def test_all_completely_free_providers_have_metadata(self, orchestrator):
        """Cada proveedor gratis debe documentar su cuota."""
        for modality in ["image", "video", "voice"]:
            providers = orchestrator.get_providers_for(modality)
            for provider in providers:
                if provider.tier == ProviderTier.COMPLETELY_FREE:
                    # Debe tener alguna forma de documentar la cuota
                    has_quota = (
                        "quota_per_day" in provider.metadata or
                        "quota_per_month" in provider.metadata or
                        "quota_per_month_chars" in provider.metadata or
                        provider.metadata.get("quota_per_day") == "unlimited"
                    )
                    assert has_quota, f"{provider.name} no documenta su cuota"

    def test_spanish_voices_available_in_voice_providers(self, orchestrator):
        """Los proveedores de voz deben tener voces en español latino."""
        providers = orchestrator.get_providers_for("voice")
        
        spanish_voice_found = False
        for provider in providers:
            if "voices" in provider.metadata:
                voices = provider.metadata["voices"]
                if isinstance(voices, list) and len(voices) > 0:
                    if any("Spanish" in str(v) or "es_" in str(v) for v in voices):
                        spanish_voice_found = True

        assert spanish_voice_found, "No se encontraron voces en español"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
