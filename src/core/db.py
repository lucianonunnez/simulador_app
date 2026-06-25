"""
Conexión y esquema de la base PostgreSQL en Supabase (schema: simulador).

Los datos viven en el proyecto 'gestor-clientes' de Supabase, en un schema
dedicado 'simulador' completamente separado de las otras tablas de ese proyecto.

La URL de conexión se lee desde:
  - st.secrets["supabase_db_url"]  (app Streamlit)
  - Variable de entorno DATABASE_URL  (script CLI de ingesta)
"""

from __future__ import annotations

import logging
import os

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

SCHEMA = "simulador"

CONSUMO_TABLE = "consumo"
VALORES_TABLE = "valores"
INGEST_LOG_TABLE = "_ingest_log"

CONSUMO_KEY = ("Prestador ID", "Mes")
VALORES_KEY = ("Prestador ID", "Mes Vigencia")


def _get_db_url() -> str:
    """Devuelve la URL de conexión desde secrets o variable de entorno."""
    try:
        import streamlit as st
        return st.secrets["supabase_db_url"]
    except Exception:
        pass
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "No se encontró la URL de la base de datos. "
            "Configurá supabase_db_url en .streamlit/secrets.toml "
            "o la variable de entorno DATABASE_URL."
        )
    return url


def get_connection() -> psycopg2.extensions.connection:
    """Abre una conexión PostgreSQL con search_path=simulador.

    El search_path se fija por DOS vías a propósito: el parámetro de arranque
    `options` (lo toma la conexión directa) y un `SET` explícito tras conectar.
    Algunos poolers pueden no propagar `options`, así que el `SET` garantiza
    que las consultas sin schema-qualify ('FROM consumo') resuelvan a
    'simulador' tanto en local como deployado contra el Session Pooler.
    """
    url = _get_db_url()
    con = psycopg2.connect(url, options=f"-c search_path={SCHEMA},public")
    try:
        with con.cursor() as cur:
            cur.execute(f"SET search_path TO {SCHEMA}, public")
        con.commit()
    except Exception:
        con.rollback()
    return con


def table_exists(con: psycopg2.extensions.connection, name: str) -> bool:
    """True si la tabla existe en el schema simulador."""
    with con.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s",
            [SCHEMA, name],
        )
        return cur.fetchone() is not None


def table_count(con: psycopg2.extensions.connection, name: str) -> int:
    """Cantidad de filas de una tabla (0 si no existe)."""
    if not table_exists(con, name):
        return 0
    with con.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM simulador."{name}"')
        return cur.fetchone()[0]
