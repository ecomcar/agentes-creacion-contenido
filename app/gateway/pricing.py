"""
Precios por modelo.

ADVERTENCIA DE HONESTIDAD: los precios cambian y esta tabla envejece. Sólo
`claude-sonnet-5` está verificado (2 USD entrada / 10 USD salida por millón,
la cifra con la que se presupuestó el proyecto anterior). El resto están
marcados `verified=False` y deben confirmarse contra la documentación oficial
antes de confiar en una estimación de coste.

Se sobrescriben por `.env` sin tocar código:
    PRICE_CLAUDE_OPUS_5="15.00,75.00"
"""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict


class ModelPrice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    input_per_mtok: float
    output_per_mtok: float
    verified: bool = False
    note: str = ""

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return round(
            input_tokens / 1_000_000 * self.input_per_mtok
            + output_tokens / 1_000_000 * self.output_per_mtok,
            6,
        )


PRICES: dict[str, ModelPrice] = {
    "claude-sonnet-5": ModelPrice(
        model="claude-sonnet-5", input_per_mtok=2.00, output_per_mtok=10.00,
        verified=True, note="Cifra usada y verificada en el proyecto anterior.",
    ),
    "claude-opus-5": ModelPrice(
        model="claude-opus-5", input_per_mtok=15.00, output_per_mtok=75.00,
        verified=False, note="SIN VERIFICAR — confirmar antes de presupuestar.",
    ),
    "claude-haiku-4-5": ModelPrice(
        model="claude-haiku-4-5", input_per_mtok=1.00, output_per_mtok=5.00,
        verified=False, note="SIN VERIFICAR — confirmar antes de presupuestar.",
    ),
}


def _load_overrides() -> None:
    """Permite corregir precios desde .env sin tocar el código."""
    for name in list(PRICES):
        env_key = "PRICE_" + name.upper().replace("-", "_")
        raw = os.getenv(env_key)
        if not raw:
            continue
        try:
            inp, out = (float(x.strip()) for x in raw.split(","))
        except ValueError:
            continue
        PRICES[name] = ModelPrice(
            model=name, input_per_mtok=inp, output_per_mtok=out,
            verified=True, note=f"Definido en .env ({env_key}).",
        )


_load_overrides()


def price_for(model: str) -> ModelPrice:
    if model not in PRICES:
        # Un modelo sin precio no puede estimarse. Devolvemos coste cero pero
        # lo marcamos, en vez de inventar una cifra plausible.
        return ModelPrice(model=model, input_per_mtok=0.0, output_per_mtok=0.0,
                          verified=False, note="MODELO SIN PRECIO REGISTRADO — "
                                               "el coste reportado será 0.")
    return PRICES[model]


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    return price_for(model).cost(input_tokens, output_tokens)


def unverified_models() -> list[str]:
    return sorted(m for m, p in PRICES.items() if not p.verified)
