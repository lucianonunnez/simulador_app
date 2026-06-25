"""
Módulo de carga de datos — solo accesible para el rol admin.

Permite subir un export de consumo (.xlsx) desde MicroStrategy y cargarlo
directamente a simulador.consumo en Supabase.
"""
import logging

import pandas as pd
import psycopg2.extras
import streamlit as st

from core.db import get_connection
from core.excel_utils import (
    CONSUMO_NUMERIC_COLS,
    EXPECTED_CONSUMO_COLS,
    clean_dataset,
    load_excel_smart,
    missing_columns,
)

logger = logging.getLogger(__name__)

# Orden de columnas tal como están en la tabla
_COLS_TABLA = [
    "Prestador ID", "Prestador Desc", "Convenio ID", "Convenio Desc",
    "Mes", "Tipo Categoria", "Megacuenta", "Gama", "Cartilla",
    "Tipo Clase CM", "Nomenclador", "Prestacion Desc", "Prestacion ID",
    "Cantidad CM", "Importe CM",
]


def _df_to_rows(df: pd.DataFrame, cols: list) -> list:
    """Convierte DataFrame a tuplas para psycopg2, manejando pd.NA / NaN."""
    df_obj = df[cols].astype(object).where(pd.notna(df[cols]), None)
    return [tuple(row) for row in df_obj.itertuples(index=False, name=None)]


def _insertar(df: pd.DataFrame, mode: str) -> tuple:
    """
    Inserta el DataFrame en simulador.consumo.

    mode="actualizar" — borra las combinaciones (Prestador ID, Mes) que trae
                        el archivo y las reinserta; el resto queda intacto.
    mode="reemplazar" — TRUNCATE + INSERT (borra todo antes de insertar).

    Returns (filas_insertadas: int, error: str).
    """
    cols = [c for c in _COLS_TABLA if c in df.columns]
    rows = _df_to_rows(df, cols)
    if not rows:
        return 0, "El archivo no tiene filas válidas."

    col_names = ", ".join([f'"{c}"' for c in cols])
    sql_insert = f"INSERT INTO simulador.consumo ({col_names}) VALUES %s"

    try:
        con = get_connection()
    except Exception as exc:
        return 0, f"No se pudo conectar a la base de datos: {exc}"

    try:
        with con.cursor() as cur:
            if mode == "reemplazar":
                cur.execute("TRUNCATE simulador.consumo")
            else:
                combos = (
                    df[["Prestador ID", "Mes"]]
                    .drop_duplicates()
                    .dropna(subset=["Prestador ID", "Mes"])
                    .values.tolist()
                )
                if combos:
                    cur.executemany(
                        'DELETE FROM simulador.consumo '
                        'WHERE "Prestador ID" = %s AND "Mes" = %s',
                        combos,
                    )
            psycopg2.extras.execute_values(cur, sql_insert, rows, page_size=1000)
        con.commit()
        return len(rows), ""
    except Exception as exc:
        con.rollback()
        logger.exception("Error insertando consumo")
        return 0, str(exc)
    finally:
        con.close()


def render() -> None:
    st.title("Carga de Datos")
    st.caption(
        "Subí el export de MicroStrategy para actualizar la base de consumo. "
        "Solo visible para el administrador."
    )

    uploaded = st.file_uploader(
        "Export de Consumo (xlsx)",
        type=["xlsx"],
        key="upload_consumo_admin",
        help="El mismo archivo .xlsx que descargás de MicroStrategy.",
    )

    if not uploaded:
        st.info(
            "Arrastrá el archivo Excel aquí o usá el botón para seleccionarlo. "
            "El sistema detecta automáticamente el formato y las columnas."
        )
        return

    # Procesar
    with st.spinner("Procesando archivo..."):
        try:
            content = uploaded.getvalue()
            df = load_excel_smart(content, EXPECTED_CONSUMO_COLS)
            df = clean_dataset(df, CONSUMO_NUMERIC_COLS)
        except Exception as exc:
            st.error(f"No se pudo leer el archivo: {exc}")
            return

    miss = missing_columns(df, EXPECTED_CONSUMO_COLS)
    if miss:
        st.warning(f"Columnas faltantes (se ignoran): {sorted(miss)}")

    # Resumen
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Filas", f"{len(df):,}")
    prestadores = (
        df["Prestador Desc"].dropna().unique() if "Prestador Desc" in df.columns else []
    )
    c2.metric("Prestadores", len(prestadores))
    meses = df["Mes"].dropna().unique() if "Mes" in df.columns else []
    c3.metric("Meses", len(meses))
    importe = df["Importe CM"].sum() if "Importe CM" in df.columns else 0
    c4.metric("Importe total", f"${importe:,.0f}")

    if len(prestadores):
        st.caption(f"Prestadores: {', '.join(str(p) for p in sorted(prestadores))}")
    if len(meses):
        st.caption(f"Períodos: {', '.join(sorted(str(m) for m in meses))}")

    with st.expander("Vista previa (primeras 50 filas)"):
        st.dataframe(df.head(50), use_container_width=True)

    st.divider()

    mode_label = st.radio(
        "Modo de carga",
        [
            "Actualizar — reemplaza solo este prestador/período, conserva el resto",
            "Reemplazar todo — borra TODA la tabla antes de insertar",
        ],
        key="upload_mode",
    )
    insert_mode = "reemplazar" if "Reemplazar todo" in mode_label else "actualizar"

    if insert_mode == "reemplazar":
        st.warning(
            "Esta acción borra TODOS los datos de consumo antes de insertar los nuevos.",
            icon="⚠️",
        )

    if st.button("Cargar a Supabase", type="primary", key="btn_cargar"):
        with st.spinner(f"Cargando {len(df):,} filas..."):
            n, err = _insertar(df, insert_mode)
            st.cache_data.clear()

        if err:
            st.error(f"Error al cargar: {err}")
        else:
            st.success(f"{n:,} filas cargadas correctamente.")
            st.balloons()
