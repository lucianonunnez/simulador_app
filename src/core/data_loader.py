"""
Carga de datos de consumo y valores.

Estrategia (en orden de prioridad):
1. Carpeta local 'data/' si existe (modo oficina - datos precargados)
2. URLs de OneDrive (si están en secrets.toml)
3. Upload manual desde la UI (fallback universal)

Usa caché de Streamlit para no recargar en cada interacción.
"""

from __future__ import annotations

import base64
import time
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import requests
import streamlit as st


# ============================================================================
# COLUMNAS ESPERADAS
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

# Carpeta local donde buscar los archivos precargados (modo oficina)
LOCAL_DATA_DIR = Path("data")
LOCAL_CONSUMO_FILE = LOCAL_DATA_DIR / "consumo.xlsx"
LOCAL_VALORES_FILE = LOCAL_DATA_DIR / "valores.xlsx"


# ============================================================================
# AUTODETECCIÓN DE ENCABEZADOS
# ============================================================================
def _detect_header_row(file_content: bytes, expected_cols: set, max_rows: int = 10) -> int:
    """
    Detecta en qué fila está el encabezado real.

    Reemplaza el bug original (skiprows=3 hardcoded), que rompía cuando
    el Excel no traía 3 filas de título de Power BI.
    """
    buf = BytesIO(file_content)
    preview = pd.read_excel(buf, header=None, nrows=max_rows, engine="openpyxl")

    best_row = 0
    best_matches = 0

    for row_idx in range(len(preview)):
        row_values = set(preview.iloc[row_idx].astype(str).str.strip())
        matches = len(row_values & expected_cols)
        if matches > best_matches:
            best_matches = matches
            best_row = row_idx

    if best_matches < 3:
        return 0

    return best_row


def _load_excel_smart(file_content: bytes, expected_cols: set) -> pd.DataFrame:
    """Carga un Excel autodetectando la fila de encabezado."""
    skiprows = _detect_header_row(file_content, expected_cols)
    buf = BytesIO(file_content)
    df = pd.read_excel(buf, skiprows=skiprows, engine="openpyxl")
    df.columns = df.columns.astype(str).str.strip()
    return df


# ============================================================================
# LECTURA DESDE CARPETA LOCAL (modo oficina)
# ============================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def _load_from_local_file(path_str: str, _expected_cols: frozenset) -> Optional[pd.DataFrame]:
    """
    Carga un archivo local (desde carpeta data/).
    Resultado cacheado 1 hora para no re-leer en cada interacción.

    Recibe path_str (no Path) porque st.cache_data necesita argumentos hasheables.
    """
    path = Path(path_str)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            content = f.read()
        return _load_excel_smart(content, set(_expected_cols))
    except Exception as e:
        st.error(f"❌ Error leyendo archivo local {path.name}: {e}")
        return None


def _check_local_files() -> Tuple[bool, bool]:
    """Chequea si existen los archivos locales precargados."""
    return LOCAL_CONSUMO_FILE.exists(), LOCAL_VALORES_FILE.exists()


# ============================================================================
# DESCARGA DESDE ONEDRIVE
# ============================================================================
def _onedrive_to_direct_url(sharing_url: str) -> str:
    """Convierte un link de compartir de OneDrive a URL de descarga directa."""
    if not sharing_url or not isinstance(sharing_url, str):
        return ""

    sharing_url = sharing_url.strip()

    if "1drv.ms" in sharing_url:
        try:
            parts = sharing_url.split("?")[0].split("/")
            if len(parts) >= 2:
                res_id = "/".join(parts[-2:])
                if res_id:
                    encoded = base64.urlsafe_b64encode(res_id.encode()).decode().rstrip("=")
                    return f"https://api.onedrive.com/v1.0/shares/u!{encoded}/root/content"
        except Exception:
            pass

    if "/personal/" in sharing_url or "/business/" in sharing_url:
        if "redir?resid=" in sharing_url:
            return sharing_url.replace("redir?resid=", "download?resid=")
        if "?" not in sharing_url:
            return sharing_url + "?download=1"

    return sharing_url


def _download_with_retries(url: str, retries: int = 3, timeout: int = 30) -> Optional[bytes]:
    """Descarga con reintentos y backoff exponencial."""
    if not url:
        return None

    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=timeout, allow_redirects=True)
            resp.raise_for_status()
            return resp.content
        except requests.exceptions.RequestException:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            return None

    return None


# ============================================================================
# API PÚBLICA
# ============================================================================
@st.cache_data(ttl=600, show_spinner=False)
def _load_from_onedrive_cached(url: str, _expected_cols: frozenset) -> Optional[pd.DataFrame]:
    """Descarga y parsea un Excel desde OneDrive. Resultado cacheado 10 min."""
    direct_url = _onedrive_to_direct_url(url)
    content = _download_with_retries(direct_url)
    if content is None:
        return None
    return _load_excel_smart(content, set(_expected_cols))


