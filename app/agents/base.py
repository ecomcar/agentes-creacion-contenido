"""
Clase base de los agentes.

Dos decisiones que se sostienen en todo el sistema:

1. **Los prompts viven en archivos, no en el código.** Se leen en runtime
   desde `app/prompts/agent_NN/vN.md`. Editar un prompt no requiere un deploy,
   y cada versión queda en git para poder medir después si V2 rinde mejor que
   V1.

2. **El agente no habla con la base de datos ni con ningún proveedor.**
   Recibe un objeto Pydantic, devuelve otro. Quien persiste es el pipeline;
   quien llama al modelo es el gateway. Por eso los agentes se testean sin
   levantar Postgres y sin gastar.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Generic, TypeVar

from ..contracts import ArtifactBase
from ..gateway import AIGateway, TaskSpec

T = TypeVar("T", bound=ArtifactBase)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class PromptNotFound(Exception):
    pass


@functools.lru_cache(maxsize=64)
def load_prompt(agent_number: int, version: int = 1) -> str:
    path = PROMPTS_DIR / f"agent_{agent_number:02d}" / f"v{version}.md"
    if not path.is_file():
        raise PromptNotFound(
            f"No existe el prompt {path.relative_to(PROMPTS_DIR.parent)}. "
            f"Los prompts se versionan como archivos; crear v{version}.md."
        )
    return path.read_text(encoding="utf-8").strip()


def available_versions(agent_number: int) -> list[int]:
    folder = PROMPTS_DIR / f"agent_{agent_number:02d}"
    if not folder.is_dir():
        return []
    versions = []
    for f in folder.glob("v*.md"):
        try:
            versions.append(int(f.stem[1:]))
        except ValueError:
            continue
    return sorted(versions)


class Agent(Generic[T]):
    """
    Un agente = número + contrato de salida + TaskSpec + prompt versionado.

    Las subclases sólo implementan `build_user()`: cómo convertir el artefacto
    de entrada en el mensaje concreto de esta ejecución.
    """

    number: int
    name: str
    contract: type[T]
    spec: TaskSpec
    max_tokens: int = 4096
    temperature: float = 1.0

    # Cada subclase puede fijar su propia versión por defecto una vez que
    # una versión nueva se valide como mejor que v1 (ver validar_prompts.py
    # --version-hooks). El parámetro del constructor sigue permitiendo
    # forzar cualquier versión para comparar, sin tocar este valor.
    default_prompt_version: int = 1

    def __init__(self, prompt_version: int | None = None):
        self.prompt_version = (prompt_version if prompt_version is not None
                               else self.default_prompt_version)

    @property
    def system_prompt(self) -> str:
        return load_prompt(self.number, self.prompt_version)

    @property
    def prompt_id(self) -> str:
        return f"AG{self.number:02d}_V{self.prompt_version}"

    def build_user(self, payload) -> str:
        raise NotImplementedError

    def run(self, gateway: AIGateway, payload, *,
            project_code: str | None = None,
            feedback: str | None = None,
            triggered_by: str = "orchestrator") -> T:
        """
        Ejecuta el agente y devuelve su artefacto ya validado.

        `feedback` es el rechazo humano de un intento anterior. Va al final
        del mensaje para que pese sobre las instrucciones generales.
        """
        user = self.build_user(payload)
        if feedback:
            user += (
                f"\n\n--- CORRECCIÓN SOLICITADA POR EL REVISOR ---\n"
                f"{feedback}\n\n"
                f"Rehaz el trabajo atendiendo específicamente a esto."
            )

        return gateway.generate_artifact(
            contract=self.contract, spec=self.spec,
            system=self.system_prompt, user=user,
            agent_number=self.number, agent_name=self.name,
            project_code=project_code, max_tokens=self.max_tokens,
            temperature=self.temperature, triggered_by=triggered_by,
        )
