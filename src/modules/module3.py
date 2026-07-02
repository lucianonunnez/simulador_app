"""
Módulo 3 — Predicción ML.

Orquesta:
1. Reusa carga de datos del Módulo 1 (caché compartido).
2. Verifica que los modelos estén disponibles (degradación parcial: con los
   LightGBM alcanza; la red neuronal es opcional y solo suma la comparativa).
3. Controles en sidebar (ui/ml_controls).
4. Renderizado de 5 tabs (ui/ml_tabs).

Si faltan los LightGBM (el mínimo), muestra instrucciones para subirlos.
"""

from __future__ import annotations

import streamlit as st

from core.data_loader import get_normalized_consumo, load_consumo_and_valores
from core.ml_predictor import estado_modelos
from ui.formatters import format_int
from ui.ml_controls import render_ml_controls
from ui.ml_tabs import render_tabs


def render() -> None:
    st.title("Módulo 3 — Predicción ML")

    # --- Verificar modelos: LightGBM es el mínimo; la red neuronal, opcional ---
    estado = estado_modelos()

    if not estado["lightgbm_ok"]:
        faltantes = [
            k for k, v in estado["detalle"].items()
            if not v and k.startswith("lightgbm")
        ]
        st.error("**No se encontraron los modelos LightGBM (mínimo para predecir)**")
        st.markdown(f"Faltan o no son usables: `{', '.join(faltantes)}`")
        st.info("""
        **Cómo solucionarlo:**

        1. Corré el notebook `entrenar_modelos.ipynb` en Google Colab
        2. Descargá el ZIP con los modelos
        3. Subí los archivos al repo en una carpeta `models/` en la raíz

        Ante dudas, contactá al área de Datos/IA.
        """)
        return

    if not estado["nn_ok"]:
        # Aviso discreto: el módulo funciona igual, solo sin la comparativa NN
        st.caption(
            f"Comparativa con red neuronal no disponible: {estado['nn_motivo']}. "
            "El módulo funciona en modo LightGBM."
        )

    # --- Datos ---
    df_consumo, _ = load_consumo_and_valores()
    if df_consumo is None:
        st.info(
            "**Esperando datos** — Abrí la sección **«Carga de datos»** del menú "
            "izquierdo y subí el archivo de Consumo (o corré `python scripts/ingest.py`)."
        )
        return

    st.caption(f"Dataset cargado: **{format_int(len(df_consumo))}** registros")

    df_consumo = get_normalized_consumo(df_consumo)

    # --- Prestadores disponibles (para el filtro del sidebar) ---
    prestadores = (
        df_consumo[["Prestador ID", "Prestador Desc"]]
        .drop_duplicates()
        .sort_values("Prestador Desc")
        .values.tolist()
    )

    # --- Controles sidebar ---
    config = render_ml_controls(
        prestadores_disponibles=prestadores,
        nn_disponible=estado["nn_ok"],
    )

    # --- Tabs ---
    render_tabs(df_consumo, config)
