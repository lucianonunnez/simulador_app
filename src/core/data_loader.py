"""
Carga de datos de consumo y valores desde DuckDB (local).

Antes esto leía los Excel ENTEROS a RAM con pandas en cada sesión. Ahora los
datos viven en una base DuckDB local (data/simulador.duckdb), construida por
scripts/ingest.py a partir de los Excel descargados manualmente de
MicroStrategy. Las consultas piden solo lo necesario (filtros opcionales por
prestador y mes), así que:
  - La RAM usada es una fracción de la de antes.
  - Nada sale de la máquina (datos médicos sensibles -> todo local).

Si la base todavía no existe (checkout nuevo, sin datos ingeridos), cae a un
uploader manual en el sidebar para no dejar la app inutilizable.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional, Tuple

import pandas as pd
import streamlit as st

from core.cachekeys import df_fingerprint

logger = logging.getLogger(__name__)

from core.db import (
    CONSUMO_TABLE,
    DB_PATH,
    VALORES_TABLE,
    get_connection,
    table_exists,
)
from core.excel_utils import (
    CONSUMO_MES_COL,
    CONSUMO_NUMERIC_COLS,
    EXPECTED_CONSUMO_COLS,
    EXPECTED_VALORES_COLS,
    VALORES_MES_COL,
    VALORES_NUMERIC_COLS,
    clean_dataset,
    load_excel_smart,
    missing_columns,
)


def _as_tuple(x: Optional[Iterable]) -> Optional[tuple]:
    """st.cache_data necesita argumentos hasheables -> listas a tuplas."""
    return None if x is None else tuple(x)


# ============================================================================
# CONSULTA A DUCKDB
# ============================================================================
def _db_fingerprint() -> str:
    """
    Identidad del estado de la base (mtime + tamaño del archivo).

    Se pasa como argumento de las funciones cacheadas: cuando la ingesta
    reescribe la base, el fingerprint cambia y el caché se invalida solo.
    Antes, los datos recién ingeridos tardaban hasta 10 min (el TTL) en
    aparecer en la app.
    """
    try:
        s = DB_PATH.stat()
        return f"{s.st_mtime_ns}-{s.st_size}"
    except OSError:
        return "no-db"


@st.cache_resource(ttl=600, show_spinner=False)
def _get_ro_connection():
    """
    Conexión de solo-lectura cacheada (DuckDB admite múltiples lectores).

    Antes se abría y cerraba una conexión por consulta y por rerun: frágil y
    más lento. La conexión cacheada se renueva sola cada 10 min (ttl).
    """
    return get_connection(read_only=True)


@st.cache_data(ttl=600, show_spinner=False)
def _query_table(
    table: str,
    mes_col: str,
    prestador_ids: Optional[tuple],
    meses: Optional[tuple],
    db_state: str = "",
) -> Optional[pd.DataFrame]:
    """
    Consulta una tabla de DuckDB con filtros opcionales empujados al SQL.

    Devuelve None si la base/tabla no existe o no hay filas (para que la capa
    de arriba muestre el fallback de upload manual). Cacheado 10 min, con
    invalidación automática al reingerir (db_state = fingerprint de la base).
    """
    if not DB_PATH.exists():
        return None

    try:
        con = _get_ro_connection().cursor()  # cursor propio: thread-safe
        if not table_exists(con, table):
            return None

        sql = f'SELECT * FROM "{table}"'
        clauses: list[str] = []
        params: list = []

        if prestador_ids:
            placeholders = ",".join(["?"] * len(prestador_ids))
            clauses.append(f'"Prestador ID" IN ({placeholders})')
            params.extend(prestador_ids)

        if meses:
            placeholders = ",".join(["?"] * len(meses))
            clauses.append(f'"{mes_col}" IN ({placeholders})')
            params.extend(meses)

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        df = con.execute(sql, params).fetch_df()
        return df if len(df) else None
    except Exception as e:
        # Detalle técnico al log; mensaje entendible al usuario (sin internals).
        logger.exception("Error consultando la tabla '%s' en la base local", table)
        if "lock" in str(e).lower():
            st.error(
                "La base de datos está siendo usada por otro proceso "
                "(probablemente una ingesta en curso). Esperá a que termine "
                "y recargá la página."
            )
        else:
            st.error(
                "No se pudieron cargar los datos. Reintentá en unos segundos; "
                "si persiste, contactá al equipo técnico."
            )
        return None


# NOTA sobre concurrencia (bug visto en vivo): la conexión cacheada con
# st.cache_resource se COMPARTE entre los hilos de las sesiones de Streamlit,
# y una conexión DuckDB no es thread-safe — dos consultas simultáneas se
# pisaban y fetchone() devolvía None ("cannot unpack non-iterable NoneType").
# Por eso cada consulta usa un CURSOR propio (con.cursor(), barato y seguro
# por hilo). Además, las funciones cacheadas dejan PROPAGAR las excepciones
# (st.cache_data no cachea errores): un fallo transitorio —p.ej. el lock de
# una ingesta— no deja un None pegado por 10 minutos; el wrapper de afuera
# loguea y devuelve None solo para ese rerun.


@st.cache_data(ttl=600, show_spinner=False)
def _catalogo_prestadores(db_state: str) -> Optional[list]:
    """SELECT DISTINCT de prestadores (liviano) — para selectores."""
    if not DB_PATH.exists():
        return None
    con = _get_ro_connection().cursor()
    if not table_exists(con, CONSUMO_TABLE):
        return None
    rows = con.execute(
        f'SELECT DISTINCT "Prestador ID", "Prestador Desc" '
        f'FROM "{CONSUMO_TABLE}" WHERE "Prestador ID" IS NOT NULL '
        f'ORDER BY "Prestador Desc"'
    ).fetchall()
    return rows or None


def get_prestadores_disponibles() -> Optional[list]:
    """
    Catálogo [(id, desc), ...] de prestadores SIN cargar las tablas completas.

    Permite que la UI renderice el selector primero y cargue después solo los
    datos del prestador elegido (filtro empujado al SQL de DuckDB), en vez de
    traer todo a RAM y filtrar en pandas. None si no hay base (modo upload).
    """
    try:
        return _catalogo_prestadores(_db_fingerprint())
    except Exception:
        logger.exception("Error consultando el catálogo de prestadores")
        return None


@st.cache_data(ttl=600, show_spinner=False)
def _resumen_base_cached(db_state: str) -> Optional[dict]:
    """Conteos livianos (COUNT/DISTINCT en SQL) para el panel de Inicio."""
    if not DB_PATH.exists():
        return None
    con = _get_ro_connection().cursor()
    if not table_exists(con, CONSUMO_TABLE):
        return None
    fila = con.execute(
        f'SELECT COUNT(*), COUNT(DISTINCT "Prestador ID"), '
        f'COUNT(DISTINCT "Mes") FROM "{CONSUMO_TABLE}"'
    ).fetchone()
    if fila is None:
        return None
    filas, prestadores, meses = fila
    tarifas = 0
    if table_exists(con, VALORES_TABLE):
        t = con.execute(f'SELECT COUNT(*) FROM "{VALORES_TABLE}"').fetchone()
        tarifas = int(t[0]) if t else 0
    return {
        "filas": int(filas),
        "prestadores": int(prestadores),
        "meses": int(meses),
        "tarifas": int(tarifas),
    }


def resumen_base() -> Optional[dict]:
    """Estado de los datos cargados (para el panel de Inicio). None sin base."""
    try:
        return _resumen_base_cached(_db_fingerprint())
    except Exception:
        logger.exception("Error consultando el resumen de la base")
        return None


# ============================================================================
# INGESTA DESDE LA APP (detectar archivos nuevos en data/raw y unificarlos)
# ============================================================================
@st.cache_data(ttl=60, show_spinner=False)
def _pendientes_cached(dir_state: tuple, db_state: str) -> dict:
    """Escaneo de archivos sin ingerir (y cuáles necesitan mes), cacheado por
    estado de carpeta + base (hashear un xlsx de 40 MB por rerun sería caro)."""
    from core import ingest_runner

    return ingest_runner.pendientes_detalle()


def _render_ingesta_pendiente() -> None:
    """
    Si hay archivos nuevos en data/raw/ (consumo (1).csv, valores (2).xlsx,
    etc., como los deja el navegador), ofrece ingerirlos y unificarlos a la
    base desde la propia app — el equivalente a correr
    `python scripts/ingest.py --archivar` en la terminal.
    """
    from core import ingest_runner

    # Resultado de la última ingesta (quedó pendiente de mostrar tras el rerun).
    # OJO: acá NO se puede usar st.expander — esta función se renderiza DENTRO
    # del expander "Carga de datos" y Streamlit no permite anidarlos
    # (StreamlitAPIException detectada con la app corriendo en real).
    if "_ingesta_resultado" in st.session_state:
        ok, salida = st.session_state.pop("_ingesta_resultado")
        if ok:
            st.success("Ingesta finalizada: archivos unificados a la base.")
        else:
            st.error("La ingesta tuvo errores (ver detalle).")
        lineas = [
            ln for ln in (salida or "").splitlines()
            if ln.strip()
            and "no default style" not in ln
            and "UserWarning" not in ln
            and not ln.strip().startswith("warn(")
        ]
        st.code("\n".join(lineas[-30:]) or "(sin salida)", language=None)

    try:
        detalle = _pendientes_cached(
            ingest_runner.estado_carpetas(), _db_fingerprint()
        )
    except Exception:
        logger.exception("Error buscando archivos pendientes de ingesta")
        return
    pendientes = detalle["todos"]
    sin_mes = detalle["consumo_sin_mes"]
    if not pendientes:
        return

    st.divider()
    nombres = ", ".join(pendientes[:4]) + ("…" if len(pendientes) > 4 else "")
    st.info(
        f"**{len(pendientes)} archivo(s) nuevo(s)**: {nombres}. "
        "Tip: soltá los exports en `data/a_procesar/` con el período en el "
        "nombre (`05-2026-Consumo-1584.xlsx`) y entra todo solo — lo procesado "
        "se mueve a `data/procesado/`."
    )

    # Los consumos CRUDOS no traen el período en el archivo (verificado: la
    # metadata de MicroStrategy solo guarda la ruta del reporte y la fecha de
    # descarga). Se pide POR archivo; si el nombre incluye MM-YYYY, se
    # precarga solo (convención: "consumo 12-2025.xlsx").
    mes_por_archivo: dict = {}
    if sin_mes:
        st.warning(
            f"**{len(sin_mes)} archivo(s) de consumo necesitan el período** "
            "(el export crudo no trae la columna 'Mes'). Completá el mes de "
            "cada uno — el que quede vacío NO se ingiere todavía. "
            "⚠️ Solo válido para descargas de UN mes: si el archivo abarca "
            "varios meses, pedí el export CON la columna 'Mes' "
            "(ver FUENTE_DATOS.md §9)."
        )
        import re as _re

        for nombre in sin_mes:
            match = _re.search(r"(\d{2}-\d{4})", nombre)
            valor = st.text_input(
                f"Mes de «{nombre}» (MM-YYYY)",
                value=match.group(1) if match else "",
                key=f"ingesta_mes_{nombre}",
                placeholder="ej: 12-2025",
                help="El período que elegiste en MicroStrategy al descargar "
                     "este archivo. Tip: si nombrás el archivo con el mes "
                     "(ej: consumo 12-2025.xlsx) se completa solo.",
            )
            if valor.strip():
                mes_por_archivo[nombre] = valor.strip()

    if st.button("Ingerir y unificar ahora", key="ingesta_btn", type="primary"):
        invalidos = [
            f"{n} ({m})" for n, m in mes_por_archivo.items()
            if not pd.Series([m]).str.fullmatch(r"\d{2}-\d{4}").iloc[0]
        ]
        if invalidos:
            st.warning(f"Mes inválido (debe ser MM-YYYY): {', '.join(invalidos)}")
            return
        with st.spinner("Ingiriendo y unificando archivos (puede tardar varios minutos)..."):
            # DuckDB no admite un escritor con lectores abiertos: cerrar la
            # conexión read-only cacheada antes de lanzar la ingesta.
            try:
                _get_ro_connection().close()
            except Exception:
                logger.exception("No se pudo cerrar la conexión read-only")
            st.cache_resource.clear()
            ok, salida = ingest_runner.ejecutar_ingesta_detallada(mes_por_archivo)
        st.session_state["_ingesta_resultado"] = (ok, salida)
        st.cache_data.clear()
        st.rerun()


# ============================================================================
# FALLBACK: UPLOAD MANUAL
# ============================================================================
def _load_from_upload(
    uploaded_file, expected_cols: set, numeric_cols: set, label: str
) -> Optional[pd.DataFrame]:
    """Carga un archivo subido manualmente desde la UI (fallback)."""
    if uploaded_file is None:
        return None
    try:
        with st.spinner(f"Leyendo {label}..."):
            content = uploaded_file.read()
            df = load_excel_smart(content, expected_cols)
        miss = missing_columns(df, expected_cols)
        if miss:
            st.warning(f"{label}: faltan columnas {sorted(miss)}")
        df = clean_dataset(df, numeric_cols)
        st.success(f"{label} cargado: {len(df):,} filas")
        return df
    except Exception:
        logger.exception("Error leyendo el archivo subido de %s", label)
        st.error(
            f"No se pudo leer el archivo de {label}. Verificá que sea un "
            "export válido (xlsx o csv) y reintentá."
        )
        return None


# ============================================================================
# API PÚBLICA
# ============================================================================
def load_consumo_and_valores(
    prestador_ids: Optional[Iterable] = None,
    meses: Optional[Iterable] = None,
) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Carga consumo y valores desde DuckDB (con filtros opcionales).

    Args:
        prestador_ids: si se pasa, filtra por esos "Prestador ID" (más liviano).
        meses: si se pasa, filtra por esos meses ("Mes" / "Mes Vigencia").

    Returns:
        (df_consumo, df_valores). Cada uno puede ser None si no se cargó.

    Nota: sin argumentos trae las tablas completas (comportamiento histórico,
    apto para volúmenes de demo). Para datasets grandes conviene pasar
    prestador_ids/meses y dejar que DuckDB filtre en disco.
    """
    pid = _as_tuple(prestador_ids)
    mes = _as_tuple(meses)
    estado = _db_fingerprint()

    df_consumo = _query_table(CONSUMO_TABLE, CONSUMO_MES_COL, pid, mes, estado)
    df_valores = _query_table(VALORES_TABLE, VALORES_MES_COL, pid, mes, estado)

    need_fallback = df_consumo is None or df_valores is None

    with st.sidebar.expander("Carga de datos", expanded=need_fallback):
        if df_consumo is not None:
            st.success(f"Consumo: {len(df_consumo):,} filas")
        if df_valores is not None:
            st.success(f"Valores: {len(df_valores):,} filas")

        if st.button(
            "Recargar datos",
            key="reload_data",
            help="Vacía el caché y vuelve a leer la base "
                 "(útil tras correr la ingesta).",
        ):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()

        _render_ingesta_pendiente()

        # ---- Fallback: upload manual si falta algún dataset ----
        if df_consumo is None:
            st.divider()
            st.caption(
                "Consumo no está en la base. Subilo manualmente o corré "
                "`python scripts/ingest.py`."
            )
            up_c = st.file_uploader(
                "Subir Consumo (xlsx/csv)",
                type=["xlsx", "csv"],
                key="upload_consumo",
                label_visibility="collapsed",
            )
            df_consumo = _load_from_upload(
                up_c, EXPECTED_CONSUMO_COLS, CONSUMO_NUMERIC_COLS, "Consumo"
            )

        if df_valores is None:
            st.divider()
            st.caption(
                "Valores no está en la base. Subilo manualmente o corré "
                "`python scripts/ingest.py`."
            )
            up_v = st.file_uploader(
                "Subir Valores (xlsx/csv)",
                type=["xlsx", "csv"],
                key="upload_valores",
                label_visibility="collapsed",
            )
            df_valores = _load_from_upload(
                up_v, EXPECTED_VALORES_COLS, VALORES_NUMERIC_COLS, "Valores"
            )

    return df_consumo, df_valores


