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

from core import db_remote
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
from ui.formatters import format_int


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

    Con Supabase configurado, la identidad viene de la base remota.
    """
    if db_remote.remote_configured():
        return db_remote.fingerprint()
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
def _query_table_cached(
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

    Los errores PROPAGAN (ver NOTA sobre concurrencia más abajo): el manejo
    está en el wrapper _query_table, fuera del caché.

    Si hay Supabase configurado, la consulta va a la base remota (mismo
    contrato de columnas y mismo push-down de filtros).
    """
    if db_remote.remote_configured():
        return db_remote.query_table(table, mes_col, prestador_ids, meses)
    if not DB_PATH.exists():
        return None

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


def _query_table(
    table: str,
    mes_col: str,
    prestador_ids: Optional[tuple],
    meses: Optional[tuple],
    db_state: str = "",
) -> Optional[pd.DataFrame]:
    """
    Wrapper NO cacheado de _query_table_cached: maneja el error del rerun.

    Antes el try/except vivía DENTRO de la función cacheada y devolvía None:
    st.cache_data cacheaba ese None (y el st.error solo se veía en el primer
    rerun) → un lock transitorio de ingesta dejaba la app "sin datos" y sin
    mensaje hasta 10 minutos. Con el error fuera del caché, el fallo afecta
    solo a este rerun y el mensaje se muestra siempre.
    """
    try:
        return _query_table_cached(table, mes_col, prestador_ids, meses, db_state)
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
    if db_remote.remote_configured():
        return db_remote.catalogo_prestadores()
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
    if db_remote.remote_configured():
        return db_remote.resumen()
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
# UPLOAD MANUAL + FUENTE DE DATOS
# ============================================================================
# Etiquetas del selector de fuente (también las lee module1 para decidir si
# evitar el push-down y armar el selector desde los datos cargados).
SRC_BASE = "Base (datos cargados)"
SRC_SUBIDOS = "Solo archivos subidos"
SRC_COMBINAR = "Combinar base + subidos"


def source_uses_uploads() -> bool:
    """True si la fuente elegida usa archivos subidos (solo o combinados).

    module1 la consulta ANTES de cargar: cuando hay subidos no conviene el
    push-down por prestador (se necesita el universo completo) y el selector
    de prestadores debe salir de los datos, no del catálogo de la base.
    """
    return st.session_state.get("data_source_radio") in (SRC_SUBIDOS, SRC_COMBINAR)


@st.cache_data(show_spinner=False, max_entries=8)
def _parse_upload(content: bytes, expected: tuple, numeric: tuple) -> pd.DataFrame:
    """Parsea + limpia un archivo subido (cacheado por contenido).

    Cacheado por los bytes del archivo: sin esto se re-parsearía el Excel en
    CADA rerun (caro con archivos grandes). clean_dataset deja el archivo con
    el mismo esquema que la base (numéricas coaccionadas, mes 'MM-YYYY', IDs
    Int64), así combinar base + subido es consistente.
    """
    df = load_excel_smart(content, set(expected))
    return clean_dataset(df, set(numeric))


def _leer_subido(uploaded_file, expected_cols: set, numeric_cols: set, label: str):
    """Lee un archivo del uploader (o None) y reporta estado en el sidebar."""
    if uploaded_file is None:
        return None
    try:
        df = _parse_upload(
            uploaded_file.getvalue(),
            tuple(sorted(expected_cols)),
            tuple(sorted(numeric_cols)),
        )
        miss = missing_columns(df, expected_cols)
        if miss:
            st.warning(f"{label} (subido): faltan columnas {sorted(miss)}")
        st.success(f"{label} subido: {format_int(len(df))} filas")
        return df
    except Exception:
        logger.exception("Error leyendo el archivo subido de %s", label)
        st.error(
            f"No se pudo leer el archivo de {label}. Verificá que sea un "
            "export válido (xlsx o csv) y reintentá."
        )
        return None


def _concat_datasets(
    base: Optional[pd.DataFrame], extra: Optional[pd.DataFrame]
) -> Optional[pd.DataFrame]:
    """Une base + subido para el modo 'combinar' (unión de columnas, sin dupes)."""
    if base is None:
        return extra
    if extra is None:
        return base
    cols = list(dict.fromkeys([*base.columns, *extra.columns]))
    out = pd.concat(
        [base.reindex(columns=cols), extra.reindex(columns=cols)], ignore_index=True
    )
    return out.drop_duplicates().reset_index(drop=True)


