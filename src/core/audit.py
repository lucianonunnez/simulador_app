"""
Auditoría de acceso (login y consultas) para trazabilidad.

Escribe eventos en logs/auth_audit.log (gitignored) como JSON Lines. Valioso
para compliance de datos sensibles: deja registro de quién entró, cuándo, desde
qué IP y, si se quiere, qué prestador consultó.

Sin dependencia dura de Streamlit: la captura de IP es best-effort (si Streamlit
no está disponible o no expone headers, registra "unknown"), así que el módulo
es testeable de forma aislada.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

LOG_DIR = Path("logs")
AUDIT_FILE = LOG_DIR / "auth_audit.log"


def _client_ip() -> str:
    """
    IP del cliente, best-effort.

    Detrás de un reverse proxy (lo recomendado, ver docs/DESPLIEGUE_SEGURO.md)
    llega en X-Forwarded-For. Sirviendo HTTP plano en la LAN, Streamlit no expone
    de forma confiable la IP del socket, así que puede quedar "unknown".
    """
    try:
        import streamlit as st

        headers = st.context.headers or {}
        xff = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        real = headers.get("X-Real-Ip") or headers.get("x-real-ip")
        if real:
            return real.strip()
    except Exception:
        pass
    return "unknown"


def log_event(
    event: str,
    username: Optional[str] = None,
    success: Optional[bool] = None,
    detail: Optional[str] = None,
) -> None:
    """
    Registra un evento de auditoría (una línea JSON en logs/auth_audit.log).

    Args:
        event:    "login_success", "login_failed", "data_access", etc.
        username: usuario involucrado (si se conoce).
        success:  True/False para eventos con resultado.
        detail:   texto libre (p. ej. el prestador consultado).
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    record = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "event": event,
        "username": username or "",
        "ip": _client_ip(),
    }
    if success is not None:
        record["success"] = bool(success)
    if detail:
        record["detail"] = detail

    try:
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # La auditoría nunca debe tumbar la app: si falla el log, seguimos.
        pass
