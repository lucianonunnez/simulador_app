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
# Umbral alternativo pensado para el bucket POR IP: más alto que el de
# username para frenar ataques distribuidos entre cuentas, sin que unos pocos
# fallos ajenos alcancen para bloquearle la cuenta (DoS) a un usuario legítimo.
MAX_INTENTOS_IP = 15

# {clave ("user:<username>", "ip:<ip>" o "global"): [timestamps de fallos]}
_fallos: dict[str, list[float]] = defaultdict(list)


def registrar_fallo(clave: str, ahora: float | None = None) -> None:
    """Registra un intento de login fallido para la clave dada."""
    ahora = time.time() if ahora is None else ahora
    _fallos[clave].append(ahora)
    # Mantener solo lo relevante (ventana + bloqueo) para no crecer sin límite.
    limite = ahora - max(VENTANA_SEG, BLOQUEO_SEG)
    _fallos[clave] = [t for t in _fallos[clave] if t >= limite]


def segundos_bloqueado(
    clave: str, ahora: float | None = None, max_intentos: int | None = None
) -> int:
    """
    Segundos restantes de bloqueo para la clave (0 = no bloqueada).

    Bloqueada si acumuló `max_intentos` fallos (default: MAX_INTENTOS) dentro
    de VENTANA_SEG; el bloqueo dura BLOQUEO_SEG desde el último fallo. El
    umbral es parametrizable porque el bucket por IP usa uno más alto
    (MAX_INTENTOS_IP) que el bucket por username.
    """
    umbral = MAX_INTENTOS if max_intentos is None else max_intentos
    ahora = time.time() if ahora is None else ahora
    recientes = [t for t in _fallos.get(clave, []) if t >= ahora - VENTANA_SEG]
    if len(recientes) < umbral:
        return 0
    fin_bloqueo = max(recientes) + BLOQUEO_SEG
    return max(int(fin_bloqueo - ahora), 0)


def reset(clave: str | None = None) -> None:
    """Limpia el estado (de una clave, o todo). Útil para tests y post-login OK."""
    if clave is None:
        _fallos.clear()
    else:
        _fallos.pop(clave, None)