# ============================================================================
# TRANSFORMACIONES CACHEADAS
# ============================================================================
# El merge y la normalización de tipos son pesados (to_numeric sobre todo el
# dataset + pd.merge). Antes corrían en CADA rerun de Streamlit -> el indicador
# de "Procesando datos..." reaparecía a cada interacción (el "parpadeo"). Acá
# se cachean: solo se recalculan cuando cambian los datos de entrada.

@st.cache_data(ttl=600, show_spinner=False, hash_funcs={pd.DataFrame: df_fingerprint})
def get_merged_dataset(
    df_consumo: pd.DataFrame, df_valores: pd.DataFrame
) -> pd.DataFrame:
    """Normaliza + une consumo y valores (cacheado). Usado por el Módulo 1."""
    from core.simulator import merge_datasets, normalize_dataframes

    c, v = normalize_dataframes(df_consumo, df_valores)
    return merge_datasets(c, v)


def load_merged_completo() -> Optional[pd.DataFrame]:
    """
    Consumo + valores COMPLETOS (sin filtro de prestador) ya mergeados, sin
    renderizar UI.

    Para vistas que comparan entre prestadores (tab Comparativa) cuando la
    carga principal del módulo vino filtrada por el push-down. Todo cacheado:
    después de la primera carga es gratis.
    """
    estado = _db_fingerprint()
    c = _query_table(CONSUMO_TABLE, CONSUMO_MES_COL, None, None, estado)
    v = _query_table(VALORES_TABLE, VALORES_MES_COL, None, None, estado)
    if c is None or v is None:
        return None
    return get_merged_dataset(c, v)


@st.cache_data(ttl=600, show_spinner=False, hash_funcs={pd.DataFrame: df_fingerprint})
def get_normalized_consumo(df_consumo: pd.DataFrame) -> pd.DataFrame:
    """Normaliza tipos del dataset de consumo (cacheado). Usado por Mód. 2 y 3."""
    from core.simulator import normalize_dataframes

    c, _ = normalize_dataframes(df_consumo, df_consumo.iloc[:0])
    return c
