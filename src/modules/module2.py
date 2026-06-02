"""
Módulo 2 — Detección de Desvíos / Anomalías.

Orquesta:
1. Reusa la carga de datos del Módulo 1 (caché compartido).
2. Controles en sidebar (ui/anomaly_controls).
3. Renderizado de 4 tabs (ui/anomaly_tabs).

Métodos implementados en este hito (estadísticos puros):
- Temporal: z-score / IQR con ventana móvil
- Estructural: percentil / z-score vs pares

En el Hito 5 se suma LightGBM como método alternativo.
"""

from __future__ import annotations

import streamlit as st

from core.data_loader import load_consumo_and_valores
from core.simulator import normalize_dataframes
from ui.anomaly_controls import render_anomaly_controls
from ui.anomaly_tabs import render_tabs


def render() -> None:
    """Entry point del Módulo 2."""
    st.title("Módulo 2 — Detección de Desvíos")

    # --- Carga de datos (reusa caché del Módulo 1) ---
    df_consumo, _df_valores = load_consumo_and_valores()

    if df_consumo is None:
        st.info(
            "**Esperando datos** — Subí `consumo.xlsx` desde el sidebar "
            "(expandí la sección **Carga de datos**). "
            "Si ya lo cargaste en el Módulo 1, debería aparecer automáticamente."
        )
        return

    st.caption(f"Analizando **{len(df_consumo):,}** registros")

    # --- Normalizar tipos (mismo helper que Módulo 1) ---
    df_consumo, _ = normalize_dataframes(df_consumo, df_consumo.iloc[:0])

    # --- Controles en sidebar ---
    config = render_anomaly_controls()

    # --- Renderizar los 4 tabs ---
    render_tabs(df_consumo, config)