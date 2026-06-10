"""
Módulo 1 — Simulador de Aumentos de Tarifas.
v0.5.2 — diseño Swiss Medical
"""

from __future__ import annotations

import streamlit as st

from core.data_loader import get_merged_dataset, load_consumo_and_valores
from core.simulator import apply_simulation, merge_match_rate
from ui.formatters import format_currency, format_currency_full
from ui.simulator_controls import render_simulator_controls
from ui.simulator_tabs import render_tabs


# ============================================================================
# CÁLCULO CACHEADO
# ============================================================================
@st.cache_data(show_spinner=False, max_entries=50)
def _apply_simulation_cached(
    df_scope, mode, flat_pct, nomenclador_pcts, prestacion_pcts
):
    """
    Wrapper cacheado de apply_simulation.

    apply_simulation copia el DataFrame y recalcula Consumo Ideal/Simulado en
    cada rerun, también al cambiar de tab (Streamlit ejecuta el cuerpo de todos
    los tabs). Cacheado por (datos + parámetros del aumento), solo se recalcula
    cuando el usuario cambia algún %, prestador o mes; los cambios de tab y
    otras interacciones reusan el resultado.

    months=1 a propósito: "Cantidad CM" ya viene acumulada por mes/ventana de
    liquidación, así que el impacto total es la suma de las filas. Validado
    contra simulaciones reales del negocio (desvío 0.0000%); con months=12 el
    impacto se inflaría 12x.
    """
    return apply_simulation(
        df_merged=df_scope,
        months=1,
        mode=mode,
        flat_pct=flat_pct,
        nomenclador_pcts=nomenclador_pcts,
        prestacion_pcts=prestacion_pcts,
    )


# ============================================================================
# HELPERS DE UI
# ============================================================================

def _metric_card(label: str, value: str, delta: str = "", delta_color: str = "#E4002B", icon: str = "") -> None:
    """Renderiza una card de métrica estilo Swiss Medical."""
    delta_html = ""
    if delta:
        delta_html = f'<div style="margin-top:6px; font-size:13px; font-weight:500; color:{delta_color};">{delta}</div>'

    st.markdown(f"""
    <div style="
        background: #FFFFFF;
        border: 1px solid #E9ECEF;
        border-radius: 10px;
        padding: 20px 24px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        height: 100%;
    ">
        <div style="font-size:11px; font-weight:600; color:#797979;
                    text-transform:uppercase; letter-spacing:0.8px; margin-bottom:8px;">
            {label}
        </div>
        <div style="font-size:28px; font-weight:700; color:#212529; line-height:1.1;">
            {value}
        </div>
        {delta_html}
    </div>
    """, unsafe_allow_html=True)


def _render_metrics(total_ideal: float, total_sim: float, dif: float, pct: float, n_meses) -> None:
    fmt_ideal = format_currency(total_ideal)
    fmt_sim   = format_currency(total_sim)
    fmt_dif   = format_currency(dif)
    fmt_pct   = f"{pct:+.2f}%"
    fmt_imp   = f"{pct:.2f}%"

    if pct > 0:
        delta_color, delta_icon = "#E4002B", "▲"
    elif pct < 0:
        delta_color, delta_icon = "#28A745", "▼"
    else:
        delta_color, delta_icon = "#797979", "—"

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _metric_card("Consumo Ideal", fmt_ideal, icon="")
    with c2:
        _metric_card("Consumo Simulado", fmt_sim, icon="")
    with c3:
        _metric_card("Diferencia", fmt_dif,
                     delta=f"{delta_icon} {fmt_pct}",
                     delta_color=delta_color, icon="")
    with c4:
        _metric_card("Impacto Total", fmt_imp,
                     delta=f"sobre {n_meses} mes(es)",
                     delta_color="#797979", icon="")

    st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)


# ============================================================================
# RENDER PRINCIPAL
# ============================================================================

