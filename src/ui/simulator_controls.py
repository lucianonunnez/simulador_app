"""
Controles del simulador — renderizados inline en el cuerpo principal.

- Fila 1: Prestador | Tipo de Aumento (horizontal)
- Fila 2: Multiselect de meses reales del dataset
- Expander: Inputs de % según el modo elegido
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui.formatters import format_currency_full


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


def _render_por_prestacion(df_scope: pd.DataFrame, config: dict) -> None:
    """
    Interfaz de aumento MIXTO por prestación.

    Replica el proceso real de negociación: un prestador con N prestaciones puede
    pedir un **%** en algunas, proponer un **monto $** en otras, y dejar el resto
    en un aumento **plano** (definido por nosotros). La idea de la revisión:
    "selecciono prestación A, le cargo % o $ propuesto, y veo cómo se modifica;
    luego la B, y así".

    Llena en `config`:
      - flat_pct          → el plano base para el "resto" (no ajustadas).
      - prestacion_pcts    → {pid: %}  para las ajustadas por porcentaje.
      - prestacion_valores → {pid: $}  para las ajustadas por monto absoluto.
    """
    base = st.number_input(
        "Aumento plano para el resto (%)",
        min_value=-100.0, max_value=500.0, value=15.0, step=0.5,
        key="sim_prest_base",
        help="Lo reciben todas las prestaciones que NO ajustes individualmente abajo.",
    )
    config["flat_pct"] = base

    # Catálogo de prestaciones del scope con su valor actual representativo.
    prests_all = (
        df_scope.groupby("Prestacion ID", dropna=True)
        .agg(**{
            "Prestacion Desc": ("Prestacion Desc", "first"),
            "Valor actual": ("Valor Convenido a HOY", "mean"),
        })
        .reset_index()
        .sort_values("Prestacion Desc")
    )
    prests_all = prests_all[prests_all["Prestacion ID"].notna()]
    prests_all["label"] = (
        prests_all["Prestacion ID"].astype("Int64").astype(str)
        + " — " + prests_all["Prestacion Desc"].astype(str)
    )
    valor_por_pid = dict(zip(prests_all["Prestacion ID"].astype("Int64"),
                            prests_all["Valor actual"]))

    seleccionadas = st.multiselect(
        "Prestaciones a ajustar individualmente",
        options=prests_all["label"].tolist(),
        default=[],
        placeholder="Escribí para buscar y seleccionar prestaciones...",
        key="sim_prest_multi",
        help="Cada prestación elegida puede recibir un % o un monto $ propio. "
             "Las no elegidas usan el plano base de arriba.",
    )

    st.caption(
        f"Las prestaciones **no seleccionadas** usan el plano base de **{base:.1f}%**. "
        "Para cada seleccionada: elegí **Tipo** (% o $) y cargá el **Valor**."
    )

    if not seleccionadas:
        return

    # Tabla editable: una fila por prestación seleccionada. Tipo (% o $) + Valor.
    filas = []
    for label in seleccionadas:
        try:
            pid = int(label.split(" — ")[0])
        except (ValueError, IndexError):
            continue
        desc = label.split(" — ", 1)[1] if " — " in label else label
        filas.append({
            "Prestación": desc,
            "Valor actual": float(valor_por_pid.get(pid, 0.0) or 0.0),
            "Tipo": "%",
            "Valor": round(base, 2),
            "_pid": pid,
        })
    if not filas:
        return

    editor_df = pd.DataFrame(filas)
    edited = st.data_editor(
        editor_df.drop(columns=["_pid"]),
        key="sim_prest_editor",
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "Prestación": st.column_config.TextColumn("Prestación", disabled=True),
            "Valor actual": st.column_config.NumberColumn(
                "Valor actual", disabled=True, format="$ %.2f",
            ),
            "Tipo": st.column_config.SelectboxColumn(
                "Tipo", options=["%", "$"], required=True,
                help="% = aumento porcentual sobre el valor actual · "
                     "$ = monto propuesto (valor ofrecido absoluto)",
            ),
            "Valor": st.column_config.NumberColumn(
                "Valor", help="El % de aumento o el monto $ propuesto, según el Tipo.",
            ),
        },
    )

    # Volcar lo editado a config y armar la vista previa de "cómo queda".
    preview = []
    for fila, (_, row) in zip(filas, edited.iterrows()):
        pid = fila["_pid"]
        actual = fila["Valor actual"]
        tipo = row["Tipo"]
        valor = row["Valor"]
        if valor is None or pd.isna(valor):
            continue
        if tipo == "$":
            ofrecido = float(valor)
            config["prestacion_valores"][pid] = ofrecido
        else:  # "%"
            ofrecido = actual * (1 + float(valor) / 100)
            config["prestacion_pcts"][pid] = float(valor)
        var = (ofrecido / actual - 1) * 100 if actual else 0.0
        preview.append({
            "Prestación": fila["Prestación"],
            "Valor actual": format_currency_full(actual),
            "Tipo": tipo,
            "Valor ofrecido": format_currency_full(ofrecido),
            "Variación": f"{var:+.2f}%",
        })

    if preview:
        st.caption("Así queda cada prestación ajustada:")
        st.dataframe(pd.DataFrame(preview), use_container_width=True, hide_index=True)


def render_simulator_controls(
    df_merged: pd.DataFrame, prestadores: list | None = None
) -> dict:
    """
    Controles del simulador.

    Args:
        df_merged: datos (posiblemente ya filtrados por prestador).
        prestadores: catálogo completo [(id, desc), ...] para el selector.
            Cuando los datos vienen filtrados por prestador (push-down a
            DuckDB), las opciones deben salir del catálogo y no de df_merged
            (que solo contiene el prestador elegido). None = derivar de
            df_merged (modo upload, comportamiento histórico).
    """
    config = {}

    # ── Fila 1: Prestador + Tipo de Aumento ──
    col_prest, col_modo = st.columns([4, 4])

    with col_prest:
        if prestadores:
            labels = [f"{int(pid)} - {desc}" for pid, desc in prestadores]
        else:
            prest_df = (
                df_merged[["Prestador ID", "Prestador Desc"]]
                .drop_duplicates().sort_values("Prestador Desc")
            )
            labels = (
                prest_df["Prestador ID"].astype(str) + " - " + prest_df["Prestador Desc"]
            ).tolist()
        options  = ["TODOS"] + labels
        selected = st.selectbox("Prestador", options, key="sim_prest")

    with col_modo:
        mode_label = st.radio(
            "Tipo de aumento",
            ["Igual para todo", "Por grupo de prácticas", "Detallado por prestación (% o $)"],
            horizontal=True, key="sim_mode",
        )

    config["prestador_id"] = None if selected == "TODOS" else int(selected.split(" - ")[0])
    config["mode"] = {
        "Igual para todo": "plano",
        "Por grupo de prácticas": "por_nomenclador",
        "Detallado por prestación (% o $)": "por_prestacion",
    }[mode_label]

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

    config["flat_pct"]           = 0.0
    config["flat_pct_propuesto"] = None
    config["pauta_pct"]          = None
    config["nomenclador_pcts"]   = {}
    config["prestacion_pcts"]    = {}
    config["prestacion_valores"] = {}
    config["excluidas"]          = []

    # ── Expander: Definir Aumentos ──
    with st.expander("Definir Aumentos", expanded=True):

        # ------------------------------------------------------------------ PLANO
        if config["mode"] == "plano":
            config["flat_pct"] = st.number_input(
                "Aumento Solicitado (%)", min_value=-100.0, max_value=500.0,
                value=15.0, step=0.5, key="sim_flat_pct",
                help="Escenario principal: el % de aumento pedido.",
            )

            c_prop, c_pauta = st.columns(2)
            with c_prop:
                usar_prop = st.checkbox(
                    "Comparar con escenario Propuesto",
                    key="sim_usar_prop",
                    help="Simula además un segundo % (la contraoferta) y "
                         "muestra ambos impactos lado a lado.",
                )
                if usar_prop:
                    config["flat_pct_propuesto"] = st.number_input(
                        "Aumento Propuesto (%)", min_value=-100.0, max_value=500.0,
                        value=10.0, step=0.5, key="sim_prop_pct",
                    )
            with c_pauta:
                usar_pauta = st.checkbox(
                    "Pauta de referencia (Extrapauta)",
                    key="sim_usar_pauta",
                    help="% autorizado de referencia. El Extrapauta mide cuánto "
                         "excede cada escenario a esa pauta.",
                )
                if usar_pauta:
                    config["pauta_pct"] = st.number_input(
                        "Pauta (%)", min_value=-100.0, max_value=500.0,
                        value=2.0, step=0.1, key="sim_pauta_pct",
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
            _render_por_prestacion(df_scope, config)

    # ── Expander: Exclusiones (No pauta) ──
    with st.expander("Exclusiones — No pauta", expanded=False):
        st.caption(
            "Prestaciones que quedan **fuera** de la simulación (el 'No pauta' "
            "del proceso de negociación: débitos, ajustes, módulos especiales, "
            "etc.). Las filas sin tarifa positiva se excluyen automáticamente."
        )
        prests_excl = (
            df_scope[["Prestacion ID", "Prestacion Desc"]]
            .drop_duplicates()
            .sort_values("Prestacion Desc")
        )
        prests_excl = prests_excl[prests_excl["Prestacion ID"].notna()]
        prests_excl["label"] = (
            prests_excl["Prestacion ID"].astype(str) + " — " + prests_excl["Prestacion Desc"].astype(str)
        )
        seleccion_excl = st.multiselect(
            "Prestaciones a excluir",
            options=prests_excl["label"].tolist(),
            default=[],
            placeholder="Escribí para buscar prestaciones a excluir...",
            key="sim_excluidas",
        )
        excluidas = []
        for label in seleccion_excl:
            try:
                excluidas.append(int(label.split(" — ")[0]))
            except ValueError:
                continue
        config["excluidas"] = excluidas

    return config