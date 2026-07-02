"""
Conexión y esquema de la base DuckDB local.

DuckDB es una base analítica embebida: un solo archivo (data/simulador.duckdb)
en disco, sin servidor ni dependencias externas. Los datos NUNCA salen de la
máquina -> cumple la restricción de datos médicos sensibles ("todo local").

Por qué DuckDB y no cargar el Excel a RAM (como antes):
  - Los datos viven en DISCO; a memoria sube solo lo que pide cada consulta.
  - Es columnar y vectorizado: filtrar/agregar es rápido aunque haya millones
    de filas.
  - Si una consulta necesitara más RAM que la disponible, DuckDB derrama a
    disco en vez de reventar (out-of-core). Por eso fijamos un techo de RAM.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

# La base vive dentro de data/ (gitignored): nunca se versiona ni se sube.
DB_PATH = Path("data") / "simulador.duckdb"

# Techo de RAM para las consultas. Lo que exceda, DuckDB lo derrama a disco.
MEMORY_LIMIT = "2GB"

# Tablas
CONSUMO_TABLE = "consumo"
VALORES_TABLE = "valores"
INGEST_LOG_TABLE = "_ingest_log"

# Grano del upsert. Como los datos se bajan "de a partes" por prestador (por el
# límite de ~1M filas de MicroStrategy), el reemplazo es por (Prestador, Mes):
# re-subir un prestador/mes pisa solo esas filas, sin tocar los demás.
# OJO: dentro de cada par el reemplazo es POR DISEÑO destructivo — un re-export
# PARCIAL de un (Prestador, Mes) elimina el resto de las filas de ese par. La
# ingesta (scripts/ingest.py) avisa con un ATENCIÓN cuando el archivo nuevo
# trae bastante menos filas (< 50%) que las que borra.
CONSUMO_KEY = ("Prestador ID", "Mes")
VALORES_KEY = ("Prestador ID", "Mes Vigencia")


def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """
    Abre una conexión a la base local.

    read_only=True para la app (permite varios lectores en paralelo).
    read_only=False para el script de ingesta (único escritor).
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    try:
        con.execute(f"SET memory_limit = '{MEMORY_LIMIT}'")
    except Exception:
        # Si la versión de DuckDB no soporta el pragma, seguimos igual.
        logger.warning("No se pudo fijar memory_limit=%s en DuckDB", MEMORY_LIMIT)
    return con


def table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    """True si la tabla existe en la base."""
    row = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?",
        [name],
    ).fetchone()
    return row is not None


def table_count(con: duckdb.DuckDBPyConnection, name: str) -> int:
    """Cantidad de filas de una tabla (0 si no existe)."""
    if not table_exists(con, name):
        return 0
    return con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
