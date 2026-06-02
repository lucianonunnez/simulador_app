"""
Obtención de inflación argentina desde la API pública del INDEC.

Usa la API de datos.gob.ar (Agencia Argentina de Datos), que expone las
series del INDEC en formato JSON.

Serie IPC Nivel General (nacional, variación mensual %):
    148.3_INIVELNAL_DICE_M_26

Documentación: https://datosgobar.github.io/series-tiempo-ar-api/
"""

from __future__ import annotations

import pandas as pd
import requests
import streamlit as st

# Serie oficial INDEC - IPC Nacional - variación mensual %
INDEC_IPC_SERIES_ID = "148.3_INIVELNAL_DICE_M_26"
API_BASE = "https://apis.datos.gob.ar/series/api/series"


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_inflation(months: int = 12) -> pd.DataFrame:
    """
    Descarga los últimos N meses de inflación mensual del INDEC.

    Returns:
        DataFrame con columnas ['Mes', 'Inflacion'] ordenadas por fecha desc.
        DataFrame vacío si la API falla (caller debe manejar el fallback).
    """
    params = {
        "ids": INDEC_IPC_SERIES_ID,
        "limit": months,
        "sort": "desc",
        "format": "json",
    }

    try:
        resp = requests.get(API_BASE, params=params, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return pd.DataFrame(columns=["Mes", "Inflacion"])

    # La API devuelve {"data": [["2024-10-01", 2.7], ["2024-09-01", 3.5], ...]}
    data = payload.get("data", [])
    if not data:
        return pd.DataFrame(columns=["Mes", "Inflacion"])

    df = pd.DataFrame(data, columns=["Mes", "Inflacion"])
    df["Mes"] = pd.to_datetime(df["Mes"], errors="coerce")
    df["Inflacion"] = pd.to_numeric(df["Inflacion"], errors="coerce")
    df = df.dropna().sort_values("Mes", ascending=False).reset_index(drop=True)

    return df