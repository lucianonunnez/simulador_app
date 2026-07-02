"""
Controles del Módulo 3 (Predicción ML) en el sidebar.

Devuelve un dict con la configuración elegida por el usuario.
"""

from __future__ import annotations

import streamlit as st


def render_ml_controls(prestadores_disponibles: list = None,
                       nn_disponible: bool = True) -> dict:
    """
    Renderiza los controles del sidebar y devuelve un dict con la configuración.

    Args:
        prestadores_disponibles: lista de tuplas (id, desc) para el selector
        nn_disponible: si la red neuronal está disponible (archivos + tensorflow);
            si no, el checkbox queda deshabilitado y el módulo corre LightGBM-only

    Returns:
        {
            "metric": "importe" | "precio" | "cantidad",
            "models": list[str],        # ["lightgbm", "pablo_corregido"]
            "nn_disponible": bool,
            "filtro_prestador": int | None,
        }
    """
    config = {"nn_disponible": nn_disponible}

    with st.sidebar.expander("Configuración de Predicción", expanded=True):

        # --- Métrica ---
        metric_label = st.radio(
            "Métrica a predecir",
            ["Importe total", "Precio unitario", "Cantidad"],
            help=(
                "• **Importe total**: plata total facturada por mes\n"
                "• **Precio unitario**: importe / cantidad\n"
                "• **Cantidad**: número de prestaciones"
            ),
        )
        metric_map = {
            "Importe total": "importe",
            "Precio unitario": "precio",
            "Cantidad": "cantidad",
        }
        config["metric"] = metric_map[metric_label]

        st.divider()

        # --- Modelos a comparar ---
        st.caption("**Modelos a aplicar**")
        usar_lgb = st.checkbox("LightGBM (recomendado)", value=True,
                                help="Gradient boosting. Más preciso para tabular.")
        usar_pablo = st.checkbox("Red Neuronal", value=nn_disponible,
                                  disabled=not nn_disponible,
                                  help=("Red neuronal feed-forward, corregida sin data leakage."
                                        if nn_disponible else
                                        "No disponible en esta instalación (faltan archivos "
                                        "del modelo o tensorflow). Ver aviso arriba."))

        config["models"] = []
        if usar_lgb:
            config["models"].append("lightgbm")
        if usar_pablo and nn_disponible:
            config["models"].append("pablo_corregido")

        if not config["models"]:
            st.warning("Seleccioná al menos un modelo")

    # --- Filtro de prestador (opcional) ---
    with st.sidebar.expander("Filtros (opcional)", expanded=False):
        if prestadores_disponibles:
            opts = ["(Todos)"] + [f"{pid} - {desc}" for pid, desc in prestadores_disponibles]
            choice = st.selectbox("Prestador específico", opts)
            if choice == "(Todos)":
                config["filtro_prestador"] = None
            else:
                config["filtro_prestador"] = int(choice.split(" - ")[0])
        else:
            config["filtro_prestador"] = None

    return config
