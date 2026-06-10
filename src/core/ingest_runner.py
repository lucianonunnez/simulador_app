"""
Puente app -> ingesta: detectar archivos nuevos en data/raw/ y unificarlos
a DuckDB desde la propia UI, sin pasar por la terminal.

- listar_pendientes(): qué archivos de data/raw/ todavía no están en la base
  (por hash SHA-256 contra _ingest_log — el mismo criterio del script).
- ejecutar_ingesta(): corre scripts/ingest.py --archivar como SUBPROCESO del
  mismo Python (venv). Reusa el script tal cual para no duplicar lógica.
  IMPORTANTE: el llamador debe cerrar antes las conexiones read-only de la
  app (DuckDB no admite un escritor con lectores abiertos).

Asume CWD = raíz del repo (la misma convención que db.DB_PATH y data/raw).
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

RAW_DIR = Path("data") / "raw"
INBOX_DIR = Path("data") / "a_procesar"
CARPETAS = (RAW_DIR / "consumo", RAW_DIR / "valores", INBOX_DIR)
SCRIPT_INGESTA = Path("scripts") / "ingest.py"


def _archivos_entrada() -> list[Path]:
    """xlsx/csv en las carpetas de entrada (sin recursión: ignora procesados/)."""
    archivos: list[Path] = []
    for d in CARPETAS:
        if d.exists():
            archivos += sorted(d.glob("*.xlsx")) + sorted(d.glob("*.csv"))
    return archivos


def estado_carpetas() -> tuple:
    """Huella barata de data/raw (nombre, tamaño, mtime): cambia cuando el
    usuario suelta archivos nuevos. Sirve de clave de caché del escaneo."""
    return tuple(
        (str(p), p.stat().st_size, p.stat().st_mtime_ns)
        for p in _archivos_entrada()
    )


def _hash_archivo(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def listar_pendientes() -> list[str]:
    """Nombres de los archivos de data/raw/ que aún NO fueron ingeridos."""
    archivos = _archivos_entrada()
    if not archivos:
        return []

    ya_ingeridos: set[str] = set()
    from core import db

    if db.DB_PATH.exists():
        try:
            con = db.get_connection(read_only=True)
            try:
                if db.table_exists(con, db.INGEST_LOG_TABLE):
                    ya_ingeridos = {
                        r[0]
                        for r in con.execute(
                            f"SELECT file_hash FROM {db.INGEST_LOG_TABLE}"
                        ).fetchall()
                    }
            finally:
                con.close()
        except Exception:
            # Base bloqueada o ilegible: reportamos todo como pendiente y el
            # propio script de ingesta resolverá (es idempotente por hash).
            pass

    return [p.name for p in archivos if _hash_archivo(p) not in ya_ingeridos]


def ejecutar_ingesta(mes: str | None = None) -> tuple[bool, str]:
    """
    Corre la ingesta (con --archivar) y devuelve (ok, salida_de_consola).

    El subproceso evita duplicar la lógica del script y aísla el lock RW:
    cuando termina, la base queda libre para que la app reabra sus lectores.
    """
    cmd = [sys.executable, str(SCRIPT_INGESTA), "--archivar"]
    if mes:
        cmd += ["--mes", mes]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return False, "La ingesta superó los 30 minutos y fue cancelada."
    salida = (res.stdout or "") + (res.stderr or "")
    return res.returncode == 0, salida


def _leer_headers(path: Path) -> list[str] | None:
    """Encabezados crudos del archivo (chequeo barato, sin cargar los datos)."""
    import pandas as pd

    try:
        if path.suffix.lower() == ".csv":
            from core.excel_utils import _decode_text

            primera = _decode_text(path.read_bytes()[:65536]).split("\n", 1)[0]
            return [h.strip().strip('"') for h in primera.split(",")]
        df = pd.read_excel(path, nrows=0, engine="openpyxl")
        return [str(c).strip() for c in df.columns]
    except Exception:
        return None


def _necesita_mes(path: Path) -> bool:
    """
    True si el archivo es un consumo que NO puede resolver su período solo.

    El período se resuelve, en orden: columna 'Mes' en el archivo > período en
    el NOMBRE ('05-2026-Consumo-1584.xlsx'). Los archivos de valores nunca lo
    necesitan (traen 'Mes Vigencia' como dato propio).
    """
    from core.excel_utils import clasificar_dataset, mes_desde_nombre

    if mes_desde_nombre(path.name):
        return False
    headers = _leer_headers(path)
    if headers is None:
        return False  # que lo resuelva (y reporte) la ingesta misma
    if "Mes" in headers:
        return False
    return clasificar_dataset(headers) == "consumo"


def pendientes_detalle() -> dict:
    """
    Pendientes con el detalle que necesita la UI:
        {"todos": [nombres], "consumo_sin_mes": [nombres]}
    Los de consumo_sin_mes requieren que el usuario indique el período
    (no lo traen en el contenido NI en el nombre del archivo).
    """
    todos = set(listar_pendientes())
    consumo_sin_mes = [
        p.name for p in _archivos_entrada()
        if p.name in todos and _necesita_mes(p)
    ]
    return {"todos": sorted(todos), "consumo_sin_mes": consumo_sin_mes}


def ejecutar_ingesta_detallada(
    mes_por_archivo: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """
    Ingesta con mes POR ARCHIVO para los consumos crudos sin columna 'Mes':
    cada uno corre con su período (--solo + --mes) y después una pasada
    general para el resto (valores y archivos que ya traen Mes).
    """
    import os

    def correr(extra: list[str]) -> tuple[bool, str]:
        cmd = [sys.executable, str(SCRIPT_INGESTA), "--archivar", *extra]
        # Sin warnings de openpyxl ("Workbook contains no default style")
        # ensuciando el detalle que ve el usuario.
        env = {**os.environ, "PYTHONWARNINGS": "ignore"}
        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=1800, env=env
            )
        except subprocess.TimeoutExpired:
            return False, "La ingesta superó los 30 minutos y fue cancelada."
        return res.returncode == 0, (res.stdout or "") + (res.stderr or "")

    salidas: list[str] = []
    ok_total = True

    for nombre, mes in (mes_por_archivo or {}).items():
        ok, salida = correr(["--solo", nombre, "--mes", mes])
        ok_total = ok_total and ok
        salidas.append(f"--- {nombre} (mes {mes}) ---\n{salida}")

    ok, salida = correr([])
    ok_total = ok_total and ok
    salidas.append(salida)

    return ok_total, "\n".join(salidas)
