"""
Proveedor de Anthropic — SDK oficial, sin capas de traducción.

Misma decisión que en el proyecto anterior: proveedor nativo en lugar de
LiteLLM o LangChain. Una capa menos entre el agente y el modelo, y los
errores llegan con su forma original.

Instalar:  pip install anthropic
Requiere:  ANTHROPIC_API_KEY en el entorno.
"""

from __future__ import annotations

import os
import time

from ..pricing import estimate_cost
from ..types import GatewayError, GenerationRequest, GenerationResponse, Usage


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, max_retries: int = 2,
                 timeout_s: float = 120.0):
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover
            raise GatewayError(
                "El SDK de Anthropic no está instalado. `pip install anthropic`."
            ) from exc

        key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            # Degradación explícita: se dice qué falta y por qué, en vez de
            # fallar más adelante con un error opaco de autenticación.
            raise GatewayError(
                "Falta ANTHROPIC_API_KEY. Es la única clave obligatoria del "
                "sistema; copiar .env.example a .env y rellenarla."
            )

        self._client = Anthropic(api_key=key, max_retries=max_retries,
                                 timeout=timeout_s)

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        if not request.model:
            raise GatewayError("El Router debe fijar el modelo antes de llamar.")

        started = time.perf_counter()
        # Construir los argumentos y quitar los que la versión instalada del
        # SDK no reconozca, en vez de asumir una firma fija. El SDK de
        # Anthropic ha cambiado su interfaz entre versiones (por ejemplo,
        # cómo se pasa 'temperature'), y fijar los kwargs a mano rompe la
        # llamada según qué versión haya instalado cada persona.
        kwargs = dict(
            model=request.model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            system=request.system,
            messages=[{"role": "user", "content": request.user}],
        )
        try:
            import inspect
            firma = inspect.signature(self._client.messages.create)
            acepta_kwargs_libres = any(
                p.kind is inspect.Parameter.VAR_KEYWORD
                for p in firma.parameters.values())
            if not acepta_kwargs_libres:
                kwargs = {k: v for k, v in kwargs.items()
                         if k in firma.parameters}
        except (ValueError, TypeError):
            # Si no se puede inspeccionar la firma (por ejemplo, está escrita
            # en C o envuelta), se intenta con todos los argumentos y se deja
            # que el manejo de abajo reintente sin 'temperature' si hace falta.
            pass

        try:
            msg = self._client.messages.create(**kwargs)
        except TypeError as exc:
            if "temperature" in str(exc) and "temperature" in kwargs:
                # Compatibilidad con versiones del SDK que reestructuraron
                # cómo se declara el muestreo. Sin 'temperature' explícito,
                # el modelo usa su valor por defecto.
                kwargs.pop("temperature")
                msg = self._client.messages.create(**kwargs)
            else:
                raise GatewayError(f"Fallo de la API de Anthropic: {exc}") from exc
        except Exception as exc:
            raise GatewayError(f"Fallo de la API de Anthropic: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)

        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        in_tok = msg.usage.input_tokens
        out_tok = msg.usage.output_tokens

        return GenerationResponse(
            text=text,
            model=msg.model,
            usage=Usage(input_tokens=in_tok, output_tokens=out_tok,
                        cost_usd=estimate_cost(msg.model, in_tok, out_tok)),
            latency_ms=latency_ms,
            stop_reason=msg.stop_reason,
        )
