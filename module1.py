"""
Módulo 1 — Simulador de Aumentos de Tarifas.
v0.5.2 — diseño Swiss Medical
"""

from __future__ import annotations

import time

import pandas as pd
import streamlit as st

from core.data_loader import load_consumo_and_valores
from core.simulator import apply_simulation, merge_datasets, normalize_dataframes
from ui.formatters import format_currency, format_currency_full
from ui.simulator_controls import render_simulator_controls
from ui.simulator_tabs import render_tabs


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
            {icon}&nbsp;{label}
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
        _metric_card("Consumo Ideal", fmt_ideal, icon="💰")
    with c2:
        _metric_card("Consumo Simulado", fmt_sim, icon="📈")
    with c3:
        _metric_card("Diferencia", fmt_dif,
                     delta=f"{delta_icon} {fmt_pct}",
                     delta_color=delta_color, icon="📊")
    with c4:
        _metric_card("Impacto Total", fmt_imp,
                     delta=f"sobre {n_meses} mes(es)",
                     delta_color="#797979", icon="⚡")

    st.markdown("<div style='margin-top:16px;'></div>", unsafe_allow_html=True)


# ============================================================================
# RENDER PRINCIPAL
# ============================================================================

def render() -> None:
    _MODULO_ID = "module1"
    if "ultimo_modulo" not in st.session_state:
        st.session_state["ultimo_modulo"] = _MODULO_ID
    elif st.session_state["ultimo_modulo"] != _MODULO_ID:
        st.session_state["ultimo_modulo"] = _MODULO_ID
        st.rerun()

    st.title("Módulo 1 — Simulador de Aumentos")

    df_consumo, df_valores = load_consumo_and_valores()
    if df_consumo is None or df_valores is None:
        _render_waiting_state(df_consumo is not None, df_valores is not None)
        return

    df_merged = _process_with_feedback(df_consumo, df_valores)
    if df_merged is None:
        return

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

    df_simulated = apply_simulation(
        df_merged=df_scope,
        months=1,
        mode=config["mode"],
        flat_pct=config["flat_pct"],
        nomenclador_pcts=config["nomenclador_pcts"],
        prestacion_pcts=config["prestacion_pcts"],
    )

    n_meses      = len(meses_raw) if meses_raw else "todos"
    total_ideal  = df_simulated["Consumo Ideal"].sum()
    total_sim    = df_simulated["Consumo Simulado"].sum()
    dif          = total_sim - total_ideal
    pct          = (dif / total_ideal * 100) if total_ideal > 0 else 0

    st.caption(f"Período analizado: **{n_meses} mes(es)** · {len(df_simulated):,} registros")
    _render_metrics(total_ideal, total_sim, dif, pct, n_meses)

    with st.expander("🤝 Tabla de Negociación — Valores por Prestación", expanded=True):
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
        st.download_button("📥 Descargar tabla de negociación", csv, "negociacion.csv", "text/csv")

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
    st.info("⏳ **Esperando datos** — Subí los archivos desde el sidebar.")
    st.markdown(f"""
    - {"✅" if consumo_loaded else "⬜"} **Archivo de Consumo** (`consumo.xlsx`)
    - {"✅" if valores_loaded else "⬜"} **Archivo de Valores** (`valores.xlsx`)
    """)


def _process_with_feedback(
    df_consumo: pd.DataFrame, df_valores: pd.DataFrame
) -> pd.DataFrame | None:
    with st.status("⚙️ Procesando datos...", expanded=True, state="running") as status:
        st.write(f"📄 Consumo leído → **{len(df_consumo):,}** filas")
        time.sleep(0.15)
        st.write(f"📄 Valores leído → **{len(df_valores):,}** filas")
        time.sleep(0.15)
        st.write("🔄 Normalizando tipos de datos...")
        df_consumo, df_valores = normalize_dataframes(df_consumo, df_valores)
        st.write("✅ Normalización completa")
        time.sleep(0.15)
        st.write("🔗 Uniendo datasets...")
        df_merged = merge_datasets(df_consumo, df_valores)

        if len(df_merged) == 0:
            status.update(label="❌ Error en el procesamiento", state="error", expanded=True)
            st.write("❌ **No se encontraron coincidencias entre Consumo y Valores.**")
            return None

        st.write(f"✅ Merge completo → **{len(df_merged):,}** registros")
        status.update(
            label=f"✅ Datos listos ({len(df_merged):,} registros)",
            state="complete", expanded=False,
        )
    return df_merged