# ============================================================================
# API PÚBLICA
# ============================================================================
def load_consumo_and_valores(
    prestador_ids: Optional[Iterable] = None,
    meses: Optional[Iterable] = None,
) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Carga consumo y valores según la FUENTE elegida en el sidebar.

    Fuentes (selector "Carga de datos" → "Fuente de datos"):
      - Base: lo ingerido en DuckDB (con push-down opcional por prestador/mes).
      - Solo archivos subidos: simula con lo que el usuario sube en el momento.
      - Combinar base + subidos: une ambos (la base completa + los subidos).

    Args:
        prestador_ids: filtra por esos "Prestador ID" (push-down, solo aplica a
            la fuente Base; con subidos/combinar se trae el universo completo).
        meses: filtra por esos meses (idem, solo fuente Base).

    Returns:
        (df_consumo, df_valores). Cada uno puede ser None si no se cargó.
    """
    pid = _as_tuple(prestador_ids)
    mes = _as_tuple(meses)
    estado = _db_fingerprint()

    base_consumo = _query_table(CONSUMO_TABLE, CONSUMO_MES_COL, pid, mes, estado)
    base_valores = _query_table(VALORES_TABLE, VALORES_MES_COL, pid, mes, estado)
    base_ok = base_consumo is not None and base_valores is not None

    with st.sidebar.expander("Carga de datos", expanded=not base_ok):
        if base_consumo is not None:
            st.success(f"Base · Consumo: {format_int(len(base_consumo))} filas")
        if base_valores is not None:
            st.success(f"Base · Valores: {format_int(len(base_valores))} filas")

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

        # ── Subir archivos (siempre disponible) ──
        st.divider()
        st.markdown("**Subir archivos** _(opcional)_")
        st.caption(
            "Subí Consumo y/o Valores para simular con datos propios "
            "(p. ej. el export de un prestador puntual)."
        )
        up_c = st.file_uploader(
            "Consumo (xlsx/csv)", type=["xlsx", "csv"], key="upload_consumo",
        )
        up_v = st.file_uploader(
            "Valores (xlsx/csv)", type=["xlsx", "csv"], key="upload_valores",
        )
        sub_consumo = _leer_subido(up_c, EXPECTED_CONSUMO_COLS, CONSUMO_NUMERIC_COLS, "Consumo")
        sub_valores = _leer_subido(up_v, EXPECTED_VALORES_COLS, VALORES_NUMERIC_COLS, "Valores")
        hay_sub = sub_consumo is not None or sub_valores is not None

        # ── Fuente de datos ──
        if hay_sub and base_ok:
            fuente = st.radio(
                "Fuente de datos",
                [SRC_BASE, SRC_SUBIDOS, SRC_COMBINAR],
                key="data_source_radio",
                help="¿Simular con la base, solo con lo que subiste, o combinando ambos?",
            )
        elif hay_sub:
            fuente = SRC_SUBIDOS
            st.info("No hay base cargada: se simulará con los archivos subidos.")
        else:
            fuente = SRC_BASE
            # Sin archivos subidos, limpiar una selección de fuente vieja para
            # que source_uses_uploads() no quede "pegada" en subidos/combinar
            # (y module1 recupere el push-down por prestador).
            st.session_state.pop("data_source_radio", None)
            if not base_ok:
                st.caption(
                    "No hay datos en la base. Subí los archivos arriba o corré "
                    "`python scripts/ingest.py`."
                )

    # ── Resolución de la fuente ──
    if fuente == SRC_SUBIDOS:
        # Si falta un lado, se completa con la base (si existe) para poder mergear.
        c = sub_consumo if sub_consumo is not None else base_consumo
        v = sub_valores if sub_valores is not None else base_valores
        return c, v

    if fuente == SRC_COMBINAR:
        # Combinar necesita la base COMPLETA (sin el filtro de push-down por
        # prestador): se re-consulta sin filtros si la carga vino filtrada.
        full_c = base_consumo if pid is None else _query_table(
            CONSUMO_TABLE, CONSUMO_MES_COL, None, None, estado)
        full_v = base_valores if pid is None else _query_table(
            VALORES_TABLE, VALORES_MES_COL, None, None, estado)
        return _concat_datasets(full_c, sub_consumo), _concat_datasets(full_v, sub_valores)

    # Fuente Base (comportamiento histórico, con push-down).
    return base_consumo, base_valores


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
