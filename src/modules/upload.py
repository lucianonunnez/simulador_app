"""
Módulo de carga de datos — solo accesible para el rol admin.

Permite subir exports de MicroStrategy (consumo y valores/tarifas) y
cargarlos directamente a simulador.consumo / simulador.valores en Supabase.
"""
import logging

import pandas as pd
import psycopg2.extras
import streamlit as st

from auth import get_current_role
from core.db import get_connection
from core.excel_utils import (
    CONSUMO_NUMERIC_COLS,
    EXPECTED_CONSUMO_COLS,
    VALORES_NUMERIC_COLS,
    EXPECTED_VALORES_COLS,
    clean_dataset,
    load_excel_smart,
    missing_columns,
)

logger = logging.getLogger(__name__)

_COLS_CONSUMO = [
    "Prestador ID", "Prestador Desc", "Convenio ID", "Convenio Desc",
    "Mes", "Tipo Categoria", "Megacuenta", "Gama", "Cartilla",
    "Tipo Clase CM", "Nomenclador", "Prestacion Desc", "Prestacion ID",
    "Cantidad CM", "Importe CM",
]

_COLS_VALORES = [
    "Prestador ID", "Prestador Desc", "Convenio Desc", "Convenio ID",
    "Prestacion Desc", "Prestacion ID", "Mes Vigencia", "Valor Convenido a HOY",
]


def _df_to_rows(df: pd.DataFrame, cols: list) -> list:
    """Convierte DataFrame a tuplas para psycopg2, manejando pd.NA / NaN."""
    df_obj = df[cols].astype(object).where(pd.notna(df[cols]), None)
    return [tuple(row) for row in df_obj.itertuples(index=False, name=None)]


def _insertar_tabla(
    df: pd.DataFrame,
    tabla: str,
    cols_tabla: list,
    key_col1: str,
    key_col2: str,
    mode: str,
) -> tuple:
    """
    Inserta df en simulador.<tabla>.

    mode="actualizar" — borra las combinaciones (key_col1, key_col2) que trae
                        el archivo y las reinserta; el resto queda intacto.
    mode="reemplazar" — TRUNCATE + INSERT (borra todo antes de insertar).

    Returns (filas_insertadas: int, error: str).
    """
    cols = [c for c in cols_tabla if c in df.columns]
    rows = _df_to_rows(df, cols)
    if not rows:
        return 0, "El archivo no tiene filas válidas."

    col_names = ", ".join([f'"{c}"' for c in cols])
    sql_insert = f'INSERT INTO simulador."{tabla}" ({col_names}) VALUES %s'

    try:
        con = get_connection()
    except Exception:
        logger.exception("Error conectando a la base de datos para insertar %s", tabla)
        return 0, "No se pudo conectar a la base de datos. Contactá al administrador."

    try:
        with con.cursor() as cur:
            if mode == "reemplazar":
                cur.execute(f'TRUNCATE simulador."{tabla}"')
            else:
                combos = (
                    df[[key_col1, key_col2]]
                    .drop_duplicates()
                    .dropna(subset=[key_col1, key_col2])
                    .values.tolist()
                )
                if combos:
                    cur.executemany(
                        f'DELETE FROM simulador."{tabla}" '
                        f'WHERE "{key_col1}" = %s AND "{key_col2}" = %s',
                        combos,
                    )
            psycopg2.extras.execute_values(cur, sql_insert, rows, page_size=1000)
        con.commit()
        return len(rows), ""
    except Exception:
        con.rollback()
        logger.exception("Error insertando en %s", tabla)
        return 0, "Error interno al cargar los datos. Contactá al administrador."
    finally:
        try:
            con.close()
        except Exception:
            pass


def _procesar_upload(uploaded_file, expected_cols: set, numeric_cols: set):
    """Lee y limpia un archivo subido. Devuelve (df, columnas_faltantes) o (None, None)."""
    if uploaded_file is None:
        return None, None
    with st.spinner("Procesando archivo..."):
        try:
            df = load_excel_smart(uploaded_file.getvalue(), expected_cols)
            df = clean_dataset(df, numeric_cols)
        except Exception:
            logger.exception("Error leyendo archivo subido")
            st.error("No se pudo leer el archivo. Verificá que sea un export xlsx válido.")
            return None, None
    miss = missing_columns(df, expected_cols)
    return df, miss


