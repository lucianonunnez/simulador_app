"""
Configuración centralizada de logging.

Objetivos:
- Un único punto de inicialización (`setup_logging`), idempotente.
- Logs de aplicación (operación) separados de logs de **auditoría**
  (eventos relevantes para seguridad/compliance: login, carga de datos,
  exportaciones).
- Formato configurable por entorno: texto legible en desarrollo, JSON en
  producción para ingestión por un colector (ELK / Loki / CloudWatch).
- Nunca se registran datos sensibles en claro (contraseñas, hashes, contenido
  de los datasets). Solo identificadores y metadatos del evento.

Variables de entorno:
    LOG_LEVEL    DEBUG | INFO | WARNING | ERROR        (default: INFO)
    LOG_FORMAT   text | json                            (default: text)

Uso:
    from core.logging_config import setup_logging, get_logger, audit

    setup_logging()                 # una vez, al arrancar la app
    log = get_logger(__name__)
    log.info("Procesando %s filas", n)

    audit("login_success", username="luciano", role="admin")
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

# ============================================================================
# CONSTANTES
# ============================================================================
APP_LOGGER = "simulador"
AUDIT_LOGGER = "simulador.audit"

_DEFAULT_LEVEL = "INFO"
_DEFAULT_FORMAT = "text"

# Claves cuyo valor jamás debe loguearse en claro.
_SENSITIVE_KEYS = {"password", "passwd", "pwd", "hash", "cookie_key", "token", "secret"}

_configured = False


# ============================================================================
# FORMATTERS
# ============================================================================
class _JsonFormatter(logging.Formatter):
    """Formatea cada registro como una línea JSON (apto para colectores)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Campos extra inyectados vía `extra={"fields": {...}}`
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(_redact(fields))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _TextFormatter(logging.Formatter):
    """Formato legible para desarrollo, con campos extra al final."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict) and fields:
            extra = " ".join(f"{k}={v}" for k, v in _redact(fields).items())
            return f"{base} | {extra}"
        return base


def _redact(fields: dict[str, Any]) -> dict[str, Any]:
    """Reemplaza por '***' cualquier valor cuya clave sea sensible."""
    out: dict[str, Any] = {}
    for k, v in fields.items():
        out[k] = "***" if k.lower() in _SENSITIVE_KEYS else v
    return out


# ============================================================================
# SETUP
# ============================================================================
def setup_logging() -> None:
    """
    Inicializa el logging de la aplicación. Idempotente: llamarlo varias veces
    (por ejemplo en cada rerun de Streamlit) no duplica handlers.
    """
    global _configured
    if _configured:
        return

    level = os.getenv("LOG_LEVEL", _DEFAULT_LEVEL).upper()
    fmt = os.getenv("LOG_FORMAT", _DEFAULT_FORMAT).lower()
    formatter = _JsonFormatter() if fmt == "json" else _TextFormatter()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger(APP_LOGGER)
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
    # Evita que los registros suban al root global y se dupliquen.
    root.propagate = False

    _configured = True
    root.info("Logging inicializado", extra={"fields": {"level": level, "format": fmt}})


def get_logger(name: str) -> logging.Logger:
    """
    Devuelve un logger hijo del namespace de la app.

    `get_logger(__name__)` produce p.ej. `simulador.core.data_loader`.
    """
    suffix = name.split(".")[-1] if name else "app"
    return logging.getLogger(f"{APP_LOGGER}.{suffix}")


# ============================================================================
# AUDITORÍA
# ============================================================================
def audit(event: str, **fields: Any) -> None:
    """
    Registra un evento de auditoría (seguridad / compliance).

    Ejemplos de eventos: `login_success`, `login_failure`, `logout`,
    `data_loaded`, `export_csv`, `model_loaded`.

    Los valores se redactan automáticamente si la clave es sensible.
    No pasar nunca contenido de datasets ni contraseñas en claro.
    """
    logger = logging.getLogger(AUDIT_LOGGER)
    logger.info(event, extra={"fields": {"event": event, **fields}})
