"""
Conexión y esquema de la base PostgreSQL en Supabase (schema: simulador).

Los datos viven en el proyecto 'gestor-clientes' de Supabase, en un schema
dedicado 'simulador' completamente separado de las otras tablas de ese proyecto.

La URL de conexión se lee desde:
  - st.secrets["supabase_db_url"]  (app Streamlit)
  - Variable de entorno DATABASE_URL  (script CLI de ingesta)

Robustez de la conexión (por qué este módulo es defensivo)
----------------------------------------------------------
Streamlit Community Cloud es SOLO IPv4, pero la conexión DIRECTA de Supabase
(host `db.<ref>.supabase.co`) es SOLO IPv6 desde 2024: desde la nube NO resuelve
("could not translate host name"). La forma robusta es usar el **Session Pooler**
(host `aws-0-<region>.pooler.supabase.com`, usuario `postgres.<ref>`), que es
IPv4. Para que la app "funcione siempre" aunque el secret quede mal cargado,
`_normalize_db_url` autodetecta una URL directa y la reescribe al pooler.

Además, cada conexión usa `connect_timeout` + keepalives (para que un pooler
ocioso no corte la conexión a mitad de uso) y se reintenta con backoff ante
errores transitorios de red.
"""

from __future__ import annotations

import logging
import os
import time
from urllib.parse import urlsplit, urlunsplit

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

SCHEMA = "simulador"

CONSUMO_TABLE = "consumo"
VALORES_TABLE = "valores"
INGEST_LOG_TABLE = "_ingest_log"

CONSUMO_KEY = ("Prestador ID", "Mes")
VALORES_KEY = ("Prestador ID", "Mes Vigencia")

# Región del proyecto Supabase, usada solo para reescribir una URL directa al
# Session Pooler. El proyecto 'gestor-clientes' vive en sa-east-1; se puede
# pisar con la env var SUPABASE_REGION o el secret supabase_region si migrara.
_DEFAULT_REGION = "sa-east-1"

# Supabase tiene dos "shards" de pooler por región: aws-0 (proyectos viejos) y
# aws-1 (proyectos nuevos). Una URL directa NO dice cuál le toca, así que al
# reescribir probamos ambos en orden (aws-1 primero: los proyectos recientes
# viven ahí). Si el usuario pega la URL del pooler ya armada, se respeta tal cual.
_POOLER_IDS = ("aws-1", "aws-0")

# Parámetros de robustez de la conexión.
_CONNECT_TIMEOUT = 10          # segundos para abrir la conexión (no colgar)
_MAX_ATTEMPTS = 3              # rondas de reintento ante errores transitorios
_RETRY_BACKOFF = (1, 3, 6)     # segundos de espera entre rondas

# keepalives TCP: si el Session Pooler deja la conexión ociosa, estos pings
# evitan que el SO la dé por muerta y se corte a mitad de una operación.
_KEEPALIVE_KWARGS = {
    "connect_timeout": _CONNECT_TIMEOUT,
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 5,
}

# Valores placeholder que NO son una contraseña real: si la URL trae uno de
# estos, la conexión nunca podría funcionar, así que fallamos con un mensaje
# claro en vez de un error críptico de psycopg2.
_PASSWORD_PLACEHOLDERS = (
    "tu_password",
    "tu-password",
    "your-password",
    "your_password",
    "reemplazar",
    "[",  # cualquier resto de "[YOUR-PASSWORD]"
)


def _region() -> str:
    """Región del pooler (env var / secret, con default sa-east-1)."""
    region = os.environ.get("SUPABASE_REGION")
    if not region:
        try:
            import streamlit as st
            region = st.secrets.get("supabase_region")  # type: ignore[assignment]
        except Exception:
            region = None
    return region or _DEFAULT_REGION


def _with_sslmode(parts) -> str:
    """Garantiza sslmode=require en el query string y serializa la URL."""
    query = parts.query
    if "sslmode=" not in query:
        query = (query + "&" if query else "") + "sslmode=require"
        parts = parts._replace(query=query)
    return urlunsplit(parts)