def render() -> None:
    if get_current_role() != "admin":
        st.error("Acceso denegado.")
        st.stop()
        return

    st.title("Carga de Datos")
    st.caption("Actualizá la base de consumo y tarifas desde exports de MicroStrategy.")

    tab_consumo, tab_valores = st.tabs(["Consumo", "Tarifas (Valores)"])

    # ── TAB CONSUMO ──────────────────────────────────────────────────────────
    with tab_consumo:
        st.markdown("##### Export de Consumo")
        uploaded_c = st.file_uploader(
            "Archivo de Consumo (xlsx)",
            type=["xlsx"],
            key="upload_consumo_admin",
            help="El mismo archivo .xlsx que descargás de MicroStrategy.",
        )
        df_c, miss_c = _procesar_upload(uploaded_c, EXPECTED_CONSUMO_COLS, CONSUMO_NUMERIC_COLS)

        if df_c is None:
            st.info("Arrastrá el archivo xlsx de consumo para comenzar.")
        else:
            if miss_c:
                st.info(f"Columnas no encontradas (se omiten): {sorted(miss_c)}")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Filas", f"{len(df_c):,}")
            prestadores = df_c["Prestador Desc"].dropna().unique() if "Prestador Desc" in df_c.columns else []
            c2.metric("Prestadores", len(prestadores))
            meses = df_c["Mes"].dropna().unique() if "Mes" in df_c.columns else []
            c3.metric("Meses", len(meses))
            importe = df_c["Importe CM"].sum() if "Importe CM" in df_c.columns else 0
            c4.metric("Importe total", f"${importe:,.0f}")

            if len(prestadores):
                st.caption(f"Prestadores: {', '.join(str(p) for p in sorted(prestadores))}")
            if len(meses):
                st.caption(f"Períodos: {', '.join(sorted(str(m) for m in meses))}")

            with st.expander("Vista previa (primeras 50 filas)"):
                st.dataframe(df_c.head(50), use_container_width=True)

            st.divider()

            mode_c = st.radio(
                "Modo de carga",
                [
                    "Actualizar — reemplaza solo este prestador/período, conserva el resto",
                    "Reemplazar todo — borra TODA la tabla antes de insertar",
                ],
                key="upload_mode_consumo",
            )
            insert_mode_c = "reemplazar" if "Reemplazar todo" in mode_c else "actualizar"

            if insert_mode_c == "reemplazar":
                st.warning(
                    "Esta acción borra TODOS los datos de consumo antes de insertar los nuevos.",
                    icon="⚠️",
                )

            if st.button("Cargar Consumo a Supabase", type="primary", key="btn_cargar_consumo"):
                with st.spinner(f"Cargando {len(df_c):,} filas..."):
                    n, err = _insertar_tabla(
                        df_c, "consumo", _COLS_CONSUMO,
                        "Prestador ID", "Mes", insert_mode_c,
                    )
                    st.cache_data.clear()
                if err:
                    st.error(f"Error al cargar: {err}")
                else:
                    st.success(f"{n:,} filas de consumo cargadas correctamente.")
                    st.balloons()

    # ── TAB VALORES ──────────────────────────────────────────────────────────
    with tab_valores:
        st.markdown("##### Export de Tarifas (Valores)")
        uploaded_v = st.file_uploader(
            "Archivo de Valores (xlsx)",
            type=["xlsx"],
            key="upload_valores_admin",
            help="El archivo de tarifas/valores convenidos de MicroStrategy.",
        )
        df_v, miss_v = _procesar_upload(uploaded_v, EXPECTED_VALORES_COLS, VALORES_NUMERIC_COLS)

        if df_v is None:
            st.info("Arrastrá el archivo xlsx de valores/tarifas para comenzar.")
        else:
            if miss_v:
                st.info(f"Columnas no encontradas (se omiten): {sorted(miss_v)}")

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Filas", f"{len(df_v):,}")
            prestadores_v = df_v["Prestador Desc"].dropna().unique() if "Prestador Desc" in df_v.columns else []
            c2.metric("Prestadores", len(prestadores_v))
            meses_v = df_v["Mes Vigencia"].dropna().unique() if "Mes Vigencia" in df_v.columns else []
            c3.metric("Períodos", len(meses_v))
            valor = df_v["Valor Convenido a HOY"].sum() if "Valor Convenido a HOY" in df_v.columns else 0
            c4.metric("Valor total", f"${valor:,.0f}")

            with st.expander("Vista previa (primeras 50 filas)"):
                st.dataframe(df_v.head(50), use_container_width=True)

            st.divider()

            mode_v = st.radio(
                "Modo de carga",
                [
                    "Actualizar — reemplaza solo este prestador/período, conserva el resto",
                    "Reemplazar todo — borra TODA la tabla antes de insertar",
                ],
                key="upload_mode_valores",
            )
            insert_mode_v = "reemplazar" if "Reemplazar todo" in mode_v else "actualizar"

            if insert_mode_v == "reemplazar":
                st.warning(
                    "Esta acción borra TODOS los datos de tarifas antes de insertar los nuevos.",
                    icon="⚠️",
                )

            if st.button("Cargar Valores a Supabase", type="primary", key="btn_cargar_valores"):
                with st.spinner(f"Cargando {len(df_v):,} filas..."):
                    n, err = _insertar_tabla(
                        df_v, "valores", _COLS_VALORES,
                        "Prestador ID", "Mes Vigencia", insert_mode_v,
                    )
                    st.cache_data.clear()
                if err:
                    st.error(f"Error al cargar: {err}")
                else:
                    st.success(f"{n:,} filas de tarifas cargadas correctamente.")
                    st.balloons()
