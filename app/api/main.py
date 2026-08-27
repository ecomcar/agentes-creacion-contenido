"""
Aplicación FastAPI.

Cubre proyectos, clips, artefactos, assets, las cuatro primeras etapas de
texto (1-4), storyboard e identidad (5-6, vía la misma máquina de
estados), y — desde esta entrega — imagen, video y voz por clip (7-9,
`routers/media.py`), reutilizando Image/Video/AudioGenerationService.
Montaje y auditoría (10-11) siguen sin endpoints todavía.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from pathlib import Path

from ..gateway.types import BudgetExceeded, GatewayError, RepairFailed
from .routers import artifacts, assets, brands, media, projects, stages

app = FastAPI(
    title="Sistema UGC — API",
    description="Investigación, estrategia, hooks, guion, storyboard, "
               "identidad, imagen, video y voz para anuncios UGC "
               "generados por IA.",
    version="0.2.0",
)

app.include_router(projects.router)
app.include_router(brands.router)
app.include_router(artifacts.router)
app.include_router(assets.router)
app.include_router(stages.router)
app.include_router(media.router)

# Panel visual — página estática que habla con esta misma API. Se monta
# DESPUÉS de los routers de la API para que /projects, /artifacts, etc.
# sigan resolviendo como JSON y no como archivos estáticos.
_static_dir = Path(__file__).resolve().parent.parent / "static"
app.mount("/panel", StaticFiles(directory=_static_dir, html=True), name="panel")


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.exception_handler(BudgetExceeded)
def budget_exceeded_handler(request, exc: BudgetExceeded):
    return JSONResponse(status_code=402, content={"detail": str(exc)})


@app.exception_handler(RepairFailed)
def repair_failed_handler(request, exc: RepairFailed):
    return JSONResponse(status_code=502, content={
        "detail": str(exc), "last_errors": exc.last_errors})


@app.exception_handler(GatewayError)
def gateway_error_handler(request, exc: GatewayError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})
