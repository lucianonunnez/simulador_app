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

from typing import Iterable, Optional, Tuple

import pandas as pd
import streamlit as st

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
@st.cache_data(ttl=600, show_spinner=False)
def _query_table(
    table: str,
    mes_col: str,
    prestador_ids: Optional[tuple],
    meses: Optional[tuple],
) -> Optional[pd.DataFrame]:
    """
    Consulta una tabla de DuckDB con filtros opcionales empujados al SQL.

    Devuelve None si la base/tabla no existe o no hay filas (para que la capa
    de arriba muestre el fallback de upload manual). Cacheado 10 min.
    """
    if not DB_PATH.exists():
        return None

    con = get_connection(read_only=True)
    try:
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
        st.error(f"Error consultando '{table}' en DuckDB: {e}")
        return None
    finally:
        con.close()


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
    except Exception as e:
        st.error(f"Error leyendo {label}: {e}")
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

    df_consumo = _query_table(CONSUMO_TABLE, CONSUMO_MES_COL, pid, mes)
    df_valores = _query_table(VALORES_TABLE, VALORES_MES_COL, pid, mes)

    need_fallback = df_consumo is None or df_valores is None

    with st.sidebar.expander("Carga de datos", expanded=need_fallback):
        if df_consumo is not None:
            st.success(f"Consumo: {len(df_consumo):,} filas")
        if df_valores is not None:
            st.success(f"Valores: {len(df_valores):,} filas")

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

@st.cache_data(ttl=600, show_spinner=False)
def get_merged_dataset(
    df_consumo: pd.DataFrame, df_valores: pd.DataFrame
) -> pd.DataFrame:
    """Normaliza + une consumo y valores (cacheado). Usado por el Módulo 1."""
    from core.simulator import merge_datasets, normalize_dataframes

    c, v = normalize_dataframes(df_consumo, df_valores)
    return merge_datasets(c, v)


@st.cache_data(ttl=600, show_spinner=False)
def get_normalized_consumo(df_consumo: pd.DataFrame) -> pd.DataFrame:
    """Normaliza tipos del dataset de consumo (cacheado). Usado por Mód. 2 y 3."""
    from core.simulator import normalize_dataframes

    c, _ = normalize_dataframes(df_consumo, df_consumo.iloc[:0])
    return c