def _load_from_upload(uploaded_file, expected_cols: set, label: str) -> Optional[pd.DataFrame]:
    """Carga un archivo subido manualmente."""
    if uploaded_file is None:
        return None

    try:
        with st.spinner(f"📥 Leyendo {label}..."):
            content = uploaded_file.read()
            df = _load_excel_smart(content, expected_cols)
        return df
    except Exception as e:
        st.error(f"❌ Error leyendo {label}: {e}")
        return None


def load_consumo_and_valores() -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Carga los dos datasets en este orden de prioridad:

    1. Carpeta local 'data/' (modo oficina con archivos precargados).
    2. URLs de OneDrive (si están configuradas en secrets.toml).
    3. Upload manual desde la UI (fallback universal).

    Returns:
        (df_consumo, df_valores). Cada uno puede ser None si no se cargó.
    """
    df_consumo = None
    df_valores = None

    # ---- 1. Intento: carpeta local ----
    has_local_consumo, has_local_valores = _check_local_files()

    if has_local_consumo or has_local_valores:
        with st.sidebar.expander("📂 Carga de datos", expanded=True):
            if has_local_consumo:
                with st.spinner("Leyendo Consumo desde carpeta local..."):
                    df_consumo = _load_from_local_file(
                        str(LOCAL_CONSUMO_FILE),
                        frozenset(EXPECTED_CONSUMO_COLS),
                    )
                if df_consumo is not None:
                    st.success(f"💾 Consumo (local): {len(df_consumo):,} filas")

            if has_local_valores:
                with st.spinner("Leyendo Valores desde carpeta local..."):
                    df_valores = _load_from_local_file(
                        str(LOCAL_VALORES_FILE),
                        frozenset(EXPECTED_VALORES_COLS),
                    )
                if df_valores is not None:
                    st.success(f"💾 Valores (local): {len(df_valores):,} filas")

        # Si ambos cargaron localmente, listo
        if df_consumo is not None and df_valores is not None:
            return df_consumo, df_valores

    # ---- 2. Intento: OneDrive ----
    onedrive_consumo = _get_secret("onedrive_consumo_url")
    onedrive_valores = _get_secret("onedrive_valores_url")

    with st.sidebar.expander("📂 Carga de datos", expanded=True):
        # ---- OneDrive: Consumo ----
        if df_consumo is None and onedrive_consumo:
            with st.spinner("Descargando Consumo desde OneDrive..."):
                df_consumo = _load_from_onedrive_cached(
                    onedrive_consumo,
                    frozenset(EXPECTED_CONSUMO_COLS),
                )
            if df_consumo is not None:
                st.success(f"☁️ Consumo (OneDrive): {len(df_consumo):,} filas")
            else:
                st.warning(
                    "⚠️ No se pudo descargar Consumo desde OneDrive. "
                    "Subilo manualmente abajo."
                )

        # ---- OneDrive: Valores ----
        if df_valores is None and onedrive_valores:
            with st.spinner("Descargando Valores desde OneDrive..."):
                df_valores = _load_from_onedrive_cached(
                    onedrive_valores,
                    frozenset(EXPECTED_VALORES_COLS),
                )
            if df_valores is not None:
                st.success(f"☁️ Valores (OneDrive): {len(df_valores):,} filas")
            else:
                st.warning(
                    "⚠️ No se pudo descargar Valores desde OneDrive. "
                    "Subilo manualmente abajo."
                )

        # ---- 3. Fallback: upload manual ----
        if df_consumo is None:
            st.divider()
            st.caption("📄 Archivo de Consumo")
            up_c = st.file_uploader(
                "Subir Consumo (xlsx)",
                type=["xlsx"],
                key="upload_consumo",
                label_visibility="collapsed",
            )
            if up_c is not None:
                df_consumo = _load_from_upload(up_c, EXPECTED_CONSUMO_COLS, "Consumo")
                if df_consumo is not None:
                    st.success(f"✅ Consumo cargado: {len(df_consumo):,} filas")

        if df_valores is None:
            st.divider()
            st.caption("📄 Archivo de Valores")
            up_v = st.file_uploader(
                "Subir Valores (xlsx)",
                type=["xlsx"],
                key="upload_valores",
                label_visibility="collapsed",
            )
            if up_v is not None:
                df_valores = _load_from_upload(up_v, EXPECTED_VALORES_COLS, "Valores")
                if df_valores is not None:
                    st.success(f"✅ Valores cargado: {len(df_valores):,} filas")

    return df_consumo, df_valores


def _get_secret(key: str) -> str:
    """Lee un secret sin romper si no existe."""
    try:
        return st.secrets.get(key, "")
    except Exception:
        return ""