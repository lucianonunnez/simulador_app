"""
Controles del Módulo 2 (Detección de Desvíos) en el sidebar.

Devuelve un dict con la configuración elegida por el usuario.
"""

from __future__ import annotations

import streamlit as st


def render_anomaly_controls() -> dict:
    """
    Renderiza los controles y devuelve un dict con la configuración.

    Returns:
        {
            "analysis_type": "temporal" | "estructural" | "ambos",
            "metric": "precio_unitario" | "importe_total" | "cantidad",
            "temporal_method": "z_score" | "iqr",
            "threshold_temporal": float,
            "window": int,
            "structural_method": "percentile" | "z_score_cross",
            "threshold_structural": float,
        }
    """
    config = {}

    with st.sidebar.expander("Configuración de Detección", expanded=True):

        # --- Tipo de análisis ---
        analysis_label = st.radio(
            "Tipo de análisis",
            ["Temporal", "Estructural", "Ambos (intersección)"],
            help=(
                "• **Temporal**: compara cada registro contra su propia historia.\n"
                "• **Estructural**: compara cada registro contra sus pares del mismo mes.\n"
                "• **Ambos**: solo marca alertas cuando los dos métodos coinciden."
            ),
        )
        analysis_map = {
            "Temporal": "temporal",
            "Estructural": "estructural",
            "Ambos (intersección)": "ambos",
        }
        config["analysis_type"] = analysis_map[analysis_label]

        st.divider()

        # --- Métrica ---
        metric_label = st.radio(
            "Métrica a analizar",
            ["Precio unitario", "Importe total", "Cantidad"],
            help=(
                "• **Precio unitario** = Importe / Cantidad. Ideal para auditoría de tarifas.\n"
                "• **Importe total**: plata total facturada.\n"
                "• **Cantidad**: volumen de prestaciones."
            ),
        )
        metric_map = {
            "Precio unitario": "precio_unitario",
            "Importe total": "importe_total",
            "Cantidad": "cantidad",
        }
        config["metric"] = metric_map[metric_label]

    # --- Parámetros temporales ---
    if config["analysis_type"] in ("temporal", "ambos"):
        with st.sidebar.expander("Parámetros — Análisis Temporal", expanded=True):
            temporal_method_label = st.radio(
                "Método",
                ["Z-score", "IQR"],
                help=(
                    "• **Z-score**: asume distribución normal. Marca si se aleja más de N σ.\n"
                    "• **IQR**: no asume distribución. Marca si está fuera de Q1-k·IQR o Q3+k·IQR."
                ),
                key="temporal_method_radio",
            )
            config["temporal_method"] = "z_score" if temporal_method_label == "Z-score" else "iqr"

            config["window"] = st.slider(
                "Ventana temporal (meses)",
                min_value=3,
                max_value=12,
                value=6,
                help="Cuántos meses de historia usar para establecer el comportamiento normal.",
            )

            if config["temporal_method"] == "z_score":
                config["threshold_temporal"] = st.slider(
                    "Umbral (σ)",
                    min_value=1.0,
                    max_value=4.0,
                    value=2.0,
                    step=0.5,
                    help="Cuántos desvíos estándar de distancia para marcar como anomalía.",
                )
            else:
                config["threshold_temporal"] = st.slider(
                    "Multiplicador IQR (k)",
                    min_value=1.0,
                    max_value=3.0,
                    value=1.5,
                    step=0.25,
                    help="Multiplicador del rango intercuartílico. 1.5 es estándar estadístico.",
                )
    else:
        config["temporal_method"] = "z_score"
        config["window"] = 6
        config["threshold_temporal"] = 2.0

    # --- Parámetros estructurales ---
    if config["analysis_type"] in ("estructural", "ambos"):
        with st.sidebar.expander("Parámetros — Análisis Estructural", expanded=True):
            structural_method_label = st.radio(
                "Método",
                ["Percentil", "Z-score vs pares"],
                help=(
                    "• **Percentil**: marca si este registro queda en los extremos "
                    "del ranking de sus pares.\n"
                    "• **Z-score vs pares**: desvíos respecto de la media del grupo."
                ),
                key="structural_method_radio",
            )
            config["structural_method"] = (
                "percentile" if structural_method_label == "Percentil" else "z_score_cross"
            )

            if config["structural_method"] == "percentile":
                config["threshold_structural"] = st.slider(
                    "Percentil de corte",
                    min_value=75.0,
                    max_value=99.0,
                    value=90.0,
                    step=1.0,
                    help=(
                        "Se marcan los registros que quedan sobre este percentil "
                        "(o bajo el percentil complementario)."
                    ),
                )
            else:
                config["threshold_structural"] = st.slider(
                    "Umbral (σ vs pares)",
                    min_value=1.0,
                    max_value=4.0,
                    value=2.0,
                    step=0.5,
                )
    else:
        config["structural_method"] = "percentile"
        config["threshold_structural"] = 90.0

    # --- Nota sobre ML ---
    with st.sidebar.expander("Detección con ML", expanded=False):
        st.info(
            "La detección basada en modelo LightGBM se agrega en el **Hito 5**, "
            "cuando tengamos el modelo entrenado. Por ahora usamos solo métodos "
            "estadísticos, que son rápidos e interpretables."
        )

    return config