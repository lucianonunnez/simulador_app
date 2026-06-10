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

import re
from io import BytesIO, StringIO

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


# ============================================================================
# SOPORTE CSV (los exports reales de MicroStrategy también vienen en CSV,
# con encodings dispares verificados: UTF-8 con BOM, Windows cp1252 y
# Mac OS Roman con finales de línea CR)
# ============================================================================

# Caracteres de control que rompen el parseo (se preservan \t y \n).
_CTRL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# Letras españolas legítimas: criterio para elegir encoding.
_LETRAS_ES = re.compile(r"[áéíóúñüÁÉÍÓÚÑÜ]")


def _decode_text(content: bytes) -> str:
    """
    Decodifica un CSV probando los encodings reales de los exports.

    UTF-8 es inequívoco (si decodifica, es correcto). cp1252 y mac_roman en
    cambio "aceptan" casi cualquier byte: un export Mac leído como cp1252
    produce '—' donde iba 'ó', sin error. Por eso se elige la decodificación
    que produce más letras españolas legítimas. Después se normalizan los
    finales de línea CR (export Mac) y se eliminan caracteres de control
    sueltos (los exports reales traían un 0x1A embebido).
    """
    try:
        texto = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        candidatos = []
        for enc in ("cp1252", "mac_roman", "latin-1"):
            try:
                t = content.decode(enc)
            except UnicodeDecodeError:
                continue
            candidatos.append((len(_LETRAS_ES.findall(t)), t))
        texto = max(candidatos, key=lambda c: c[0])[1]
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    return _CTRL_CHARS.sub("", texto)


def _read_csv_smart(texto: str, expected_cols: set) -> pd.DataFrame:
    """Lee un CSV detectando separador y fila de encabezado (mismo criterio
    que detect_header_row: la fila con más columnas esperadas)."""
    lineas = texto.split("\n")[:10]
    sep = max((",", ";", "\t"), key=lambda c: lineas[0].count(c))

    best_row, best_matches = 0, 0
    for i, ln in enumerate(lineas):
        matches = len({p.strip() for p in ln.split(sep)} & set(expected_cols))
        if matches > best_matches:
            best_row, best_matches = i, matches
    skiprows = best_row if best_matches >= 3 else 0

    return pd.read_csv(StringIO(texto), sep=sep, skiprows=skiprows, low_memory=False)


# ============================================================================
# MAPEO DE COLUMNAS CRUDAS DE MICROSTRATEGY
# ============================================================================

# Cada atributo del export crudo sale como un grupo: una columna nombrada
# ('Prestador') seguida de columnas 'Unnamed: N' (el ID y la descripción,
# en orden que VARÍA según el reporte).
_MSTR_GRUPOS = {
    "Prestador": ("Prestador ID", "Prestador Desc"),
    "Convenio": ("Convenio ID", "Convenio Desc"),
    "Prestacion": ("Prestacion ID", "Prestacion Desc"),
}


def normalize_mstr_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Renombra las columnas del export CRUDO de MicroStrategy al contrato de la app.

    Cuál columna del grupo trae el ID y cuál la descripción varía según el
    reporte (verificado con exports reales: en consumo el ID va primero, en
    valores al revés), así que se decide por contenido: ID = la mayormente
    numérica; Desc = la de texto más largo. Si ninguna es numérica (ej: el
    'Convenio' del consumo trae un flag, no un ID), solo se mapea la Desc y
    el ID queda genuinamente ausente (el contrato lo reporta como faltante).

    Archivos ya curados (con 'X ID'/'X Desc' presentes) pasan intactos.
    Las columnas 'Unnamed' sobrantes (flags sin nombre) se descartan.
    """
    df = df.copy()
    cols = list(df.columns)
    rename: dict = {}

    def _share_numerica(c) -> float:
        s = df[c].dropna().astype(str).head(200)
        return to_numeric_tolerante(s).notna().mean() if len(s) else 0.0

    def _largo_medio(c) -> float:
        s = df[c].dropna().astype(str).head(200)
        return float(s.str.len().mean()) if len(s) else 0.0

    for i, col in enumerate(cols):
        base = str(col).strip()
        if base not in _MSTR_GRUPOS:
            continue
        id_col, desc_col = _MSTR_GRUPOS[base]
        if id_col in cols or desc_col in cols:
            continue  # archivo ya curado: no tocar

        grupo = [col]
        j = i + 1
        while j < len(cols) and str(cols[j]).startswith("Unnamed"):
            grupo.append(cols[j])
            j += 1
        if len(grupo) < 2:
            continue

        shares = {c: _share_numerica(c) for c in grupo}
        candidata_id = max(shares, key=shares.get)
        if shares[candidata_id] >= 0.8:
            rename[candidata_id] = id_col
            restantes = [c for c in grupo if c != candidata_id]
        else:
            restantes = grupo  # el export no trae un ID real para este grupo
        if restantes:
            rename[max(restantes, key=_largo_medio)] = desc_col

    if rename:
        df = df.rename(columns=rename)
        sobrantes = [c for c in df.columns if str(c).startswith("Unnamed")]
        df = df.drop(columns=sobrantes)
    return df


def load_excel_smart(file_content: bytes, expected_cols: set) -> pd.DataFrame:
    """
    Carga un export (xlsx o CSV) autodetectando formato, encoding y encabezado,
    y normalizando las columnas crudas de MicroStrategy al contrato de la app.
    """
    if file_content[:2] == b"PK":  # firma ZIP -> xlsx
        skiprows = detect_header_row(file_content, expected_cols)
        df = pd.read_excel(BytesIO(file_content), skiprows=skiprows, engine="openpyxl")
    else:  # CSV
        texto = _decode_text(file_content)
        df = _read_csv_smart(texto, expected_cols)
    df.columns = df.columns.astype(str).str.strip().str.lstrip("\ufeff")
    return normalize_mstr_columns(df)


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
    '8,206.90' (formato US: coma = miles, punto = decimal), '-' como vacío y
    negativos contables entre paréntesis: '(5,477,196)'. Un to_numeric directo
    los convertía a NaN y se perdían las filas. Acá se limpian antes de coaccionar.

    Asume formato US (el de MicroStrategy). No aplicar sobre columnas que
    pudieran venir con coma decimal.
    """
    if s.dtype == object or pd.api.types.is_string_dtype(s):
        s = s.astype(str).str.strip()
        # Negativos contables: '(1,234)' -> '-1234'
        s = s.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
        s = s.str.replace(",", "", regex=False)
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
    - Descarta filas EXACTAMENTE duplicadas: los exports son agregados
      (una fila por combinación de atributos), así que una fila idéntica
      repetida es un duplicado real, no dos eventos distintos. Entre archivos
      no hace falta: el upsert por (Prestador, Mes) ya reemplaza en vez de
      acumular.
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

    df = df.drop_duplicates().reset_index(drop=True)

    for col in (numeric_cols & _ID_COLS):
        if col in df.columns:
            df[col] = df[col].astype("Int64")

    return df
