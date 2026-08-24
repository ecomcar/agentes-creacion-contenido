"""
Aplicación FastAPI.

Sólo cubre lo que ya está validado y probado: proyectos, clips, artefactos,
assets, y las cuatro primeras etapas (agentes de texto 1-4). Imagen, video
y voz no tienen endpoints todavía — sus servicios existen
(Image/Video/AudioGenerationService) pero exponerlos por HTTP es el
siguiente paso, no éste.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from pathlib import Path

from ..gateway.types import BudgetExceeded, GatewayError, RepairFailed
from .routers import artifacts, assets, projects, stages

app = FastAPI(
    title="Sistema UGC — API",
    description="Investigación, estrategia, hooks y guion para anuncios "
               "UGC generados por IA.",
    version="0.1.0",
)

app.include_router(projects.router)
app.include_router(artifacts.router)
app.include_router(assets.router)
app.include_router(stages.router)

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
