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

from core.data_loader import get_normalized_consumo, load_consumo_and_valores
from ui.anomaly_controls import render_anomaly_controls
from ui.formatters import format_int
from ui.anomaly_tabs import render_tabs


def render() -> None:
    """Entry point del Módulo 2."""
    st.title("Módulo 2 — Detección de Desvíos")

    # --- Carga de datos (reusa caché del Módulo 1) ---
    df_consumo, _df_valores = load_consumo_and_valores()

    if df_consumo is None:
        from auth import get_current_role

        st.info(
            "**Esperando datos** — "
            + (
                "Abrí la sección **«Carga de datos»** del menú izquierdo y subí el archivo de Consumo."
                if get_current_role() == "admin"
                else "Los datos aún no fueron cargados. Aguardá a que el administrador cargue los archivos."
            )
        )
        if st.button("Recargar datos", key="reload_waiting_m2"):
            st.cache_data.clear()
            st.rerun()
        return

    st.caption(f"Analizando **{format_int(len(df_consumo))}** registros")

    # --- Normalizar tipos (cacheado, mismo helper que Módulo 1) ---
    df_consumo = get_normalized_consumo(df_consumo)

    # --- Controles en sidebar ---
    config = render_anomaly_controls()

    # --- Renderizar los 4 tabs ---
    render_tabs(df_consumo, config)