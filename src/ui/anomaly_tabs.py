"""
Cuatro tabs del Módulo 2 (Detección de Desvíos):
    1. Por Prestador  — multiselect + comparativa si hay varios
    2. Por Prestación — selectbox (sin text input)
    3. Por Grupo
    4. Ranking de Alertas
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from core.cachekeys import df_fingerprint
from core.anomaly import (
    build_alerts_ranking,
    build_time_series,
    detect_structural_anomalies,
    detect_temporal_anomalies,
)
from ui.exporters import render_export_buttons
from ui.formatters import format_currency, format_currency_full, format_quantity, safe_pct
from ui.insights import insight_anomalias


# ============================================================================
# WRAPPERS CACHEADOS
# ============================================================================
# Las funciones de core.anomaly son puras pero caras (groupby + rolling +
# apply). Streamlit ejecuta el cuerpo de TODOS los tabs en cada rerun, así que
# sin caché se recalculaban a cada interacción (incluso al solo cambiar de tab).
# Separar build_time_series (no depende del umbral) de la detección permite que
# mover un slider de umbral/ventana NO reconstruya la serie temporal.

@st.cache_data(show_spinner=False, hash_funcs={pd.DataFrame: df_fingerprint})
def _build_time_series_cached(df, group_cols, metric):
    return build_time_series(df, group_cols, metric)


@st.cache_data(show_spinner=False, hash_funcs={pd.DataFrame: df_fingerprint})
def _detect_temporal_cached(ts, group_cols, method, window, threshold):
    return detect_temporal_anomalies(
        ts, group_cols=group_cols, method=method, window=window, threshold=threshold
    )


@st.cache_data(show_spinner=False, max_entries=50,
               hash_funcs={pd.DataFrame: df_fingerprint})
def _detect_structural_cached(df, peer_group_cols, method, threshold, metric):
    return detect_structural_anomalies(
        df, peer_group_cols=peer_group_cols, method=method,
        threshold=threshold, metric=metric,
    )


@st.cache_data(show_spinner=False, hash_funcs={pd.DataFrame: df_fingerprint})
def _build_ranking_cached(ts_with_flags, entity_cols, last_month_only, top_n):
    return build_alerts_ranking(
        ts_with_flags, entity_cols=entity_cols,
        last_month_only=last_month_only, top_n=top_n,
    )


METRIC_LABEL = {
    "precio_unitario": "Precio Unitario",
    "importe_total":   "Importe Total",
    "cantidad":        "Cantidad",
}

# Meses en español para los gráficos
MESES_ES = {
    1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Ago",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic",
}


def render_tabs(df_consumo: pd.DataFrame, config: dict) -> None:
    tabs = st.tabs([
        "Por Prestador",
        "Por Prestación",
        "Por Grupo",
        "Ranking de Alertas",
    ])
    with tabs[0]: _tab_prestador(df_consumo, config)
    with tabs[1]: _tab_prestacion(df_consumo, config)
    with tabs[2]: _tab_grupo(df_consumo, config)
    with tabs[3]: _tab_ranking(df_consumo, config)


# ============================================================================
# TAB 1 — POR PRESTADOR
# ============================================================================
def _tab_prestador(df: pd.DataFrame, config: dict) -> None:
    st.subheader("Análisis por Prestador")

    prestadores = (
        df[["Prestador ID", "Prestador Desc"]]
        .drop_duplicates()
        .sort_values("Prestador Desc")
    )
    prestadores["label"] = (
        prestadores["Prestador ID"].astype(str) + " - " + prestadores["Prestador Desc"]
    )

    seleccionados = st.multiselect(
        "Seleccioná uno o varios prestadores",
        options=prestadores["label"].tolist(),
        default=[],
        placeholder="Escribí para buscar o seleccioná de la lista...",
        key="anomaly_prest_multi",
    )

    if not seleccionados:
        st.info("Seleccioná al menos un prestador para ver el análisis.")
        return

    prest_data = [
        {"id": int(s.split(" - ")[0]), "desc": s.split(" - ", 1)[1]}
        for s in seleccionados
    ]

    if len(prest_data) == 1:
        df_p = df[df["Prestador ID"] == prest_data[0]["id"]].copy()
        if len(df_p) == 0:
            st.info("Sin datos para este prestador")
            return
        _render_temporal_view(df_p, config, group_cols=["Prestador ID"], entity_name=prest_data[0]["desc"], view_key="prestador")
    else:
        _render_comparativa(df, config, prest_data)


def _render_comparativa(df: pd.DataFrame, config: dict, prest_data: list[dict]) -> None:
    metric_label = METRIC_LABEL[config["metric"]]
    st.caption(f"Comparativa de **{len(prest_data)} prestadores** · Métrica: **{metric_label}**")

    fig = go.Figure()
    colores = px.colors.qualitative.Set2
    resumen_rows = []

    for i, p in enumerate(prest_data):
        df_p = df[df["Prestador ID"] == p["id"]].copy()
        if len(df_p) == 0:
            continue
        ts = _build_time_series_cached(df_p, ["Prestador ID"], config["metric"])
        if len(ts) < 2:
            continue
        ts = _detect_temporal_cached(
            ts, ["Prestador ID"],
            config["temporal_method"], config["window"], config["threshold_temporal"],
        )
        color = colores[i % len(colores)]
        fig.add_trace(go.Scatter(
            x=ts["mes_dt"], y=ts["valor"],
            mode="lines+markers", name=p["desc"],
            line=dict(color=color, width=2), marker=dict(size=7),
        ))
        anom = ts[ts["is_anomaly_temporal"] == True]
        if len(anom) > 0:
            fig.add_trace(go.Scatter(
                x=anom["mes_dt"], y=anom["valor"], mode="markers",
                marker=dict(size=13, color=color, symbol="x", line=dict(width=2, color="black")),
                name=f"Anomalía — {p['desc'][:20]}",
            ))
        resumen_rows.append({
            "Prestador": p["desc"],
            f"Promedio {metric_label}": ts["valor"].mean(),
            f"Máximo {metric_label}":   ts["valor"].max(),
            f"Mínimo {metric_label}":   ts["valor"].min(),
            "Meses analizados":         len(ts),
            "Anomalías detectadas":     int(ts["is_anomaly_temporal"].sum()),
        })

    fig.update_layout(
        title=dict(text=f"Comparativa — {metric_label} por Prestador", font=dict(color="#212529", size=15, weight="bold")),
        xaxis_title="Mes", yaxis_title=metric_label,
        hovermode="x unified", height=520,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="#FFFFFF", paper_bgcolor="#F8F9FA",
    )
    st.plotly_chart(fig, use_container_width=True)

    if resumen_rows:
        st.write("### Resumen comparativo")
        df_res = pd.DataFrame(resumen_rows)
        fmt = format_currency_full if config["metric"] in ("precio_unitario", "importe_total") else format_quantity
        for col in [f"Promedio {metric_label}", f"Máximo {metric_label}", f"Mínimo {metric_label}"]:
            if col in df_res.columns:
                df_res[col] = df_res[col].apply(fmt)
        st.dataframe(df_res, use_container_width=True, hide_index=True)
        render_export_buttons(
            df_res,
            filename="comparativa_prestadores",
            title=f"Comparativa — {metric_label} por Prestador",
            key="anom_comparativa",
        )


# ============================================================================
# TAB 2 — POR PRESTACIÓN (selectbox, sin text input)
# ============================================================================
def _tab_prestacion(df: pd.DataFrame, config: dict) -> None:
    st.subheader("Análisis por Prestación")

    prests = (
        df[["Prestacion ID", "Prestacion Desc"]]
        .drop_duplicates()
        .sort_values("Prestacion Desc")
    )
    prests["label"] = prests["Prestacion ID"].astype(str) + " - " + prests["Prestacion Desc"]

    choice = st.selectbox(
        "Prestación",
        options=prests["label"].tolist(),
        key="anomaly_prest_select",
        placeholder="Escribí para buscar...",
    )

    if not choice:
        return

    prid  = choice.split(" - ")[0]
    prdesc = choice.split(" - ", 1)[1]
    df_pr = df[df["Prestacion ID"].astype(str) == prid].copy()

    if len(df_pr) == 0:
        st.info("Sin datos para esta prestación")
        return

    _render_temporal_view(df_pr, config, group_cols=["Prestacion ID"], entity_name=prdesc, view_key="prestacion")


# ============================================================================
# TAB 3 — POR GRUPO
# ============================================================================
def _tab_grupo(df: pd.DataFrame, config: dict) -> None:
    st.subheader("Análisis por Grupo")

    grouping = st.radio("Agrupar por", ["Nomenclador", "Tipo Clase CM"], horizontal=True)

    if grouping not in df.columns:
        st.info(f"La columna '{grouping}' no está en el dataset")
        return

    opts = sorted(df[grouping].dropna().unique().astype(str).tolist())
    if not opts:
        st.info("Sin datos en esta columna")
        return

    choice = st.selectbox(f"Seleccioná {grouping}", opts)
    df_g = df[df[grouping].astype(str) == choice].copy()

    if len(df_g) == 0:
        st.info("Sin datos para este grupo")
        return

    _render_temporal_view(df_g, config, group_cols=[grouping], entity_name=choice, view_key="grupo")


# ============================================================================
# TAB 4 — RANKING DE ALERTAS
# ============================================================================
def _tab_ranking(df: pd.DataFrame, config: dict) -> None:
    st.subheader("Ranking de Alertas")
    st.caption("Alertas ordenadas por severidad.")

    c1, c2 = st.columns(2)
    with c1:
        scope = st.radio("Alcance temporal", ["Último mes", "Todo el histórico"],
                         horizontal=True, key="ranking_scope")
    with c2:
        top_n = st.slider("Máximo de alertas", 10, 200, 50, 10, key="ranking_topn")

    level = st.radio("Detección a nivel:", ["Prestador", "Prestador × Prestación"],
                     horizontal=True, key="ranking_level")

    group_cols = (
        ["Prestador ID", "Prestador Desc"]
        if level == "Prestador"
        else ["Prestador ID", "Prestador Desc", "Prestacion ID", "Prestacion Desc"]
    )

    with st.spinner("Calculando alertas..."):
        ts = _build_time_series_cached(df, group_cols, config["metric"])
        if len(ts) == 0:
            st.info("No hay datos para analizar")
            return
        ts_with_flags = _detect_temporal_cached(
            ts, group_cols,
            config["temporal_method"], config["window"], config["threshold_temporal"],
        )
        ranking = _build_ranking_cached(
            ts_with_flags, group_cols,
            (scope == "Último mes"), top_n,
        )

    if len(ranking) == 0:
        st.success("No se detectaron alertas con los parámetros actuales")
        return

    st.metric("Alertas detectadas", len(ranking))
    display = ranking.copy()
    display["Mes"] = display["mes_dt"].dt.strftime("%m-%Y")

    fmt_fn = (format_currency_full if config["metric"] == "precio_unitario"
              else format_currency if config["metric"] == "importe_total"
              else format_quantity)
    display["Valor"] = display["valor"].apply(fmt_fn)
    if "media_movil" in display.columns:
        display["Esperado (media móvil)"] = display["media_movil"].apply(fmt_fn)
    display["Severidad"] = display["severidad_temporal"].apply(lambda x: f"{x:.2f}")

    show_cols = [c for c in group_cols if "Desc" in c] + ["Mes", "Valor"]
    if "Esperado (media móvil)" in display.columns:
        show_cols.append("Esperado (media móvil)")
    show_cols.append("Severidad")

    st.dataframe(display[show_cols], use_container_width=True, hide_index=True)
    render_export_buttons(
        display[show_cols],
        filename=f"alertas_{config['metric']}",
        title="Ranking de Alertas",
        key=f"anom_alertas_{config['metric']}",
    )


# ============================================================================
# VISTA TEMPORAL — reusada en tabs 1, 2, 3
# ============================================================================
def _render_temporal_view(
    df: pd.DataFrame, config: dict,
    group_cols: list[str], entity_name: str, view_key: str = "",
) -> None:
    metric_label = METRIC_LABEL[config["metric"]]
    st.caption(
        f"Métrica: **{metric_label}** · "
        f"Método: **{config['temporal_method'].upper()}** · "
        f"Ventana: **{config['window']} meses** · "
        f"Umbral: **{config['threshold_temporal']}**"
    )

    with st.spinner("Analizando..."):
        ts = _build_time_series_cached(df, group_cols, config["metric"])
        if len(ts) < 4:
            st.info(f"Muy pocos puntos temporales ({len(ts)} meses). Se necesitan al menos 4.")
            return

        if config["analysis_type"] in ("temporal", "ambos"):
            ts = _detect_temporal_cached(
                ts, group_cols,
                config["temporal_method"], config["window"], config["threshold_temporal"],
            )
        else:
            ts["is_anomaly_temporal"] = False
            ts["media_movil"] = None
            ts["std_movil"]   = None

    ts_agg = (
        ts.groupby(["mes_dt", "Mes"], as_index=False)
        .agg(
            valor=("valor", "mean"),
            media_movil=("media_movil", "mean") if "media_movil" in ts.columns else ("valor", "mean"),
            std_movil=("std_movil", "mean")   if "std_movil"   in ts.columns else ("valor", "mean"),
            is_anomaly=("is_anomaly_temporal", "any"),
        )
        .sort_values("mes_dt")
    )

    if len(ts_agg) == 0:
        st.info("Sin datos temporales")
        return

    # Etiquetas de meses en español
    tick_vals  = ts_agg["mes_dt"].tolist()
    tick_texts = [f"{MESES_ES.get(d.month, d.month)} {d.year}" for d in tick_vals]

    fig = go.Figure()

    if config["temporal_method"] == "z_score" and ts_agg["media_movil"].notna().any():
        thr   = config["threshold_temporal"]
        upper = ts_agg["media_movil"] + thr * ts_agg["std_movil"]
        lower = ts_agg["media_movil"] - thr * ts_agg["std_movil"]
        fig.add_trace(go.Scatter(x=ts_agg["mes_dt"], y=upper, line=dict(width=0),
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=ts_agg["mes_dt"], y=lower,
                                 fill="tonexty", fillcolor="rgba(228,0,43,0.08)",
                                 line=dict(width=0), name=f"Banda ±{thr}σ", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=ts_agg["mes_dt"], y=ts_agg["media_movil"],
                                 mode="lines", line=dict(dash="dash", color="#E4002B", width=1),
                                 name="Media móvil"))

    fig.add_trace(go.Scatter(
        x=ts_agg["mes_dt"], y=ts_agg["valor"],
        mode="lines+markers",
        line=dict(color="#E4002B", width=2),
        marker=dict(size=8, color="#E4002B"),
        name="Valor real",
    ))

    anomalies = ts_agg[ts_agg["is_anomaly"] == True]
    if len(anomalies) > 0:
        fig.add_trace(go.Scatter(
            x=anomalies["mes_dt"], y=anomalies["valor"], mode="markers",
            marker=dict(size=14, color="#B8001F", symbol="x",
                       line=dict(width=2, color="#7A0013")),
            name="Anomalía",
        ))

    fig.update_layout(
        title=dict(text=f"{metric_label} — {entity_name}",
                   font=dict(color="#212529", size=15, weight="bold")),
        xaxis=dict(
            title=dict(text="Mes", font=dict(color="#212529", size=13)),
            tickvals=tick_vals, ticktext=tick_texts,
            tickfont=dict(color="#212529", size=11),
        ),
        yaxis=dict(
            title=dict(text=metric_label, font=dict(color="#212529", size=13)),
            tickfont=dict(color="#212529"),
        ),
        hovermode="x unified",
        height=500,
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="#F8F9FA",
    )
    st.plotly_chart(fig, use_container_width=True)

    desvios = [
        safe_pct(v - m, m)
        for v, m in zip(anomalies["valor"], anomalies["media_movil"])
    ]
    st.caption(insight_anomalias(anomalies["Mes"].tolist(), desvios))

    c1, c2, c3 = st.columns(3)
    c1.metric("Meses analizados", len(ts_agg))
    c2.metric("Anomalías detectadas", int(ts_agg["is_anomaly"].sum()))
    if ts_agg["is_anomaly"].any():
        c3.metric("Última anomalía", anomalies["Mes"].iloc[-1])

    if ts_agg["is_anomaly"].any():
        st.write("### Detalle de anomalías")
        display = anomalies[["Mes", "valor", "media_movil"]].copy()
        fmt = format_currency_full if config["metric"] in ("precio_unitario", "importe_total") else format_quantity
        display["Valor real"] = display["valor"].apply(fmt)
        display["Esperado"]   = display["media_movil"].apply(fmt)
        display["Desvío %"]   = [
            f"{p:+.1f}%" if (p := safe_pct(v - m, m)) is not None else "-"
            for v, m in zip(display["valor"], display["media_movil"])
        ]
        tabla_anom = display[["Mes", "Valor real", "Esperado", "Desvío %"]]
        st.dataframe(tabla_anom, use_container_width=True, hide_index=True)
        render_export_buttons(
            tabla_anom,
            filename=f"anomalias_{config['metric']}",
            title=f"Detalle de anomalías — {entity_name}",
            key=f"anom_detalle_{view_key}",
        )
    else:
        st.success("No se detectaron anomalías con los parámetros actuales.")

    if config["analysis_type"] in ("estructural", "ambos"):
        st.divider()
        _render_structural_section(df, config, view_key=view_key)


def _render_structural_section(df: pd.DataFrame, config: dict, view_key: str = "") -> None:
    st.write("### Análisis Estructural — vs pares comparables")
    peer_cols = ["Prestacion ID", "Mes"]

    with st.spinner("Comparando contra pares..."):
        df_struct = _detect_structural_cached(
            df, peer_cols,
            config["structural_method"], config["threshold_structural"], config["metric"],
        )

    total = len(df_struct)
    anom  = int(df_struct["is_anomaly_structural"].sum())
    c1, c2, c3 = st.columns(3)
    c1.metric("Registros evaluados", f"{total:,}")
    c2.metric("Marcados estructuralmente", f"{anom:,}")
    c3.metric("% anómalos", f"{(anom/total*100) if total > 0 else 0:.1f}%")

    if anom == 0:
        st.info("Sin desvíos estructurales encontrados")
        return

    top_struct = df_struct[df_struct["is_anomaly_structural"]].nlargest(20, "severidad_structural")
    show_cols  = [c for c in ["Prestador Desc", "Prestacion Desc", "Mes", "__metric__", "severidad_structural"]
                  if c in top_struct.columns]
    display = top_struct[show_cols].copy()
    if "__metric__" in display.columns:
        fmt = format_currency_full if config["metric"] in ("precio_unitario", "importe_total") else format_quantity
        display["__metric__"] = display["__metric__"].apply(fmt)
        display = display.rename(columns={"__metric__": "Valor"})
    if "severidad_structural" in display.columns:
        display["severidad_structural"] = display["severidad_structural"].apply(lambda x: f"{x:.2f}")
        display = display.rename(columns={"severidad_structural": "Severidad"})
    st.dataframe(display, use_container_width=True, hide_index=True)
    render_export_buttons(
        display,
        filename=f"estructural_{config['metric']}",
        title="Análisis Estructural — vs pares comparables",
        key=f"anom_estructural_{view_key}",
    )