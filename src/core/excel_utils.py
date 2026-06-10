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


# Nombres de mes en español -> número. Los exports reales de MicroStrategy
# traen "Mes Vigencia" como 'Mayo 2026', 'Diciembre 2024' (verificado con datos
# reales); sin este mapa la normalización los dejaba sin parsear.
_MESES_ES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "setiembre": "09", "octubre": "10",
    "noviembre": "11", "diciembre": "12",
    # Abreviaturas comunes
    "ene": "01", "feb": "02", "mar": "03", "abr": "04", "may": "05",
    "jun": "06", "jul": "07", "ago": "08", "sep": "09", "set": "09",
    "oct": "10", "nov": "11", "dic": "12",
}


def _parse_mes_espanol(s: pd.Series) -> pd.Series:
    """'Mayo 2026' / 'dic. 2025' / 'Enero de 2024' -> datetime (NaT si no matchea)."""
    partes = (
        s.astype(str).str.strip().str.lower()
        .str.extract(r"^([a-záéíóúñ]+)\.?\s+(?:de\s+)?(\d{4})$")
    )
    mm = partes[0].map(_MESES_ES)
    return pd.to_datetime(mm + "-" + partes[1], format="%m-%Y", errors="coerce")


def normalize_month_series(s: pd.Series) -> pd.Series:
    """
    Normaliza una columna de mes a formato canónico 'MM-YYYY' (string).

    MicroStrategy/openpyxl puede entregar el mes como texto ('01-2025'),
    nombre de mes en español ('Mayo 2026'), datetime/Timestamp, o 'YYYY-MM-DD'.
    Si no se normaliza, el upsert por (Prestador, Mes) puede no matchear y
    DUPLICAR el período, y los filtros de mes de la app (que asumen 'MM-YYYY')
    fallan. Acá lo unificamos.

    Los valores que no se pueden parsear se conservan como string (no se pierden).
    """
    dt = pd.to_datetime(s, format="%m-%Y", errors="coerce")
    pendientes = dt.isna()
    if pendientes.any():
        # Nombres de mes en español ('Mayo 2026'), como vienen en los exports.
        dt = dt.mask(pendientes, _parse_mes_espanol(s.where(pendientes)))
        pendientes = dt.isna()
    if pendientes.any():
        # Parser genérico para datetime/Timestamp/'YYYY-MM-DD'/etc.
        dt = dt.mask(pendientes, pd.to_datetime(s.where(pendientes), errors="coerce"))
    canonico = dt.dt.strftime("%m-%Y")
    # Donde no se pudo parsear, dejar el valor original (limpio) como fallback.
    return canonico.where(dt.notna(), s.astype(str).str.strip())


def to_numeric_tolerante(s: pd.Series) -> pd.Series:
    """
    pd.to_numeric tolerante con números formateados como TEXTO.

    Los exports reales de MicroStrategy traen valores tipo '1,130 ', '23,653 ',
    '8,206.90' (formato US: coma = miles, punto = decimal) y '-' como vacío.
    Un to_numeric directo los convertía a NaN y se perdían las filas. Acá se
    quitan separadores de miles y espacios antes de coaccionar.

    Asume formato US (el de MicroStrategy). No aplicar sobre columnas que
    pudieran venir con coma decimal.
    """
    if s.dtype == object or pd.api.types.is_string_dtype(s):
        s = s.astype(str).str.strip().str.replace(",", "", regex=False)
        s = s.replace({"": None, "nan": None, "None": None, "-": None})
    return pd.to_numeric(s, errors="coerce")


def clean_dataset(
    df: pd.DataFrame,
    numeric_cols: set,
    key_col: str = "Prestador ID",
) -> pd.DataFrame:
    """
    Limpia el DataFrame antes de cargarlo a DuckDB.

    - Coacciona las columnas numéricas a número (lo que no es número -> NaN),
      tolerando texto con separadores de miles ('1,130 ' -> 1130). Así una fila
      de "Total" con texto en una columna numérica no rompe el tipado estricto
      de DuckDB, y los exports con números formateados no pierden datos.
    - Normaliza las columnas de mes ('Mes' / 'Mes Vigencia') a 'MM-YYYY' para
      que el upsert y los filtros sean consistentes (evita duplicar períodos).
    - Descarta las filas sin clave válida (key_col NaN): elimina justamente esas
      filas de Total/Subtotal de los exports de MicroStrategy.
    - Deja los IDs como enteros nullable (sin el ".0" de los floats).
    """
    df = df.copy()

    for col in numeric_cols:
        if col in df.columns:
            df[col] = to_numeric_tolerante(df[col])

    for mcol in (CONSUMO_MES_COL, VALORES_MES_COL):
        if mcol in df.columns:
            df[mcol] = normalize_month_series(df[mcol])

    if key_col in df.columns:
        df = df[df[key_col].notna()].reset_index(drop=True)

    for col in (numeric_cols & _ID_COLS):
        if col in df.columns:
            df[col] = df[col].astype("Int64")

    return df
