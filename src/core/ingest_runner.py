"""
Puente app -> ingesta: detectar archivos nuevos en data/raw/ y unificarlos
a Supabase desde la propia UI, sin pasar por la terminal.

- pendientes_detalle(): qué archivos de data/raw/ todavía no están en la base.
- ejecutar_ingesta(): corre scripts/ingest.py --archivar como subproceso,
  pasando DATABASE_URL para que el script se conecte a Supabase.

Asume CWD = raíz del repo.
"""

from __future__ import annotations

import hashlib
import os
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
    """Huella barata de data/raw (nombre, tamaño, mtime): clave de caché."""
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

    try:
        con = db.get_connection()
        try:
            if db.table_exists(con, db.INGEST_LOG_TABLE):
                with con.cursor() as cur:
                    cur.execute(f'SELECT file_hash FROM "{db.INGEST_LOG_TABLE}"')
                    ya_ingeridos = {r[0] for r in cur.fetchall()}
        finally:
            con.close()
    except Exception:
        # Sin conexión: reportamos todo como pendiente; la ingesta resolverá.
        pass

    return [p.name for p in archivos if _hash_archivo(p) not in ya_ingeridos]


def _db_url_para_subproceso() -> str | None:
    """Obtiene la URL de DB para pasarla al subproceso de ingesta."""
    from core.db import _get_db_url
    try:
        return _get_db_url()
    except Exception:
        return None


def ejecutar_ingesta(mes: str | None = None) -> tuple[bool, str]:
    """
    Corre la ingesta (con --archivar) y devuelve (ok, salida_de_consola).
    """
    db_url = _db_url_para_subproceso()
    env = {**os.environ, "PYTHONWARNINGS": "ignore"}
    if db_url:
        env["DATABASE_URL"] = db_url

    cmd = [sys.executable, str(SCRIPT_INGESTA), "--archivar"]
    if mes:
        cmd += ["--mes", mes]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, env=env)
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
    """True si el archivo es un consumo que NO puede resolver su período solo."""
    from core.excel_utils import clasificar_dataset, mes_desde_nombre

    if mes_desde_nombre(path.name):
        return False
    headers = _leer_headers(path)
    if headers is None:
        return False
    if "Mes" in headers:
        return False
    return clasificar_dataset(headers) == "consumo"


def pendientes_detalle() -> dict:
    """
    Pendientes con el detalle que necesita la UI:
        {"todos": [nombres], "consumo_sin_mes": [nombres]}
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
    """Ingesta con mes POR ARCHIVO para los consumos crudos sin columna 'Mes'."""
    db_url = _db_url_para_subproceso()
    env = {**os.environ, "PYTHONWARNINGS": "ignore"}
    if db_url:
        env["DATABASE_URL"] = db_url

    def correr(extra: list[str]) -> tuple[bool, str]:
        cmd = [sys.executable, str(SCRIPT_INGESTA), "--archivar", *extra]
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
