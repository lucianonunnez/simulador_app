"""
Renderizado de los 7 tabs del simulador.
v0.5.2 — diseño Swiss Medical
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

logger = logging.getLogger(__name__)

from ui.exporters import render_export_buttons
from ui.insights import insight_concentracion, insight_evolucion
from core.indec import fetch_inflation
from core.simulator import aggregate_top_n
from ui.formatters import format_currency, format_currency_full, format_int, format_quantity
from ui.theme import (
    COLOR_BLANCO,   # noqa: F401  (re-export histórico)
    COLOR_FONDO,
    COLOR_GRIS,
    COLOR_ROJO,
    COLOR_ROJO_DK,  # noqa: F401
    COLOR_TEXTO,
    layout_base as _layout_base,
)


# Meses en español
MESES_ES = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Ago",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic",
}

# Colores para barras dobles (ideal vs simulado)
COLOR_IDEAL   = "#E4002B"
COLOR_SIM     = "#343A40"


def _mes_label(dt) -> str:
    """Convierte datetime a etiqueta de mes en español."""
    try:
        return f"{MESES_ES.get(dt.month, dt.month)} {dt.year}"
    except Exception:
        return str(dt)


def render_tabs(
    df_merged: pd.DataFrame,
    df_simulated: pd.DataFrame,
    df_consumo_raw: pd.DataFrame,
    prestador_id: int | None,
) -> None:
    tabs = st.tabs([
        "Evolución",
        "Nomenclador",
        "Top Prestaciones",
        "Megacuenta",
        "Comparativa",
        "Datos",
        "Análisis",
    ])

    with tabs[0]: _tab_evolution(df_consumo_raw, df_simulated)
    with tabs[1]: _tab_nomenclador(df_simulated)
    with tabs[2]: _tab_top_prestaciones(df_simulated)
    with tabs[3]: _tab_megacuenta(df_simulated)
    with tabs[4]: _tab_comparativa(df_merged, prestador_id)
    with tabs[5]: _tab_datos(df_simulated)
    with tabs[6]: _tab_analisis(df_simulated)


# ----------------------------------------------------------------------------
# TAB 0: EVOLUCIÓN TEMPORAL
# ----------------------------------------------------------------------------
def _tabla_historico_pauta(df_time: pd.DataFrame, tick_texts: list[str]) -> None:
    """
    Tabla horizontal (meses en columnas) con dos filas:
      1) % de inflación del INDEC (la "pauta" publicada) — se precarga desde la
         API del INDEC en los meses donde hay dato publicado.
      2) % de aumento otorgado en cada mes — histórico que todavía NO tenemos
         como dato; queda el lugar RESERVADO (—) para cargarlo más adelante.

    Es el "histórico de pauta": permite contrastar lo que dio el INDEC contra
    lo que efectivamente se otorgó, mes a mes.
    """
    meses_periodo = df_time["Mes"].astype(str).tolist()   # 'MM-YYYY'

    # Inflación INDEC por mes (donde haya dato publicado).
    infl_map: dict[str, float] = {}
    try:
        infl = fetch_inflation(months=24)
        if not infl.empty:
            tmp = infl.copy()
            tmp["k"] = tmp["Mes"].dt.strftime("%m-%Y")
            infl_map = dict(zip(tmp["k"], tmp["Inflacion"]))
    except Exception:
        logger.exception("No se pudo obtener inflación INDEC para la tabla histórica")

    fila_indec = [
        f"{infl_map[m]:.1f}%" if m in infl_map else "—" for m in meses_periodo
    ]
    fila_aumento = ["—"] * len(meses_periodo)   # reservado: aún sin histórico

    tabla = pd.DataFrame(
        [fila_indec, fila_aumento],
        index=["Inflación INDEC (%)", "Aumento otorgado (%)"],
        columns=tick_texts,
    )
    st.markdown("""
    <div style="background:#FFF0F3; border-left:3px solid #E4002B;
                padding:8px 14px; border-radius:6px; margin:4px 0 6px 0;
                font-weight:600; color:#212529; font-size:13px;">
        Histórico de pauta — Inflación INDEC vs. aumento otorgado
    </div>
    """, unsafe_allow_html=True)
    st.dataframe(tabla, use_container_width=True)
    render_export_buttons(
        tabla,
        filename="historico_pauta",
        title="Histórico de pauta — Inflación INDEC vs. aumento otorgado",
        key="sim_historico_pauta",
        include_index=True,
    )
    st.caption(
        "Pauta del INDEC (IPC mensual) precargada donde hay dato publicado. "
        "La fila **Aumento otorgado** queda reservada: se completará cuando "
        "tengamos el histórico de lo otorgado mes a mes."
    )
    st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)


def _tab_evolution(df_consumo: pd.DataFrame, df_filtered: pd.DataFrame) -> None:
    st.subheader("Evolución Temporal del Consumo")

    if "Mes" not in df_filtered.columns:
        st.info("El dataset no tiene columna 'Mes'.")
        return

    df_time = df_filtered.groupby("Mes")[["Cantidad CM", "Importe CM"]].sum().reset_index()
    df_time["mes_dt"] = pd.to_datetime(df_time["Mes"], format="%m-%Y", errors="coerce")
    if df_time["mes_dt"].isna().all():
        df_time["mes_dt"] = pd.to_datetime(df_time["Mes"], errors="coerce")
    df_time = df_time.sort_values("mes_dt")

    tick_vals  = df_time["mes_dt"].tolist()
    tick_texts = [_mes_label(d) for d in tick_vals]

    # Tabla histórica de pauta (inflación INDEC vs aumento otorgado) por mes.
    _tabla_historico_pauta(df_time, tick_texts)

    def _line_fig(col_name: str, title: str, fmt) -> tuple[go.Figure, str | None]:
        """Gráfico de línea + insight: anillo sutil sobre el pico y una línea
        de texto que dice qué mirar."""
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_time["mes_dt"], y=df_time[col_name],
            mode="lines+markers",
            line=dict(color=COLOR_ROJO, width=2),
            marker=dict(size=7, color=COLOR_ROJO),
            name=col_name,
        ))

        texto = None
        res = insight_evolucion(tick_texts, df_time[col_name].tolist(), fmt)
        if res is not None:
            i_pico, texto = res
            fig.add_trace(go.Scatter(
                x=[df_time["mes_dt"].iloc[i_pico]],
                y=[df_time[col_name].iloc[i_pico]],
                mode="markers",
                marker=dict(size=18, color="rgba(228,0,43,0.12)",
                            line=dict(color=COLOR_ROJO, width=2)),
                showlegend=False, hoverinfo="skip",
            ))

        layout = _layout_base(title=title)
        layout["xaxis"].update(tickvals=tick_vals, ticktext=tick_texts, title=dict(text="Mes"))
        layout["yaxis"].update(title=dict(text=col_name))
        fig.update_layout(**layout)
        return fig, texto

    c1, c2 = st.columns(2)
    with c1:
        fig, texto = _line_fig("Cantidad CM", "Cantidad CM por Mes", format_quantity)
        st.plotly_chart(fig, use_container_width=True)
        if texto:
            st.caption(texto)
    with c2:
        fig, texto = _line_fig("Importe CM", "Costo CM por Mes", format_currency)
        st.plotly_chart(fig, use_container_width=True)
        if texto:
            st.caption(texto)

    # Pronóstico
    if len(df_time) >= 2:
        st.caption("Proyección lineal a 6 meses (regresión simple, línea punteada)")
        x = np.arange(len(df_time))
        future_months = pd.date_range(
            start=df_time["mes_dt"].iloc[-1] + pd.offsets.MonthBegin(),
            periods=6, freq="MS",
        )
        future_labels = [_mes_label(d) for d in future_months]

        c1, c2 = st.columns(2)
        for col, col_name in zip([c1, c2], ["Cantidad CM", "Importe CM"]):
            with col:
                coeff = np.polyfit(x, df_time[col_name].values, 1)
                x_future  = np.arange(len(x), len(x) + 6)
                vals_fut   = coeff[0] * x_future + coeff[1]

                all_ticks  = tick_vals + list(future_months)
                all_labels = tick_texts + future_labels

                fig = go.Figure()
                # Histórico
                fig.add_trace(go.Scatter(
                    x=df_time["mes_dt"], y=df_time[col_name],
                    mode="lines+markers",
                    line=dict(color=COLOR_ROJO, width=2),
                    marker=dict(size=7, color=COLOR_ROJO),
                    name="Histórico",
                ))
                # Pronóstico
                fig.add_trace(go.Scatter(
                    x=future_months, y=vals_fut,
                    mode="lines+markers",
                    line=dict(color=COLOR_ROJO, width=2, dash="dot"),
                    marker=dict(size=7, color=COLOR_ROJO, symbol="circle-open"),
                    name="Pronóstico",
                ))
                layout = _layout_base(title=f"{col_name} + Pronóstico")
                layout["xaxis"].update(tickvals=all_ticks, ticktext=all_labels, title=dict(text="Mes"))
                layout["yaxis"].update(title=dict(text=col_name))
                fig.update_layout(**layout)
                st.plotly_chart(fig, use_container_width=True)

    # Inflación INDEC
    with st.expander("Contexto macro: Inflación INDEC (opcional)", expanded=False):
        st.caption("Referencia de inflación mensual (IPC Nacional del INDEC).")
        df_infl = fetch_inflation(months=12)
        if not df_infl.empty:
            fig_inf = px.line(
                df_infl.sort_values("Mes"), x="Mes", y="Inflacion",
                title="Variación mensual IPC (%)", markers=True,
            )
            fig_inf.update_traces(line=dict(color=COLOR_ROJO, width=2))
            fig_inf.update_layout(**_layout_base(title="Variación mensual IPC (%)", height=350))
            st.plotly_chart(fig_inf, use_container_width=True)
        else:
            st.info("No se pudo obtener datos del INDEC.")
            infl_file = st.file_uploader(
                "Archivo opcional (csv/xlsx) con columnas 'Mes' e 'Inflacion'",
                type=["csv", "xlsx"], key="indec_manual",
            )
            if infl_file:
                try:
                    infl = pd.read_csv(infl_file) if infl_file.name.lower().endswith(".csv") \
                           else pd.read_excel(infl_file, engine="openpyxl")
                    if "Mes" in infl.columns and "Inflacion" in infl.columns:
                        fig = px.line(infl, x="Mes", y="Inflacion", markers=True)
                        fig.update_traces(line=dict(color=COLOR_ROJO))
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.error("El archivo debe tener columnas 'Mes' e 'Inflacion'")
                except Exception:
                    logger.exception("Error leyendo el archivo de inflación subido")
                    st.error("No se pudo leer el archivo. Verificá el formato (csv/xlsx).")


# ----------------------------------------------------------------------------
# TAB 1: POR NOMENCLADOR
# ----------------------------------------------------------------------------
# Definiciones de Ideal vs Simulado (se reutilizan en hovers y en la ayuda).
_HOVER_IDEAL = (
    "<b>%{x}</b><br>Consumo <b>Ideal</b>: %{y:$,.0f}<br>"
    "<i>Cantidad CM × Valor actual (vigente)</i><extra></extra>"
)
_HOVER_SIM = (
    "<b>%{x}</b><br>Consumo <b>Simulado</b>: %{y:$,.0f}<br>"
    "<i>Cantidad CM × Valor ofrecido (con el aumento)</i><extra></extra>"
)


def _ayuda_ideal_vs_simulado() -> None:
    """Explica qué es cada serie y de dónde sale (la leyenda de Plotly no admite
    tooltips, así que la referencia 'de dónde salió' va en este bloque)."""
    with st.expander("ℹ️ ¿Qué son «Ideal» y «Simulado»? (de dónde sale cada uno)"):
        st.markdown(
            "- **Consumo Ideal** — el consumo valorizado al **valor actual** "
            "(el vigente hoy, sin aumento).\n"
            "  Sale de: **Cantidad CM × Valor Convenido a HOY**.\n"
            "- **Consumo Simulado** — el mismo consumo valorizado al **valor "
            "ofrecido**, es decir tras aplicar el aumento que cargaste arriba.\n"
            "  Sale de: **Cantidad CM × Valor Ofrecido** "
            "(donde *Valor Ofrecido = Valor actual × (1 + aumento%)* o el monto $ "
            "propuesto).\n\n"
            "La **diferencia** entre ambos es el **impacto** del aumento."
        )


def _tab_nomenclador(df: pd.DataFrame) -> None:
    st.subheader("Análisis por Nomenclador")

    grouping = st.radio("Agrupar por", ["Nomenclador", "Tipo Clase CM"], horizontal=True)
    _ayuda_ideal_vs_simulado()
    df_agg = aggregate_top_n(df, grouping, ["Consumo Ideal", "Consumo Simulado"], top_n=25)

    c1, c2 = st.columns(2)

    with c1:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_agg[grouping], y=df_agg["Consumo Ideal"],
                             name="Ideal", marker_color=COLOR_ROJO,
                             hovertemplate=_HOVER_IDEAL))
        fig.add_trace(go.Bar(x=df_agg[grouping], y=df_agg["Consumo Simulado"],
                             name="Simulado", marker_color=COLOR_GRIS,
                             hovertemplate=_HOVER_SIM))
        layout = _layout_base(title=f"Consumo por {grouping}")
        layout["xaxis"]["title"] = dict(text=grouping)
        layout["yaxis"]["title"] = dict(text="Consumo ($)")
        fig.update_layout(**layout, barmode="group")
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        fig = px.pie(
            df_agg, values="Consumo Ideal", names=grouping,
            title=f"Composición por {grouping}", hole=0.35,
        )
        # Mostrar % solo para segmentos > 5%, hover para el resto
        fig.update_traces(
            texttemplate="%{percent:.1%}",
            textinfo="percent",
            textposition="inside",
            insidetextorientation="radial",
            hovertemplate="<b>%{label}</b><br>%{value:$,.0f}<br>%{percent}<extra></extra>",
        )
        # Ocultar etiquetas de segmentos pequeños via JS no es posible en Plotly directo,
        # pero podemos formatear: mostrar vacío si < 5%
        total_val = df_agg["Consumo Ideal"].sum()
        fig.update_traces(
            text=[f"{v/total_val*100:.1f}%" if total_val > 0 and v/total_val >= 0.05 else ""
                  for v in df_agg["Consumo Ideal"]],
            textinfo="text",
        )
        fig.update_layout(
            title=dict(text=f"Composición por {grouping}",
                       font=dict(color=COLOR_TEXTO, size=15, weight="bold")),
            paper_bgcolor=COLOR_FONDO,
            legend=dict(font=dict(color=COLOR_TEXTO)),
            height=450,
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Se etiquetan los segmentos ≥ 5%; pasá el mouse para ver el resto.")

    df_sin_otros = df_agg[df_agg[grouping].astype(str) != "Otros"]
    texto = insight_concentracion(
        df_sin_otros[grouping].tolist(), df_sin_otros["Consumo Ideal"].tolist(),
        top_n=3, sufijo="del consumo",
    )
    if texto:
        st.caption(texto)

    df_display = df_agg.copy()
    df_display["Consumo Ideal"]    = df_display["Consumo Ideal"].apply(format_currency)
    df_display["Consumo Simulado"] = df_display["Consumo Simulado"].apply(format_currency)
    st.dataframe(df_display, use_container_width=True, hide_index=True)
    render_export_buttons(
        df_display,
        filename=f"consumo_por_{grouping.lower().replace(' ', '_')}",
        title=f"Consumo por {grouping}",
        key="sim_nomenclador",
    )


# ----------------------------------------------------------------------------
# TAB 2: TOP 20 PRESTACIONES
# ----------------------------------------------------------------------------
def _tab_top_prestaciones(df: pd.DataFrame) -> None:
    st.subheader("Top 20 Prestaciones por Consumo")

    df_prest = df.groupby("Prestacion Desc").agg({
        "Consumo Ideal":    "sum",
        "Consumo Simulado": "sum",
        "Cantidad CM":      "sum",
        "Valor Ofrecido":   "mean",
    }).reset_index()

    top20 = df_prest.nlargest(20, "Consumo Ideal").sort_values("Consumo Ideal", ascending=True)

    fig = go.Figure()
    fig.add_trace(go.Bar(y=top20["Prestacion Desc"], x=top20["Consumo Ideal"],
                         name="Ideal", marker_color=COLOR_ROJO, orientation="h"))
    fig.add_trace(go.Bar(y=top20["Prestacion Desc"], x=top20["Consumo Simulado"],
                         name="Simulado", marker_color=COLOR_GRIS, orientation="h"))
    layout = _layout_base(title="Top 20 Prestaciones", height=620)
    layout["xaxis"]["title"] = dict(text="Consumo ($)")
    layout["yaxis"]["title"] = dict(text="Prestación")
    layout["hovermode"] = "y unified"
    fig.update_layout(**layout, barmode="group")
    st.plotly_chart(fig, use_container_width=True)

    texto = insight_concentracion(
        df_prest["Prestacion Desc"].tolist(),
        df_prest["Consumo Ideal"].tolist(),
        top_n=5, sufijo="del consumo total",
    )
    if texto:
        st.caption(texto)

    df_display = top20.sort_values("Consumo Ideal", ascending=False).copy()
    df_display["Consumo Ideal"]    = df_display["Consumo Ideal"].apply(format_currency)
    df_display["Consumo Simulado"] = df_display["Consumo Simulado"].apply(format_currency)
    df_display["Cantidad CM"]      = df_display["Cantidad CM"].apply(format_quantity)
    df_display["Valor Ofrecido"]   = df_display["Valor Ofrecido"].apply(format_currency_full)
    st.dataframe(df_display, use_container_width=True, hide_index=True)
    render_export_buttons(
        df_display,
        filename="top_prestaciones",
        title="Top 20 Prestaciones por Consumo",
        key="sim_top_prestaciones",
    )


# ----------------------------------------------------------------------------
# TAB 3: POR MEGACUENTA
# ----------------------------------------------------------------------------
def _detalle_otros(df: pd.DataFrame, group_col: str, value_col: str, top_n: int = 25) -> str:
    """Texto con las categorías que aggregate_top_n agrupó bajo 'Otros'.

    Se usa para el hover del gráfico circular: parado sobre 'Otros' aparece
    qué representa (cuántas categorías agrupa y cuáles), en vez de un opaco
    'Otros'."""
    full = (
        df.groupby(group_col, dropna=False)[value_col]
        .sum().sort_values(ascending=False)
    )
    if len(full) <= top_n:
        return ""
    tail = full.iloc[top_n:]
    nombres = [str(n) for n in tail.index]
    muestra = ", ".join(nombres[:10])
    extra = f" y {len(nombres) - 10} más" if len(nombres) > 10 else ""
    return f"Agrupa {len(nombres)} categorías: {muestra}{extra}"


def _tab_megacuenta(df: pd.DataFrame) -> None:
    st.subheader("Análisis por Megacuenta")

    if "Megacuenta" not in df.columns:
        st.info("El dataset no tiene columna 'Megacuenta'.")
        return

    # Selectbox en lugar de text input
    opciones = sorted(df["Megacuenta"].dropna().unique().astype(str).tolist())
    seleccion = st.selectbox(
        "Megacuenta",
        options=["— Todas —"] + opciones,
        key="mega_select",
    )

    df_mega = aggregate_top_n(df, "Megacuenta", ["Consumo Ideal", "Consumo Simulado"], top_n=25)

    if seleccion != "— Todas —":
        df_mega = df_mega[df_mega["Megacuenta"].astype(str) == seleccion]

    df_mega = df_mega.sort_values("Consumo Ideal", ascending=False)

    c1, c2 = st.columns(2)

    with c1:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_mega.head(15)["Megacuenta"],
                             y=df_mega.head(15)["Consumo Ideal"],
                             name="Ideal", marker_color=COLOR_ROJO))
        fig.add_trace(go.Bar(x=df_mega.head(15)["Megacuenta"],
                             y=df_mega.head(15)["Consumo Simulado"],
                             name="Simulado", marker_color=COLOR_GRIS))
        layout = _layout_base(title="Top Megacuentas")
        layout["xaxis"]["title"] = dict(text="Megacuenta")
        layout["yaxis"]["title"] = dict(text="Consumo ($)")
        fig.update_layout(**layout, barmode="group")
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        fig = px.pie(
            df_mega, values="Consumo Ideal", names="Megacuenta",
            title="Composición Megacuenta", hole=0.35,
        )
        total_mega = df_mega["Consumo Ideal"].sum()
        # Hover de 'Otros': qué megacuentas agrupa (se calcula sobre el df full,
        # antes del top-N). El resto de las porciones no llevan detalle.
        detalle_otros = _detalle_otros(df, "Megacuenta", "Consumo Ideal", top_n=25)
        customdata = [
            [f"<br>{detalle_otros}" if str(m) == "Otros" and detalle_otros else ""]
            for m in df_mega["Megacuenta"]
        ]
        fig.update_traces(
            text=[f"{v/total_mega*100:.1f}%" if total_mega > 0 and v/total_mega >= 0.05 else ""
                  for v in df_mega["Consumo Ideal"]],
            textinfo="text",
            textposition="inside",
            insidetextorientation="radial",
            customdata=customdata,
            hovertemplate="<b>%{label}</b><br>%{value:$,.0f} · %{percent}"
                          "%{customdata[0]}<extra></extra>",
        )
        fig.update_layout(
            title=dict(text="Composición Megacuenta",
                       font=dict(color=COLOR_TEXTO, size=15, weight="bold")),
            paper_bgcolor=COLOR_FONDO,
            legend=dict(font=dict(color=COLOR_TEXTO)),
            height=450,
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Se etiquetan los segmentos ≥ 5%; pasá el mouse para ver el resto.")

    df_display = df_mega.copy()
    df_display["Consumo Ideal"]    = df_display["Consumo Ideal"].apply(format_currency)
    df_display["Consumo Simulado"] = df_display["Consumo Simulado"].apply(format_currency)
    st.dataframe(df_display, use_container_width=True, hide_index=True)
    render_export_buttons(
        df_display,
        filename="por_megacuenta",
        title="Análisis por Megacuenta",
        key="sim_megacuenta",
    )


# ----------------------------------------------------------------------------
# TAB 4: COMPARATIVA MULTI-PRESTADOR
# ----------------------------------------------------------------------------
def _tab_comparativa(df_merged: pd.DataFrame, prestador_id: int | None) -> None:
    st.subheader("Comparativa de Valores (todos los prestadores)")
    st.caption("Este análisis no se filtra por el prestador seleccionado, para permitir comparar entre prestadores.")

    # Con el push-down, df_merged puede venir filtrado al prestador elegido.
    # La carga del dataset completo es opt-in (si fuera automática, este tab
    # la dispararía en cada rerun y anularía el beneficio del push-down).
    if prestador_id is not None:
        cargar_todos = st.checkbox(
            "Cargar todos los prestadores para comparar",
            value=False,
            key="comp_cargar_todos",
            help="Los datos están filtrados al prestador seleccionado. "
                 "Activá esta opción para traer el resto (queda cacheado).",
        )
        if cargar_todos:
            from core.data_loader import load_merged_completo

            with st.spinner("Cargando todos los prestadores..."):
                df_full = load_merged_completo()
            if df_full is not None:
                df_merged = df_full
        else:
            st.info(
                "Mostrando solo el prestador seleccionado. Activá la opción de "
                "arriba para comparar contra todos los prestadores."
            )

    if "Prestacion Desc" not in df_merged.columns:
        st.info("Falta columna 'Prestacion Desc'.")
        return

    prests_list = (
        df_merged[["Prestacion ID", "Prestacion Desc"]]
        .drop_duplicates()
        .sort_values("Prestacion Desc")
    )
    prests_list["label"] = (
        prests_list["Prestacion ID"].astype(str) + " - " + prests_list["Prestacion Desc"]
    )

    # Selectbox directo — sin text input separado
    choice = st.selectbox(
        "Seleccioná una prestación",
        options=prests_list["label"].tolist(),
        key="comp_select",
        placeholder="Escribí para buscar...",
    )

    if not choice:
        return

    pid = int(choice.split(" - ")[0])
    df_comp = df_merged[df_merged["Prestacion ID"] == pid].copy()

    if len(df_comp) == 0:
        st.info("Sin datos para esta prestación")
        return

    # ── Selección de prestadores a comparar ──
    # Dos modos: ver TODOS los prestadores cargados que ofrecen esta prestación,
    # o elegir SOLO algunos de ellos (p. ej. comparar contra prestadores de la
    # misma coordinación / similares).
    prest_disp = sorted(df_comp["Prestador Desc"].dropna().unique().astype(str).tolist())
    modo_comp = st.radio(
        "¿Qué prestadores comparar?",
        ["Todos los cargados", "Seleccionar algunos"],
        horizontal=True,
        key="comp_modo",
        help=f"Esta prestación la ofrecen {len(prest_disp)} prestador(es) "
             "de los cargados.",
    )
    if modo_comp == "Seleccionar algunos":
        prest_sel = st.multiselect(
            "Prestadores a comparar",
            options=prest_disp,
            default=prest_disp[:min(5, len(prest_disp))],
            key="comp_prestadores",
            placeholder="Seleccioná los prestadores a comparar...",
            help="Elegí los prestadores contra los que querés comparar.",
        )
        if not prest_sel:
            st.info("Seleccioná al menos un prestador para comparar.")
            return
        df_comp = df_comp[df_comp["Prestador Desc"].astype(str).isin(prest_sel)]

    df_group = df_comp.groupby("Prestador Desc").agg({
        "Valor Convenido a HOY": "mean",
        "Cantidad CM":           "sum",
        "Prestador ID":          "first",
    }).reset_index()

    df_group["Color"] = df_group["Prestador ID"].apply(
        lambda x: COLOR_ROJO if (prestador_id is None or x == prestador_id) else "#CCCCCC"
    )

    fig = px.scatter(
        df_group,
        x="Valor Convenido a HOY", y="Cantidad CM",
        color="Color", size="Cantidad CM",
        title=f"Valor vs Cantidad: {choice}",
        hover_name="Prestador Desc",
        color_discrete_map={COLOR_ROJO: COLOR_ROJO, "#CCCCCC": "#CCCCCC"},
    )
    layout = _layout_base(title=f"Valor vs Cantidad: {choice}", height=500)
    layout["xaxis"]["title"] = dict(text="Valor Promedio ($)")
    layout["yaxis"]["title"] = dict(text="Cantidad Total")
    layout["hovermode"] = "closest"
    fig.update_layout(**layout, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    st.write("**Detalle por Prestador:**")
    df_display = (
        df_group.drop(columns=["Color", "Prestador ID"])
        .sort_values("Valor Convenido a HOY", ascending=False)
        .copy()
    )
    df_display["Valor Convenido a HOY"] = df_display["Valor Convenido a HOY"].apply(format_currency_full)
    df_display["Cantidad CM"]           = df_display["Cantidad CM"].apply(format_quantity)
    st.dataframe(df_display, use_container_width=True, hide_index=True)
    render_export_buttons(
        df_display,
        filename="comparativa_prestadores",
        title=f"Comparativa de Valores — {choice}",
        key="sim_comparativa",
    )


# ----------------------------------------------------------------------------
# TAB 5: DATOS DETALLADOS
# ----------------------------------------------------------------------------

# Tope de filas a RENDERIZAR en pantalla. Con volumen real (cientos de miles
# de filas), serializar la tabla completa a Arrow en cada rerun tardaba
# segundos y dejaba colgados los elementos "fantasma" de la página anterior.
# La descarga CSV sigue incluyendo todo.
_MAX_FILAS_TABLA = 1_000


def _tab_datos(df: pd.DataFrame) -> None:
    st.subheader("Datos Detallados")

    cols_show = [
        "Prestador Desc", "Convenio Desc", "Nomenclador", "Prestacion Desc",
        "Cantidad CM", "Valor Convenido a HOY", "Valor Ofrecido",
        "Consumo Ideal", "Consumo Simulado", "% Aumento",
    ]
    cols_show = [c for c in cols_show if c in df.columns]

    # Aumento promedio — encabezado con fondo rosado via CSS inyectado
    st.markdown("""
    <div style="background:#FFF0F3; border-left:3px solid #E4002B;
                padding:10px 16px; border-radius:6px; margin-bottom:8px;
                font-weight:600; color:#212529;">
        Aumento promedio por prestación
    </div>
    """, unsafe_allow_html=True)

    avg = df.groupby("Prestacion Desc")["% Aumento"].mean().sort_values(ascending=False)
    st.dataframe(avg, use_container_width=True)
    avg_export = avg.round(2).reset_index()
    avg_export["% Aumento"] = avg_export["% Aumento"].apply(lambda x: f"{x:.2f}%")
    render_export_buttons(
        avg_export,
        filename="aumento_promedio_prestacion",
        title="Aumento promedio por prestación",
        key="sim_avg_aumento",
    )

    st.markdown("""
    <div style="background:#FFF0F3; border-left:3px solid #E4002B;
                padding:10px 16px; border-radius:6px; margin:16px 0 8px 0;
                font-weight:600; color:#212529;">
        Tabla completa
    </div>
    """, unsafe_allow_html=True)

    # Formatear y mostrar solo el tope de filas (el formateo .apply por celda
    # sobre cientos de miles de filas también costaba segundos por rerun).
    df_display = df[cols_show].head(_MAX_FILAS_TABLA).copy()
    for col, fn in [
        ("Cantidad CM",        format_quantity),
        ("Valor Convenido a HOY", format_currency_full),
        ("Valor Ofrecido",     format_currency_full),
        ("Consumo Ideal",      format_currency),
        ("Consumo Simulado",   format_currency),
    ]:
        if col in df_display.columns:
            df_display[col] = df_display[col].apply(fn)

    st.dataframe(df_display, use_container_width=True, hide_index=True)
    if len(df) > _MAX_FILAS_TABLA:
        st.caption(
            f"Mostrando las primeras {format_int(_MAX_FILAS_TABLA)} de {format_int(len(df))} filas. "
            "La descarga CSV incluye el detalle completo."
        )

    # CSV: detalle completo (sin truncar). PDF: la tabla mostrada (formateada y
    # acotada), que es lo razonable de imprimir.
    render_export_buttons(
        df_display,
        filename="simulacion",
        title="Datos Detallados de la Simulación",
        key="sim_datos",
        csv_df=df[cols_show],
    )


# ----------------------------------------------------------------------------
# TAB 6: ANÁLISIS Y CONCLUSIONES
# ----------------------------------------------------------------------------
def _tab_analisis(df: pd.DataFrame) -> None:
    st.subheader("Análisis y Conclusiones")

    total_ideal = df["Consumo Ideal"].sum()
    total_sim   = df["Consumo Simulado"].sum()
    dif         = total_sim - total_ideal
    pct         = (dif / total_ideal * 100) if total_ideal > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Registros",    format_int(len(df)))
    c2.metric("Prestadores",  format_int(df["Prestador ID"].nunique()))
    c3.metric("Nomencladores",format_int(df["Nomenclador"].nunique()))
    c4.metric("Prestaciones", format_int(df["Prestacion ID"].nunique()))

    st.divider()

    c1, c2 = st.columns(2)

    with c1:
        st.write("### Impacto Financiero")
        if pct > 0:
            st.success(f"Aumento proyectado: **{format_currency(dif)}** ({pct:+.2f}%)")
        elif pct < 0:
            st.warning(f"Reducción proyectada: **{format_currency(abs(dif))}** ({pct:.2f}%)")
        else:
            st.info("Sin cambio respecto del valor actual")

    with c2:
        st.write("### Top Categorías")
        top_nom = df.groupby("Nomenclador")["Consumo Ideal"].sum().nlargest(3)
        if len(top_nom) > 0:
            st.write("**Nomencladores top:** " + ", ".join(top_nom.index.astype(str).tolist()))
        top_prest = df.groupby("Prestacion Desc")["Consumo Ideal"].sum().nlargest(3)
        if len(top_prest) > 0:
            names = [p[:30] + "..." if len(p) > 30 else p for p in top_prest.index.astype(str)]
            st.write("**Prestaciones top:** " + ", ".join(names))