"""
Fuente de datos REMOTA: Supabase (PostgreSQL).

Es la fuente de verdad cuando la app corre para un equipo / en la web: una sola
base central, multiusuario, con backups y RLS. Reemplaza a DuckDB local SOLO
cuando hay configuración de Supabase en los secrets; si no la hay, `data_loader`
sigue usando DuckDB exactamente como antes (este módulo no se activa).

El esquema de tablas es idéntico al de DuckDB (`consumo`, `valores`,
`_ingest_log`) pero vive en un schema propio de Postgres (por defecto
`simulador`), así no se mezcla con otras tablas del proyecto Supabase.

Diseño:
  - Conexión vía pool (Streamlit sirve varias sesiones en hilos distintos; una
    conexión psycopg2 no es segura entre hilos -> pool con getconn/putconn por
    consulta, igual criterio que el cursor-por-consulta del lado DuckDB).
  - Los filtros (prestador / mes) se EMPUJAN al SQL (WHERE ... IN (...)), igual
    que el push-down de DuckDB: se trae solo lo necesario, no todo a RAM.
  - `build_select` es PURO (arma SQL + params) para poder testearlo sin DB.

Config esperada en `.streamlit/secrets.toml`:

    [supabase]
    # Connection string de Postgres (Dashboard > Project Settings > Database).
    # Recomendado: el "Connection pooler" (Supavisor) en modo session.
    database_url = "postgresql://USER:PASSWORD@HOST:5432/postgres"
    schema = "simulador"   # opcional, default 'simulador'

También se acepta la variable de entorno SUPABASE_DATABASE_URL (útil en deploy).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Mismas tablas que DuckDB (mismo contrato de columnas).
CONSUMO_TABLE = "consumo"
VALORES_TABLE = "valores"
INGEST_LOG_TABLE = "_ingest_log"

DEFAULT_SCHEMA = "simulador"


# ============================================================================
# CONFIGURACIÓN
# ============================================================================
def _forzar_sslmode(dsn: str) -> str:
    """
    Garantiza TLS hacia Supabase: sin `sslmode`, libpq negocia con `prefer` y
    puede caer a texto plano (credenciales y datos de salud sin cifrar). Se
    agrega `sslmode=require` salvo que el DSN ya traiga uno explícito (un modo
    más estricto como verify-full del usuario se respeta).
    """
    if "sslmode=" in dsn:
        return dsn
    sep = "&" if "?" in dsn else "?"
    return f"{dsn}{sep}sslmode=require"


def _read_secrets() -> Optional[dict]:
    """
    Lee la config de Supabase de los secrets o del entorno. None si no hay.

    Acceder a st.secrets sin archivo de secrets levanta excepción: se atrapa y
    se devuelve None (la app cae a DuckDB sin romperse).
    """
    # 1) Variable de entorno (deploy headless).
    url_env = os.environ.get("SUPABASE_DATABASE_URL")
    if url_env:
        return {
            "database_url": _forzar_sslmode(url_env),
            "schema": os.environ.get("SUPABASE_SCHEMA", DEFAULT_SCHEMA),
        }

    # 2) st.secrets (uso normal con .streamlit/secrets.toml).
    try:
        import streamlit as st

        if "supabase" not in st.secrets:
            return None
        cfg = dict(st.secrets["supabase"])
    except Exception:
        return None

    if not cfg.get("database_url"):
        # Permitir también campos sueltos -> armar el DSN (siempre con TLS:
        # acá no hay forma de que el usuario haya pedido otro sslmode).
        campos = ("user", "password", "host")
        if all(cfg.get(k) for k in campos):
            port = cfg.get("port", 5432)
            dbname = cfg.get("dbname", "postgres")
            cfg["database_url"] = (
                f"postgresql://{cfg['user']}:{cfg['password']}"
                f"@{cfg['host']}:{port}/{dbname}?sslmode=require"
            )
        else:
            return None

    cfg["database_url"] = _forzar_sslmode(cfg["database_url"])
    cfg.setdefault("schema", DEFAULT_SCHEMA)
    return cfg


def remote_configured() -> bool:
    """True si hay configuración de Supabase (la app debe usar la fuente remota)."""
    return _read_secrets() is not None


def _schema() -> str:
    cfg = _read_secrets()
    return (cfg or {}).get("schema", DEFAULT_SCHEMA)


# ============================================================================
# CONSTRUCCIÓN DE SQL (puro, testeable sin base)
# ============================================================================
def _qi(ident: str) -> str:
    """Quoting de un identificador Postgres ("col" con comillas escapadas)."""
    return '"' + str(ident).replace('"', '""') + '"'


def build_select(
    schema: str,
    table: str,
    mes_col: str,
    prestador_ids: Optional[tuple] = None,
    meses: Optional[tuple] = None,
) -> tuple[str, list]:
    """
    Arma el SELECT con filtros opcionales empujados al WHERE.

    Devuelve (sql, params) con placeholders %s (psycopg2). PURO: no toca la base.
    """
    sql = f"SELECT * FROM {_qi(schema)}.{_qi(table)}"
    clauses: list[str] = []
    params: list = []

    if prestador_ids:
        ph = ",".join(["%s"] * len(prestador_ids))
        clauses.append(f"{_qi('Prestador ID')} IN ({ph})")
        params.extend(prestador_ids)

    if meses:
        ph = ",".join(["%s"] * len(meses))
        clauses.append(f"{_qi(mes_col)} IN ({ph})")
        params.extend(meses)

    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    return sql, params


# ============================================================================
# CONEXIÓN (pool cacheado)
# ============================================================================
def _get_pool():
    """
    Pool de conexiones cacheado por sesión de Streamlit.

    Cacheado con st.cache_resource para no abrir un pool por rerun. Si no hay
    Streamlit (tests), se crea un pool efímero por llamada.
    """
    cfg = _read_secrets()
    if cfg is None:
        raise RuntimeError("Supabase no está configurado.")

    try:
        import streamlit as st

        @st.cache_resource(show_spinner=False)
        def _cached_pool(dsn: str):
            from psycopg2.pool import ThreadedConnectionPool

            return ThreadedConnectionPool(1, 8, dsn=dsn)

        return _cached_pool(cfg["database_url"])
    except Exception as e:
        # Sin runtime de Streamlit: pool directo (no cacheado).
        if "Supabase" in str(e):
            raise
        from psycopg2.pool import ThreadedConnectionPool

        return ThreadedConnectionPool(1, 4, dsn=cfg["database_url"])


def _run_query(sql: str, params: list) -> pd.DataFrame:
    """Ejecuta una consulta y devuelve un DataFrame (numéricos ya como float)."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or None)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        conn.rollback()  # solo lecturas: cerrar la transacción implícita
        return pd.DataFrame(rows, columns=cols)
    finally:
        pool.putconn(conn)