def render() -> None:
    st.title("Módulo 1 — Simulador de Aumentos")

    df_consumo, df_valores = load_consumo_and_valores()
    if df_consumo is None or df_valores is None:
        _render_waiting_state(df_consumo is not None, df_valores is not None)
        return

    # Normalización + merge cacheados: solo se recalculan si cambian los datos,
    # así no reaparece el indicador de progreso en cada interacción.
    df_merged = get_merged_dataset(df_consumo, df_valores)
    if df_merged is None or len(df_merged) == 0:
        st.error(
            "No se encontraron coincidencias entre Consumo y Valores. "
            "Revisá que las claves (Prestador / Convenio / Prestación) coincidan."
        )
        return

    st.caption(f"Datos listos · **{len(df_merged):,}** registros")

    # El inner join descarta en silencio el consumo sin tarifa. Si la cobertura
    # es baja (tarifario incompleto o de otro prestador), avisar: los totales
    # solo representan la porción con tarifa.
    cobertura = merge_match_rate(df_consumo, df_merged)
    if cobertura < 0.9:
        st.warning(
            f"Atención: solo el **{cobertura:.0%}** del consumo encontró tarifa "
            "en Valores. Los totales representan únicamente esa porción — "
            "verificá que el tarifario corresponda al mismo prestador y período."
        )

    config = render_simulator_controls(df_merged)

    if config["prestador_id"] is None:
        df_scope = df_merged.copy()
    else:
        df_scope = df_merged[df_merged["Prestador ID"] == config["prestador_id"]].copy()

    if len(df_scope) == 0:
        st.warning("Sin datos para el prestador seleccionado.")
        return

    meses_raw = config.get("meses_raw", [])
    if meses_raw and "Mes" in df_scope.columns:
        df_scope = df_scope[df_scope["Mes"].astype(str).isin(meses_raw)].copy()

    if len(df_scope) == 0:
        st.warning("Sin datos para los meses seleccionados.")
        return

    df_simulated = _apply_simulation_cached(
        df_scope,
        config["mode"],
        config["flat_pct"],
        config["nomenclador_pcts"],
        config["prestacion_pcts"],
    )

    n_meses      = len(meses_raw) if meses_raw else "todos"
    total_ideal  = df_simulated["Consumo Ideal"].sum()
    total_sim    = df_simulated["Consumo Simulado"].sum()
    dif          = total_sim - total_ideal
    pct          = (dif / total_ideal * 100) if total_ideal > 0 else 0

    st.caption(f"Período analizado: **{n_meses} mes(es)** · {len(df_simulated):,} registros")
    _render_metrics(total_ideal, total_sim, dif, pct, n_meses)

    with st.expander("Tabla de Negociación — Valores por Prestación", expanded=True):
        st.caption("Valor actual vs. valor ofrecido por prestación.")

        cols_neg = ["Prestacion ID", "Prestacion Desc", "Nomenclador",
                    "Valor Convenido a HOY", "Valor Ofrecido", "% Aumento"]
        df_neg = (
            df_simulated[cols_neg]
            .drop_duplicates(subset=["Prestacion ID"])
            .sort_values("% Aumento", ascending=False)
            .reset_index(drop=True)
        )
        df_neg_display = df_neg.copy()
        df_neg_display["Valor Convenido a HOY"] = df_neg_display["Valor Convenido a HOY"].apply(format_currency_full)
        df_neg_display["Valor Ofrecido"]        = df_neg_display["Valor Ofrecido"].apply(format_currency_full)
        df_neg_display["% Aumento"]             = df_neg_display["% Aumento"].apply(lambda x: f"{x:.2f}%")

        st.dataframe(df_neg_display, use_container_width=True, hide_index=True)
        csv = df_neg.to_csv(index=False).encode("utf-8")
        st.download_button("Descargar tabla de negociación", csv, "negociacion.csv", "text/csv")

    st.divider()

    render_tabs(
        df_merged=df_merged,
        df_simulated=df_simulated,
        df_consumo_raw=df_consumo,
        prestador_id=config["prestador_id"],
    )


# ============================================================================
# HELPERS PRIVADOS
# ============================================================================

def _render_waiting_state(consumo_loaded: bool, valores_loaded: bool) -> None:
    st.info("**Esperando datos** — Subí los archivos desde el sidebar.")
    st.markdown(f"""
    - {"[cargado]" if consumo_loaded else "[pendiente]"} **Archivo de Consumo** (`consumo.xlsx`)
    - {"[cargado]" if valores_loaded else "[pendiente]"} **Archivo de Valores** (`valores.xlsx`)
    """)