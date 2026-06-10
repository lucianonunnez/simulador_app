"""
Rate-limit de intentos de login (lockout básico anti fuerza bruta).

Estado en memoria del proceso: sobrevive a los reruns y a las sesiones de
Streamlit (todas comparten el proceso del servidor), pero se resetea al
reiniciar la app. Suficiente como fricción real para un MVP en LAN; para
producción correspondería persistirlo (el log de auditoría ya registra los
intentos fallidos con IP).

Sin dependencia de Streamlit: testeable de forma aislada (el reloj se
inyecta por parámetro).
"""

from __future__ import annotations

import time
from collections import defaultdict

# 5 intentos fallidos en 10 minutos -> bloqueo de 15 minutos.
MAX_INTENTOS = 5
VENTANA_SEG = 600
BLOQUEO_SEG = 900

# {clave (username o "global"): [timestamps de fallos]}
_fallos: dict[str, list[float]] = defaultdict(list)


def registrar_fallo(clave: str, ahora: float | None = None) -> None:
    """Registra un intento de login fallido para la clave dada."""
    ahora = time.time() if ahora is None else ahora
    _fallos[clave].append(ahora)
    # Mantener solo lo relevante (ventana + bloqueo) para no crecer sin límite.
    limite = ahora - max(VENTANA_SEG, BLOQUEO_SEG)
    _fallos[clave] = [t for t in _fallos[clave] if t >= limite]


def segundos_bloqueado(clave: str, ahora: float | None = None) -> int:
    """
    Segundos restantes de bloqueo para la clave (0 = no bloqueada).

    Bloqueada si acumuló MAX_INTENTOS fallos dentro de VENTANA_SEG; el bloqueo
    dura BLOQUEO_SEG desde el último fallo.
    """
    ahora = time.time() if ahora is None else ahora
    recientes = [t for t in _fallos.get(clave, []) if t >= ahora - VENTANA_SEG]
    if len(recientes) < MAX_INTENTOS:
        return 0
    fin_bloqueo = max(recientes) + BLOQUEO_SEG
    return max(int(fin_bloqueo - ahora), 0)


def reset(clave: str | None = None) -> None:
    """Limpia el estado (de una clave, o todo). Útil para tests y post-login OK."""
    if clave is None:
        _fallos.clear()
    else:
        _fallos.pop(clave, None)
