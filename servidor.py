"""
Levanta la API HTTP: `python servidor.py`

Documentación interactiva automática en http://localhost:8000/docs — ahí se
pueden probar todos los endpoints sin escribir código, incluida la
generación real (agentes 1-4) si ANTHROPIC_API_KEY está configurada.
"""

from __future__ import annotations

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.api.main:app", host="0.0.0.0", port=8000, reload=True)