# ============================================================================
# API (espejo de lo que data_loader necesita del lado DuckDB)
# ============================================================================
def query_table(
    table: str,
    mes_col: str,
    prestador_ids: Optional[tuple],
    meses: Optional[tuple],
) -> Optional[pd.DataFrame]:
    """Consulta una tabla con filtros opcionales. None si no hay filas/error."""
    try:
        sql, params = build_select(_schema(), table, mes_col, prestador_ids, meses)
        df = _run_query(sql, params)
        return df if len(df) else None
    except Exception:
        logger.exception("Error consultando '%s' en Supabase", table)
        try:
            import streamlit as st

            st.error(
                "No se pudieron cargar los datos desde Supabase. Verificá la "
                "conexión y reintentá; si persiste, contactá al equipo técnico."
            )
        except Exception:
            pass
        return None


def catalogo_prestadores() -> Optional[list]:
    """[(id, desc), ...] de prestadores (liviano, para el selector)."""
    try:
        sql = (
            f"SELECT DISTINCT {_qi('Prestador ID')}, {_qi('Prestador Desc')} "
            f"FROM {_qi(_schema())}.{_qi(CONSUMO_TABLE)} "
            f"WHERE {_qi('Prestador ID')} IS NOT NULL "
            f"ORDER BY {_qi('Prestador Desc')}"
        )
        df = _run_query(sql, [])
        return list(df.itertuples(index=False, name=None)) if len(df) else None
    except Exception:
        logger.exception("Error consultando el catálogo de prestadores en Supabase")
        return None


def resumen() -> Optional[dict]:
    """Conteos livianos para el panel de Inicio."""
    try:
        sch = _schema()
        sql = (
            f"SELECT COUNT(*), COUNT(DISTINCT {_qi('Prestador ID')}), "
            f"COUNT(DISTINCT {_qi('Mes')}) "
            f"FROM {_qi(sch)}.{_qi(CONSUMO_TABLE)}"
        )
        df = _run_query(sql, [])
        if not len(df):
            return None
        filas, prestadores, meses = df.iloc[0]
        tarifas = 0
        try:
            tv = _run_query(
                f"SELECT COUNT(*) FROM {_qi(sch)}.{_qi(VALORES_TABLE)}", []
            )
            tarifas = int(tv.iloc[0, 0]) if len(tv) else 0
        except Exception:
            logger.warning("No se pudo contar valores en Supabase")
        return {
            "filas": int(filas),
            "prestadores": int(prestadores),
            "meses": int(meses),
            "tarifas": int(tarifas),
        }
    except Exception:
        logger.exception("Error consultando el resumen en Supabase")
        return None


def fingerprint() -> str:
    """
    Identidad del estado de la base remota (para invalidar el caché).

    Usa el último ingest registrado en _ingest_log; si está vacío, devuelve un
    token estable (el caché se renueva por su TTL y por el botón 'Recargar').
    """
    try:
        sch = _schema()
        df = _run_query(
            f"SELECT COUNT(*), MAX(ingested_at) "
            f"FROM {_qi(sch)}.{_qi(INGEST_LOG_TABLE)}", []
        )
        n, ts = df.iloc[0]
        return f"remote-{int(n)}-{ts}"
    except Exception:
        return "remote"