def _candidate_db_urls(url: str) -> list[str]:
    """URLs candidatas a probar, en orden, desde un entorno solo-IPv4.

    - Si la URL apunta a la conexión DIRECTA (`db.<ref>.supabase.co`, solo
      IPv6), la reescribe al **Session Pooler** (IPv4) y devuelve UNA candidata
      por cada shard de pooler (aws-1, aws-0): no sabemos cuál le toca al
      proyecto, así que se prueban ambas (usuario `postgres` -> `postgres.<ref>`).
    - Si ya apunta al pooler (u otro host), la respeta tal cual (solo agrega
      sslmode). Una sola candidata.
    - Si la contraseña es un placeholder (TU_PASSWORD, [YOUR-PASSWORD], ...),
      lanza un error claro (no tiene sentido intentar conectar).
    """
    parts = urlsplit(url.strip())
    netloc = parts.netloc

    # Separar userinfo (user:pass, sin decodificar para no romper la contraseña)
    # de host:port.
    if "@" in netloc:
        userinfo, hostport = netloc.rsplit("@", 1)
    else:
        userinfo, hostport = "", netloc
    user, _, password = userinfo.partition(":")

    if password:
        low = password.lower()
        if any(ph in low for ph in _PASSWORD_PLACEHOLDERS):
            raise RuntimeError(
                "La contraseña de la base sigue siendo un placeholder "
                f"('{password}'). Reemplazala por la contraseña real del "
                "proyecto Supabase en supabase_db_url (Settings -> Secrets)."
            )

    # host[:port], soportando IPv6 entre corchetes (no es nuestro caso, pero
    # mantenemos la lógica simple y correcta).
    if hostport.startswith("["):
        host, _, port = hostport[1:].partition("]")
        port = port.lstrip(":")
    else:
        host, _, port = hostport.partition(":")

    # ¿NO es la conexión directa? -> respetar la URL tal cual (una candidata).
    if not (host.startswith("db.") and host.endswith(".supabase.co")):
        return [_with_sslmode(parts)]

    # Conexión directa: reescribir al pooler, una candidata por shard.
    ref = host[len("db."):-len(".supabase.co")]
    # El pooler exige el usuario calificado con el ref del proyecto.
    new_user = user if "." in user else f"{user or 'postgres'}.{ref}"
    new_port = port or "5432"
    logger.warning(
        "supabase_db_url apuntaba a la conexión directa (solo IPv6); se "
        "reescribe al Session Pooler (IPv4) probando shards %s.", _POOLER_IDS
    )
    candidates: list[str] = []
    for pooler_id in _POOLER_IDS:
        new_host = f"{pooler_id}-{_region()}.pooler.supabase.com"
        netloc = f"{new_user}:{password}@{new_host}:{new_port}" if password \
            else f"{new_user}@{new_host}:{new_port}"
        candidates.append(_with_sslmode(parts._replace(netloc=netloc)))
    return candidates


def _get_raw_db_url() -> str:
    """Devuelve la URL cruda desde secrets (app) o env var (CLI)."""
    raw = None
    try:
        import streamlit as st
        raw = st.secrets["supabase_db_url"]
    except Exception:
        raw = os.environ.get("DATABASE_URL")
    if not raw:
        raise RuntimeError(
            "No se encontró la URL de la base de datos. "
            "Configurá supabase_db_url en .streamlit/secrets.toml "
            "o la variable de entorno DATABASE_URL."
        )
    return raw


def get_connection() -> psycopg2.extensions.connection:
    """Abre una conexión PostgreSQL robusta con search_path=simulador.

    - Reescribe una URL directa (solo IPv6) al Session Pooler (IPv4) y prueba
      ambos shards (aws-1/aws-0) hasta que uno conecte.
    - Usa connect_timeout + keepalives para que la conexión no se cuelgue ni
      se corte por inactividad del pooler.
    - Reintenta con backoff ante errores transitorios de red.
    - Fija search_path con un `SET` explícito tras conectar (el pooler puede
      no propagar el parámetro de arranque `options`), de modo que las queries
      sin schema-qualify ('FROM consumo') resuelvan a 'simulador'.
    """
    candidates = _candidate_db_urls(_get_raw_db_url())
    last_err: Exception | None = None
    for ronda in range(_MAX_ATTEMPTS):
        for url in candidates:
            try:
                con = psycopg2.connect(url, **_KEEPALIVE_KWARGS)
                try:
                    with con.cursor() as cur:
                        cur.execute(f"SET search_path TO {SCHEMA}, public")
                    con.commit()
                except Exception:
                    con.rollback()
                return con
            except psycopg2.OperationalError as err:
                last_err = err
                # Host del candidato para el log (sin exponer la contraseña).
                host = urlsplit(url).hostname
                logger.warning(
                    "Fallo al conectar a Supabase via %s (ronda %d/%d): %s",
                    host, ronda + 1, _MAX_ATTEMPTS, err,
                )
        # Todos los candidatos fallaron en esta ronda: backoff y reintentar.
        if ronda < _MAX_ATTEMPTS - 1:
            espera = _RETRY_BACKOFF[min(ronda, len(_RETRY_BACKOFF) - 1)]
            logger.warning("Reintentando la conexión a Supabase en %ds...", espera)
            time.sleep(espera)
    logger.error("No se pudo conectar a Supabase tras %d rondas: %s",
                 _MAX_ATTEMPTS, last_err)
    raise last_err  # type: ignore[misc]


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
