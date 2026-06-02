"""
Asistente de IA (capa experimental — desactivada por defecto).

Esta es la base para la futura integración de un copiloto analítico sobre el
simulador: permitir que un ejecutivo pregunte en lenguaje natural
("¿qué prestador explica el mayor desvío en marzo?", "resumime el impacto del
escenario que acabo de simular") y reciba una respuesta fundamentada en los
DataFrames ya calculados por la app.

Principios de diseño:
- **Apagado por defecto.** Se habilita con `AI_ASSISTANT_ENABLED=true` y una
  `ANTHROPIC_API_KEY`. Si falta cualquiera de los dos, la app funciona igual y
  esta capa simplemente no se activa.
- **Lazy import.** El SDK de Anthropic NO está en `requirements.txt` del core;
  se importa solo si la feature está activa, para no engrosar la imagen ni
  introducir una dependencia en producción antes de tiempo.
- **Sin datos crudos hacia el modelo.** Solo se envían agregados / resúmenes
  que el usuario ya ve en pantalla, nunca el dataset completo ni PII. Ver
  `docs/AI_ROADMAP.md` y `docs/SECURITY.md`.
- **Prompt caching.** El bloque de instrucciones del sistema (largo y estable)
  se marca con `cache_control` para abaratar y acelerar llamadas repetidas.

Estado: STUB. La función `ask()` está implementada de forma completa pero la
integración con la UI se hará en el hito correspondiente del roadmap.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from core.logging_config import audit, get_logger

log = get_logger(__name__)

# Modelo por defecto: Claude más reciente de la familia 4.x para análisis.
DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024

# Instrucciones de sistema: estables entre llamadas → candidatas a cache.
_SYSTEM_PROMPT = """\
Sos un asistente analítico para ejecutivos del área de costos médicos.
Respondés en español rioplatense, de forma concisa y orientada a la decisión.
Trabajás SIEMPRE sobre los datos agregados que se te entregan en el contexto;
si la respuesta no se puede deducir de esos datos, lo decís explícitamente en
lugar de inventar. No revelás detalles de implementación ni datos personales.
Cuando cites cifras, mantené el formato de moneda y porcentajes del contexto.
"""


@dataclass(frozen=True)
class AssistantConfig:
    """Configuración resuelta desde el entorno."""

    enabled: bool
    api_key: str | None
    model: str

    @classmethod
    def from_env(cls) -> "AssistantConfig":
        return cls(
            enabled=os.getenv("AI_ASSISTANT_ENABLED", "false").lower() == "true",
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            model=os.getenv("AI_ASSISTANT_MODEL", DEFAULT_MODEL),
        )


def is_available() -> bool:
    """True solo si la feature está activa y hay credencial configurada."""
    cfg = AssistantConfig.from_env()
    return cfg.enabled and bool(cfg.api_key)


def ask(question: str, context: str, *, config: AssistantConfig | None = None) -> str:
    """
    Envía una pregunta del usuario junto a un `context` (resumen agregado de la
    pantalla actual) y devuelve la respuesta del modelo.

    Args:
        question: pregunta en lenguaje natural del ejecutivo.
        context:  texto ya agregado/anonimizado (métricas, top-N, escenario).
                  NUNCA pasar el dataset completo ni columnas con PII.
        config:   override opcional; por defecto se resuelve del entorno.

    Returns:
        La respuesta en texto. Si la feature está desactivada, devuelve un
        mensaje indicándolo (no lanza excepción), para que la UI degrade suave.

    Raises:
        RuntimeError: si la feature está activa pero el SDK no está instalado.
    """
    cfg = config or AssistantConfig.from_env()

    if not cfg.enabled or not cfg.api_key:
        return (
            "El asistente de IA está desactivado en este entorno. "
            "Configurá AI_ASSISTANT_ENABLED=true y ANTHROPIC_API_KEY para habilitarlo."
        )

    try:
        import anthropic  # lazy: solo si la feature está activa
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise RuntimeError(
            "AI_ASSISTANT_ENABLED=true pero el paquete 'anthropic' no está instalado. "
            "Agregá 'anthropic>=0.40.0' al entorno para usar el asistente."
        ) from exc

    client = anthropic.Anthropic(api_key=cfg.api_key)

    # `cache_control` sobre el system prompt: se reutiliza el prefijo estable
    # entre llamadas, reduciendo costo y latencia.
    system_blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": _SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    user_content = f"Contexto (datos agregados de la pantalla):\n{context}\n\nPregunta:\n{question}"

    audit("ai_query", model=cfg.model, chars_context=len(context))

    response = client.messages.create(
        model=cfg.model,
        max_tokens=MAX_TOKENS,
        system=system_blocks,
        messages=[{"role": "user", "content": user_content}],
    )

    # La respuesta es una lista de bloques; concatenamos el texto.
    return "".join(block.text for block in response.content if block.type == "text")
