"""
Carga de datos de consumo y valores desde Supabase (PostgreSQL).

Los datos viven en el schema 'simulador' del proyecto 'gestor-clientes' de
Supabase. Las consultas piden solo lo necesario (filtros opcionales por
prestador y mes). Si la base no está configurada aún, la app cae al modo
de upload manual para no quedar inutilizable.
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
# CONSULTA A SUPABASE
# ============================================================================

@st.cache_data(ttl=300, show_spinner=False)
def _query_table(
    table: str,
    mes_col: str,
    prestador_ids: Optional[tuple],
    meses: Optional[tuple],
) -> Optional[pd.DataFrame]:
    """
    Consulta una tabla PostgreSQL con filtros opcionales.

    Devuelve None si la base/tabla no existe o no hay filas (para que la capa
    de arriba muestre el fallback de upload manual).
    """
    try:
        con = get_connection()
    except Exception:
        logger.warning("No se pudo conectar a Supabase para '%s'", table)
        return None

    try:
        if not table_exists(con, table):
            return None

        sql = f'SELECT * FROM "{table}"'
        clauses: list[str] = []
        params: list = []

        if prestador_ids:
            clauses.append('"Prestador ID" = ANY(%s)')
            params.append(list(prestador_ids))

        if meses:
            clauses.append(f'"{mes_col}" = ANY(%s)')
            params.append(list(meses))

        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        df = pd.read_sql_query(sql, con, params=params if params else None)
        return df if len(df) else None
    except Exception:
        logger.exception("Error consultando la tabla '%s' en Supabase", table)
        st.error(
            "No se pudieron cargar los datos. Reintentá en unos segundos; "
            "si persiste, contactá al equipo técnico."
        )
        return None
    finally:
        try:
            con.close()
        except Exception:
            pass


@st.cache_data(ttl=300, show_spinner=False)
def _catalogo_prestadores() -> Optional[list]:
    """SELECT DISTINCT de prestadores (liviano) — para selectores."""
    try:
        con = get_connection()
    except Exception:
        return None
    try:
        if not table_exists(con, CONSUMO_TABLE):
            return None
        with con.cursor() as cur:
            cur.execute(
                f'SELECT DISTINCT "Prestador ID", "Prestador Desc" '
                f'FROM "{CONSUMO_TABLE}" WHERE "Prestador ID" IS NOT NULL '
                f'ORDER BY "Prestador Desc"'
            )
            rows = cur.fetchall()
        return rows or None
    except Exception:
        logger.exception("Error consultando el catálogo de prestadores")
        return None
    finally:
        try:
            con.close()
        except Exception:
            pass


def get_prestadores_disponibles() -> Optional[list]:
    """
    Catálogo [(id, desc), ...] de prestadores SIN cargar las tablas completas.

    Permite que la UI renderice el selector primero y cargue después solo los
    datos del prestador elegido. None si no hay base configurada.
    """
    try:
        return _catalogo_prestadores()
    except Exception:
        logger.exception("Error consultando el catálogo de prestadores")
        return None


@st.cache_data(ttl=300, show_spinner=False)
def _resumen_base_cached() -> Optional[dict]:
    """Conteos livianos para el panel de Inicio."""
    try:
        con = get_connection()
    except Exception:
        return None
    try:
        if not table_exists(con, CONSUMO_TABLE):
            return None
        with con.cursor() as cur:
            cur.execute(
                f'SELECT COUNT(*), COUNT(DISTINCT "Prestador ID"), '
                f'COUNT(DISTINCT "Mes") FROM "{CONSUMO_TABLE}"'
            )
            fila = cur.fetchone()
        if fila is None:
            return None
        filas, prestadores, meses = fila
        tarifas = 0
        if table_exists(con, VALORES_TABLE):
            with con.cursor() as cur:
                cur.execute(f'SELECT COUNT(*) FROM "{VALORES_TABLE}"')
                t = cur.fetchone()
                tarifas = int(t[0]) if t else 0
        return {
            "filas": int(filas),
            "prestadores": int(prestadores),
            "meses": int(meses),
            "tarifas": int(tarifas),
        }
    except Exception:
        logger.exception("Error consultando el resumen de la base")
        return None
    finally:
        try:
            con.close()
        except Exception:
            pass


def resumen_base() -> Optional[dict]:
    """Estado de los datos cargados (para el panel de Inicio). None sin base."""
    try:
        return _resumen_base_cached()
    except Exception:
        logger.exception("Error consultando el resumen de la base")
        return None


# ============================================================================
# INGESTA DESDE LA APP (detectar archivos nuevos en data/raw y unificarlos)
# ============================================================================
@st.cache_data(ttl=60, show_spinner=False)
def _pendientes_cached(dir_state: tuple) -> dict:
    """Escaneo de archivos sin ingerir, cacheado por estado de carpeta."""
    from core import ingest_runner

    return ingest_runner.pendientes_detalle()


def _render_ingesta_pendiente() -> None:
    """
    Si hay archivos nuevos en data/raw/ ofrece ingerirlos desde la propia app.
    """
    from core import ingest_runner

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
        detalle = _pendientes_cached(ingest_runner.estado_carpetas())
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
            st.cache_data.clear()
            ok, salida = ingest_runner.ejecutar_ingesta_detallada(mes_por_archivo)
        st.session_state["_ingesta_resultado"] = (ok, salida)
        st.cache_data.clear()
        st.rerun()


# ============================================================================
# UPLOAD MANUAL + FUENTE DE DATOS
# ============================================================================
SRC_BASE = "Base (datos cargados)"
SRC_SUBIDOS = "Solo archivos subidos"
SRC_COMBINAR = "Combinar base + subidos"


def source_uses_uploads() -> bool:
    """True si la fuente elegida usa archivos subidos (solo o combinados)."""
    return st.session_state.get("data_source_radio") in (SRC_SUBIDOS, SRC_COMBINAR)


@st.cache_data(show_spinner=False, max_entries=8)
def _parse_upload(content: bytes, expected: tuple, numeric: tuple) -> pd.DataFrame:
    """Parsea + limpia un archivo subido (cacheado por contenido)."""
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
            st.warning(f"{label}: {len(df):,} filas — sin columnas: {sorted(miss)}")
        else:
            st.success(f"{label}: {len(df):,} filas")
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
    """Une base + subido para el modo 'combinar'."""
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

    Fuentes:
      - Base: lo ingerido en Supabase (con filtros opcionales por prestador/mes).
      - Solo archivos subidos: simula con lo que el usuario sube en el momento.
      - Combinar base + subidos: une ambos.
    """
    pid = _as_tuple(prestador_ids)
    mes = _as_tuple(meses)

    base_consumo = _query_table(CONSUMO_TABLE, CONSUMO_MES_COL, pid, mes)
    base_valores = _query_table(VALORES_TABLE, VALORES_MES_COL, pid, mes)
    base_ok = base_consumo is not None and base_valores is not None

    _is_admin = st.session_state.get("_user_role", "viewer") == "admin"

    with st.sidebar.expander("Datos", expanded=not base_ok):
        if base_consumo is not None:
            st.success(f"Consumo: {len(base_consumo):,} filas")
        if base_valores is not None:
            st.success(f"Valores: {len(base_valores):,} filas")

        if st.button(
            "Recargar datos",
            key="reload_data",
            help="Vacía el caché y vuelve a leer la base "
                 "(útil tras cargar datos nuevos).",
        ):
            st.cache_data.clear()
            st.rerun()

        if _is_admin:
            _render_ingesta_pendiente()

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

        if hay_sub and base_ok:
            fuente = st.radio(
                "Fuente de datos",
                [SRC_BASE, SRC_SUBIDOS, SRC_COMBINAR],
                key="data_source_radio",
                help="¿Simular con la base, solo con lo que subiste, o combinando ambos?",
            )
        elif hay_sub:
            fuente = SRC_SUBIDOS
        else:
            fuente = SRC_BASE
            st.session_state.pop("data_source_radio", None)
            if not base_ok:
                st.caption(
                    "No hay datos en la base. Subí los archivos arriba o corré "
                    "`python scripts/ingest.py` con DATABASE_URL configurado."
                )

    if fuente == SRC_SUBIDOS:
        c = sub_consumo if sub_consumo is not None else base_consumo
        v = sub_valores if sub_valores is not None else base_valores
        return c, v

    if fuente == SRC_COMBINAR:
        full_c = base_consumo if pid is None else _query_table(
            CONSUMO_TABLE, CONSUMO_MES_COL, None, None)
        full_v = base_valores if pid is None else _query_table(
            VALORES_TABLE, VALORES_MES_COL, None, None)
        return _concat_datasets(full_c, sub_consumo), _concat_datasets(full_v, sub_valores)

    return base_consumo, base_valores


# ============================================================================
# TRANSFORMACIONES CACHEADAS
# ============================================================================
@st.cache_data(ttl=300, show_spinner=False, hash_funcs={pd.DataFrame: df_fingerprint})
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
    renderizar UI. Para vistas que comparan entre prestadores.
    """
    c = _query_table(CONSUMO_TABLE, CONSUMO_MES_COL, None, None)
    v = _query_table(VALORES_TABLE, VALORES_MES_COL, None, None)
    if c is None or v is None:
        return None
    return get_merged_dataset(c, v)


@st.cache_data(ttl=300, show_spinner=False, hash_funcs={pd.DataFrame: df_fingerprint})
def get_normalized_consumo(df_consumo: pd.DataFrame) -> pd.DataFrame:
    """Normaliza tipos del dataset de consumo (cacheado). Usado por Mód. 2 y 3."""
    from core.simulator import normalize_dataframes

    c, _ = normalize_dataframes(df_consumo, df_consumo.iloc[:0])
    return c
