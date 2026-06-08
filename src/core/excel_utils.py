"""
Utilidades puras para leer los Excel de MicroStrategy.

Sin dependencia de Streamlit ni de DuckDB: solo pandas. Esto permite reutilizar
la MISMA lógica de parseo desde la app (src/core/data_loader.py) y desde el
script de ingesta (scripts/ingest.py), y es el primer paso para desacoplar
core/ de Streamlit (Fase 0 de ARQUITECTURA.md).

Acá viven:
  - Los contratos de columnas esperadas (EXPECTED_*_COLS).
  - La autodetección de la fila de encabezado (reemplaza el viejo skiprows=3
    hardcodeado, que rompía cuando el Excel no traía las 3 filas de título de
    Power BI / MicroStrategy).
"""

from __future__ import annotations

from io import BytesIO

import pandas as pd


# ============================================================================
# COLUMNAS ESPERADAS (contratos de cada dataset)
# ============================================================================
EXPECTED_CONSUMO_COLS = {
    "Prestador ID", "Prestador Desc", "Convenio ID", "Convenio Desc",
    "Mes", "Tipo Categoria", "Megacuenta", "Gama", "Cartilla",
    "Tipo Clase CM", "Nomenclador", "Prestacion Desc", "Prestacion ID",
    "Cantidad CM", "Importe CM",
}

EXPECTED_VALORES_COLS = {
    "Prestador ID", "Prestador Desc", "Convenio Desc", "Convenio ID",
    "Prestacion Desc", "Prestacion ID", "Mes Vigencia", "Valor Convenido a HOY",
}

# Columna que marca el grano mensual en cada dataset.
CONSUMO_MES_COL = "Mes"
VALORES_MES_COL = "Mes Vigencia"

# Columnas numéricas de cada dataset. Se coaccionan a número al cargar, lo que
# neutraliza las filas de "Total"/"Subtotal" que MicroStrategy agrega al final
# (texto en columnas numéricas) y que rompen el tipado de DuckDB.
CONSUMO_NUMERIC_COLS = {
    "Prestador ID", "Convenio ID", "Prestacion ID", "Cantidad CM", "Importe CM",
}
VALORES_NUMERIC_COLS = {
    "Prestador ID", "Convenio ID", "Prestacion ID", "Valor Convenido a HOY",
}

# Columnas de identificador (se dejan como entero, sin decimales).
_ID_COLS = {"Prestador ID", "Convenio ID", "Prestacion ID"}


# ============================================================================
# AUTODETECCIÓN DE ENCABEZADOS
# ============================================================================
def detect_header_row(file_content: bytes, expected_cols: set, max_rows: int = 10) -> int:
    """
    Detecta en qué fila está el encabezado real.

    Reemplaza el bug original (skiprows=3 hardcoded), que rompía cuando el Excel
    no traía 3 filas de título de Power BI / MicroStrategy.
    """
    buf = BytesIO(file_content)
    preview = pd.read_excel(buf, header=None, nrows=max_rows, engine="openpyxl")

    best_row = 0
    best_matches = 0

    for row_idx in range(len(preview)):
        row_values = set(preview.iloc[row_idx].astype(str).str.strip())
        matches = len(row_values & set(expected_cols))
        if matches > best_matches:
            best_matches = matches
            best_row = row_idx

    if best_matches < 3:
        return 0

    return best_row


def load_excel_smart(file_content: bytes, expected_cols: set) -> pd.DataFrame:
    """Carga un Excel autodetectando la fila de encabezado y limpiando nombres."""
    skiprows = detect_header_row(file_content, expected_cols)
    buf = BytesIO(file_content)
    df = pd.read_excel(buf, skiprows=skiprows, engine="openpyxl")
    df.columns = df.columns.astype(str).str.strip()
    return df


def missing_columns(df: pd.DataFrame, expected_cols: set) -> set:
    """Devuelve las columnas esperadas que NO están en el df (vacío = OK)."""
    return set(expected_cols) - set(df.columns)


def clean_dataset(
    df: pd.DataFrame,
    numeric_cols: set,
    key_col: str = "Prestador ID",
) -> pd.DataFrame:
    """
    Limpia el DataFrame antes de cargarlo a DuckDB.

    - Coacciona las columnas numéricas a número (lo que no es número -> NaN).
      Así una fila de "Total" con texto en una columna numérica no rompe el
      tipado estricto de DuckDB.
    - Descarta las filas sin clave válida (key_col NaN): elimina justamente esas
      filas de Total/Subtotal de los exports de MicroStrategy.
    - Deja los IDs como enteros nullable (sin el ".0" de los floats).
    """
    df = df.copy()

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if key_col in df.columns:
        df = df[df[key_col].notna()].reset_index(drop=True)

    for col in (numeric_cols & _ID_COLS):
        if col in df.columns:
            df[col] = df[col].astype("Int64")

    return df
