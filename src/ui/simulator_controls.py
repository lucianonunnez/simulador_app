"""
Controles del simulador — renderizados inline en el cuerpo principal.

- Fila 1: Prestador | Tipo de Aumento (horizontal)
- Fila 2: Multiselect de meses reales del dataset
- Expander: Inputs de % según el modo elegido
"""

from __future__ import annotations

import pandas as pd
import streamlit as st


_MESES_ORDEN = {
    "01": (1, "Enero"),   "02": (2, "Febrero"),  "03": (3, "Marzo"),
    "04": (4, "Abril"),   "05": (5, "Mayo"),      "06": (6, "Junio"),
    "07": (7, "Julio"),   "08": (8, "Agosto"),    "09": (9, "Septiembre"),
    "10": (10, "Octubre"),"11": (11, "Noviembre"),"12": (12, "Diciembre"),
}


def _parse_meses(df_merged: pd.DataFrame) -> dict[str, str]:
    if "Mes" not in df_merged.columns:
        return {}
    raw = df_merged["Mes"].dropna().unique()
    resultado = {}
    for val in raw:
        val = str(val).strip()
        partes = val.split("-")
        if len(partes) == 2:
            mm, yyyy = partes[0], partes[1]
            info  = _MESES_ORDEN.get(mm, (99, mm))
            label = f"{info[1]} {yyyy}"
            resultado[label] = (info[0], yyyy, val)
    resultado_ordenado = dict(sorted(resultado.items(), key=lambda x: (x[1][1], x[1][0])))
    return {k: v[2] for k, v in resultado_ordenado.items()}


def render_simulator_controls(df_merged: pd.DataFrame) -> dict:
    config = {}

    # ── Fila 1: Prestador + Tipo de Aumento ──
    col_prest, col_modo = st.columns([4, 4])

    with col_prest:
        prestadores = (
            df_merged[["Prestador ID", "Prestador Desc"]]
            .drop_duplicates().sort_values("Prestador Desc")
        )
        prestadores["label"] = prestadores["Prestador ID"].astype(str) + " - " + prestadores["Prestador Desc"]
        options  = ["TODOS"] + prestadores["label"].tolist()
        selected = st.selectbox("Prestador", options, key="sim_prest")

    with col_modo:
        mode_label = st.radio(
            "Tipo de Aumento",
            ["Plano", "Por Nomenclador", "Por Prestación"],
            horizontal=True, key="sim_mode",
        )

    config["prestador_id"] = None if selected == "TODOS" else int(selected.split(" - ")[0])
    config["mode"] = {"Plano": "plano", "Por Nomenclador": "por_nomenclador",
                      "Por Prestación": "por_prestacion"}[mode_label]

    # ── Fila 2: Meses ──
    meses_dict = _parse_meses(df_merged)
    if meses_dict:
        labels       = list(meses_dict.keys())
        seleccionados = st.multiselect(
            "Meses a analizar", options=labels, default=labels,
            key="sim_meses", help="Seleccioná uno, varios o todos los meses del dataset",
        )
        config["meses_raw"] = (
            [meses_dict[l] for l in seleccionados] if seleccionados else list(meses_dict.values())
        )
    else:
        st.info("El dataset no tiene columna 'Mes' — se usan todos los datos.")
        config["meses_raw"] = []

    # ── Scope para inputs ──
    df_scope = df_merged if config["prestador_id"] is None \
               else df_merged[df_merged["Prestador ID"] == config["prestador_id"]]

    config["flat_pct"]         = 0.0
    config["nomenclador_pcts"] = {}
    config["prestacion_pcts"]  = {}

    # ── Expander: Definir Aumentos ──
    with st.expander("Definir Aumentos", expanded=True):

        # ------------------------------------------------------------------ PLANO
        if config["mode"] == "plano":
            config["flat_pct"] = st.number_input(
                "Aumento Global (%)", min_value=-100.0, max_value=500.0,
                value=15.0, step=0.5, key="sim_flat_pct",
            )

        # -------------------------------------------------------- POR NOMENCLADOR
        elif config["mode"] == "por_nomenclador":
            base = st.number_input(
                "Aumento Base (%)", min_value=-100.0, max_value=500.0,
                value=15.0, step=0.5, key="sim_nom_base",
            )
            noms   = sorted(df_scope["Nomenclador"].dropna().unique())
            n_cols = min(len(noms), 4)
            cols   = st.columns(n_cols)
            for i, nom in enumerate(noms):
                with cols[i % n_cols]:
                    # Label visible, sin botones +/-
                    st.markdown(
                        f"<div style='font-size:12px; color:#212529; font-weight:500; "
                        f"margin-bottom:2px;'>{str(nom)[:28]}</div>",
                        unsafe_allow_html=True,
                    )
                    pct = st.number_input(
                        label=str(nom),
                        min_value=-100.0, max_value=500.0,
                        value=base, step=0.5,
                        key=f"nom_{nom}",
                        label_visibility="collapsed",
                    )
                    config["nomenclador_pcts"][nom] = pct

        # -------------------------------------------------------- POR PRESTACIÓN
        elif config["mode"] == "por_prestacion":
            # Aumento base
            base = st.number_input(
                "Aumento Base (%)", min_value=-100.0, max_value=500.0,
                value=15.0, step=0.5, key="sim_prest_base",
            )

            # Selectbox de prestaciones (con búsqueda integrada)
            prests_all = (
                df_scope[["Prestacion ID", "Prestacion Desc"]]
                .drop_duplicates()
                .sort_values("Prestacion Desc")
            )
            prests_all["label"] = (
                prests_all["Prestacion ID"].astype(str) + " — " + prests_all["Prestacion Desc"]
            )

            seleccionadas = st.multiselect(
                "Prestaciones a ajustar",
                options=prests_all["label"].tolist(),
                default=[],
                placeholder="Escribí para buscar o seleccioná prestaciones...",
                key="sim_prest_multi",
                help="Solo las prestaciones seleccionadas aquí recibirán un % diferente al base",
            )

            st.caption(
                f"Las prestaciones **no seleccionadas** usarán el aumento base de {base:.1f}%. "
                "Seleccioná solo las que querés ajustar individualmente."
            )

            # Primero aplicar base a todas
            for _, row in prests_all.iterrows():
                pid = int(row["Prestacion ID"]) if pd.notna(row["Prestacion ID"]) else None
                if pid is not None:
                    config["prestacion_pcts"][pid] = base

            # Luego override para las seleccionadas
            if seleccionadas:
                st.markdown("---")
                st.caption("Ajustá el % para cada prestación seleccionada:")
                cols = st.columns(3)
                for idx, label in enumerate(seleccionadas):
                    pid_str = label.split(" — ")[0]
                    desc    = label.split(" — ", 1)[1] if " — " in label else label
                    try:
                        pid = int(pid_str)
                    except ValueError:
                        continue
                    with cols[idx % 3]:
                        # Nombre visible encima del input
                        st.markdown(
                            f"<div style='font-size:12px; color:#212529; font-weight:500; "
                            f"margin-bottom:2px; line-height:1.3;'>{desc[:35]}</div>",
                            unsafe_allow_html=True,
                        )
                        pct = st.number_input(
                            label=desc,
                            min_value=-100.0, max_value=500.0,
                            value=base, step=0.5,
                            key=f"prest_{pid}",
                            label_visibility="collapsed",
                        )
                        config["prestacion_pcts"][pid] = pct

    return config