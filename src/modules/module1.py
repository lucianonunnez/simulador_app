"""
Módulo 1 — Simulador de Aumentos de Tarifas.
v0.5.2 — diseño Swiss Medical
"""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from core.cachekeys import df_fingerprint
from core.data_loader import (
    get_merged_dataset,
    get_prestadores_disponibles,
    load_consumo_and_valores,
    source_uses_uploads,
)
from core.simulator import apply_simulation, impact_metrics, merge_coverage
from ui.formatters import format_currency, format_currency_full, format_int, format_pct
from ui.simulator_controls import render_simulator_controls
from ui.simulator_tabs import render_tabs


# ============================================================================
# CÁLCULO CACHEADO
# ============================================================================
@st.cache_data(show_spinner=False, max_entries=10,
               hash_funcs={pd.DataFrame: df_fingerprint})
def _tabla_negociacion(df_simulated: pd.DataFrame) -> pd.DataFrame:
    """Tabla de valores por prestación (cacheada: el drop_duplicates sobre
    cientos de miles de filas costaba en cada rerun)."""
    cols_neg = ["Prestacion ID", "Prestacion Desc", "Nomenclador",
                "Valor Convenido a HOY", "Valor Ofrecido", "% Aumento"]
    return (
        df_simulated[cols_neg]
        .drop_duplicates(subset=["Prestacion ID"])
        .sort_values("% Aumento", ascending=False)
        .reset_index(drop=True)
    )


@st.cache_data(show_spinner=False, max_entries=50,
               hash_funcs={pd.DataFrame: df_fingerprint})
def _apply_simulation_cached(
    df_scope, mode, flat_pct, nomenclador_pcts, prestacion_pcts,
    prestacion_valores=None,
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
        prestacion_valores=prestacion_valores,
    )


# ============================================================================
# HELPERS DE UI
# ============================================================================

def _render_cobertura_y_tarifario(df_consumo: pd.DataFrame, df_merged: pd.DataFrame) -> None:
    """
    Cobertura del merge (por FILAS y por IMPORTE) + vigencia del tarifario.

    El inner join descarta en silencio el consumo sin tarifa: medir solo filas
    enmascara cuánta plata queda FUERA de la simulación (hallazgo real: ~98% de
    filas con tarifa pero ~73% del importe). Acá se hace visible. Además se
    muestra a qué 'Mes Vigencia' corresponde el tarifario que se está usando,
    para que no haya confusión cuando los $ no calzan con un workbook viejo.
    """
    cob = merge_coverage(df_consumo, df_merged)

    # Vigencia del tarifario realmente usado en el merge (la más reciente).
    vigencia = None
    if "Mes Vigencia" in df_merged.columns:
        from core.excel_utils import normalize_month_series

        # Sobre los valores ÚNICOS (no la columna entera): el dataset puede
        # tener cientos de miles de filas y esto corre en cada rerun.
        vig_unicos = pd.Series(df_merged["Mes Vigencia"].dropna().unique())
        dt = pd.to_datetime(
            normalize_month_series(vig_unicos), format="%m-%Y", errors="coerce"
        )
        if dt.notna().any():
            vigencia = dt.max().strftime("%m-%Y")

    partes = [f"Cobertura del tarifario: **{format_pct(cob['filas'] * 100, 1)}** de las filas"]
    if cob["importe"] is not None:
        partes.append(f"**{format_pct(cob['importe'] * 100, 1)}** del importe")
    if vigencia:
        partes.append(f"Tarifario al **{vigencia}**")
    st.caption(" · ".join(partes))

    if cob["importe_sin_tarifa"]:
        st.caption(
            f"⚠️ Quedan **{format_currency(cob['importe_sin_tarifa'])}** de consumo "
            "sin tarifa (no entra a la simulación): medicamentos, 'No asignado' u "
            "otras prestaciones sin valor convenido."
        )


def _metric_card(label: str, value: str, delta: str = "", delta_color: str = "#E4002B", icon: str = "") -> None:
    """Renderiza una card de métrica estilo Swiss Medical."""
    # html.escape: la card interpola sus argumentos en HTML. Hoy llegan
    # formateados (montos y labels fijos), pero se escapan igual para que un
    # caller futuro con texto derivado de datos no habilite XSS.
    label, value, delta = html.escape(label), html.escape(value), html.escape(delta)
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
    fmt_imp   = format_pct(pct)

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

def _prestador_seleccionado() -> int | None:
    """ID del prestador elegido en el selector (estado persistente del widget),
    o None si es 'TODOS' / aún no se eligió."""
    label = st.session_state.get("sim_prest")
    if not label or label == "TODOS":
        return None
    try:
        return int(str(label).split(" - ")[0])
    except (ValueError, IndexError):
        return None


def render() -> None:
    st.title("Módulo 1 — Simulador de Aumentos")

    # ── Anti-"fantasma" de la página anterior ──
    # Al navegar, Streamlit muestra grisado el frame previo (el Inicio) hasta que
    # el contenido nuevo lo reemplaza. La primera carga (cientos de miles de
    # filas + merge) tarda, así que durante esa ventana se veían las "sombras"
    # del Inicio. Un placeholder que ocupa el alto del viewport, renderizado
    # ANTES de la carga, empuja ese contenido stale fuera de vista; se limpia
    # apenas hay datos. En reruns con caché la carga es instantánea, así que el
    # placeholder no llega a pintarse (no parpadea en cada interacción).
    cargando = st.empty()
    cargando.markdown(
        "<div style='min-height:80vh; display:flex; align-items:center; "
        "justify-content:center; color:#797979; font-size:15px; "
        "letter-spacing:.3px;'>Cargando datos del simulador…</div>",
        unsafe_allow_html=True,
    )

    # Cuando la fuente usa archivos subidos (solo o combinados) se trae el
    # universo completo y el selector de prestadores se arma desde los datos
    # (catalogo=None) — así aparecen también los prestadores subidos. Si la
    # fuente es la base, se mantiene el push-down: se carga SOLO el prestador
    # elegido (filtro en SQL) y el selector usa el catálogo liviano de DuckDB.
    if source_uses_uploads():
        catalogo = None
        df_consumo, df_valores = load_consumo_and_valores()
    else:
        catalogo = get_prestadores_disponibles()
        pid_previo = _prestador_seleccionado() if catalogo else None
        if pid_previo is not None:
            df_consumo, df_valores = load_consumo_and_valores(prestador_ids=[pid_previo])
        else:
            df_consumo, df_valores = load_consumo_and_valores()

    if df_consumo is None or df_valores is None:
        cargando.empty()
        _render_waiting_state(df_consumo is not None, df_valores is not None)
        return

    # Normalización + merge cacheados: solo se recalculan si cambian los datos,
    # así no reaparece el indicador de progreso en cada interacción.
    df_merged = get_merged_dataset(df_consumo, df_valores)
    if df_merged is None or len(df_merged) == 0:
        cargando.empty()
        st.error(
            "No se encontraron coincidencias entre Consumo y Valores. "
            "Revisá que las claves (Prestador / Convenio / Prestación) coincidan."
        )
        return

    cargando.empty()
    st.caption(f"Datos listos · **{format_int(len(df_merged))}** registros")
    _render_cobertura_y_tarifario(df_consumo, df_merged)

    config = render_simulator_controls(df_merged, prestadores=catalogo)

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

    # ── Universo simulable ("Pauta" del proceso de negociación) ──
    # Quedan fuera las filas sin tarifa positiva y las prestaciones excluidas
    # manualmente (los "No pauta": débitos, ajustes, módulos especiales).
    mask = df_scope["Valor Convenido a HOY"] > 0
    if config["excluidas"]:
        mask &= ~df_scope["Prestacion ID"].isin(config["excluidas"])
    df_simulable = df_scope[mask]
    n_fuera = len(df_scope) - len(df_simulable)

    if len(df_simulable) == 0:
        st.warning("No quedan filas simulables: todas están sin tarifa o excluidas.")
        return

    df_simulated = _apply_simulation_cached(
        df_simulable,
        config["mode"],
        config["flat_pct"],
        config["nomenclador_pcts"],
        config["prestacion_pcts"],
        config["prestacion_valores"],
    )

    n_meses      = len(meses_raw) if meses_raw else "todos"
    if meses_raw:
        n_meses_num = len(meses_raw)
    elif "Mes" in df_scope.columns:
        n_meses_num = max(int(df_scope["Mes"].nunique()), 1)
    else:
        n_meses_num = 12
    total_ideal  = df_simulated["Consumo Ideal"].sum()
    total_sim    = df_simulated["Consumo Simulado"].sum()
    dif          = total_sim - total_ideal
    pct          = (dif / total_ideal * 100) if total_ideal > 0 else 0

    detalle_excl = f" · Excluidas (No pauta / sin tarifa): **{format_int(n_fuera)}**" if n_fuera else ""
    st.caption(
        f"Período analizado: **{n_meses} mes(es)** · "
        f"{format_int(len(df_simulated))} registros simulados{detalle_excl}"
    )
    _render_metrics(total_ideal, total_sim, dif, pct, n_meses)

    # ── Métricas de negociación (doble escenario / extrapauta, modo plano) ──
    metrics_prop = None
    if config["flat_pct_propuesto"] is not None:
        df_sim_prop = _apply_simulation_cached(
            df_simulable, "plano", config["flat_pct_propuesto"], {}, {}, {},
        )
        metrics_prop = impact_metrics(df_sim_prop, config["pauta_pct"], n_meses_num)

    if metrics_prop is not None or config["pauta_pct"] is not None:
        metrics_sol = impact_metrics(df_simulated, config["pauta_pct"], n_meses_num)
        _render_negociacion(metrics_sol, metrics_prop, config, n_meses_num)

    with st.expander("Tabla de Negociación — Valores por Prestación", expanded=True):
        st.caption("Valor actual vs. valor ofrecido por prestación.")

        df_neg = _tabla_negociacion(df_simulated)
        df_neg_display = df_neg.copy()
        df_neg_display["Valor Convenido a HOY"] = df_neg_display["Valor Convenido a HOY"].apply(format_currency_full)
        df_neg_display["Valor Ofrecido"]        = df_neg_display["Valor Ofrecido"].apply(format_currency_full)
        df_neg_display["% Aumento"]             = df_neg_display["% Aumento"].apply(format_pct)

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

    st.divider()
    _render_validador_workbook()


# ============================================================================
# HELPERS PRIVADOS
# ============================================================================

def _render_negociacion(
    metrics_sol: dict, metrics_prop: dict | None, config: dict, n_meses_num: int
) -> None:
    """Tabla de impactos por escenario, réplica de la cabecera del workbook
    de negociación (Impacto %/total/mensual y Extrapauta si hay pauta)."""
    st.markdown("##### Métricas de negociación")
    notas = [f"Impacto mensual = total / {n_meses_num} mes(es)"]
    if config["pauta_pct"] is not None:
        notas.append(f"Pauta de referencia: **{format_pct(config['pauta_pct'])}**")
    st.caption(" · ".join(notas))

    rows = []
    escenarios = [(f"Solicitado (general {format_pct(config['flat_pct'], 1)})", metrics_sol)]
    if metrics_prop is not None:
        escenarios.append(
            (f"Propuesto ({format_pct(config['flat_pct_propuesto'], 1)})", metrics_prop)
        )
    for nombre, m in escenarios:
        row = {
            "Escenario": nombre,
            "Impacto %": format_pct(m["impacto_pct"] * 100),
            "Impacto total": format_currency_full(m["impacto"]),
            "Impacto mensual": format_currency_full(m["impacto_mensual"]),
        }
        if "extrapauta" in m:
            row["Extrapauta %"] = format_pct(m["extrapauta_pct"] * 100)
            row["Extrapauta total"] = format_currency_full(m["extrapauta"])
            row["Extrapauta mensual"] = format_currency_full(m["extrapauta_mensual"])
        rows.append(row)

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_validador_workbook() -> None:
    """
    Validador de confianza: subir un workbook del negocio y verificar que el
    motor de la app reproduce su Impacto, por dos rutas independientes
    (reconstruido Cantidad×Valor vs los Q×P que el workbook ya trae).

    No depende de la simulación en pantalla: es un chequeo autónomo del motor
    contra un archivo de referencia. Si las dos rutas coinciden, el workbook es
    internamente consistente y la app lo reproduce.
    """
    with st.expander("🔍 Validar contra un workbook del negocio", expanded=False):
        st.caption(
            "Subí una simulación ya resuelta por el equipo (hoja 'Simulación'). "
            "La app recalcula el Impacto con su propio motor y muestra el desvío "
            "entre dos rutas independientes — una verificación de confianza."
        )
        up = st.file_uploader(
            "Workbook (.xlsx)", type=["xlsx"], key="val_workbook",
            help="El archivo no se guarda: se procesa en memoria solo para validar.",
        )
        if up is None:
            return

        from core.workbook_validacion import validar_workbook

        try:
            res = validar_workbook(up.getvalue())
        except Exception as e:  # noqa: BLE001 — mensaje entendible al usuario
            st.error(
                "No se pudo leer el workbook. Verificá que tenga una hoja "
                f"'Simulación' con la columna 'Cantidad CM'. (Detalle: {e})"
            )
            return

        st.caption(
            f"{format_int(res['n_filas'])} filas · "
            f"{format_int(res['n_pauta'])} en universo Pauta"
        )

        filas = []
        for nombre, esc in (("Solicitado", res["solicitado"]),
                            ("Propuesto", res["propuesto"])):
            if esc is None:
                continue
            fila = {
                "Escenario": nombre,
                "Impacto % (app)": f"{esc['impacto_pct'] * 100:.4f}%",
                "Impacto anual": format_currency_full(esc["impacto"]),
                "Impacto mensual": format_currency_full(esc["impacto_mensual"]),
            }
            if esc.get("desvio_qxp") is not None:
                fila["Desvío vs Q×P del negocio"] = f"{esc['desvio_qxp'] * 100:.6f}%"
            filas.append(fila)

        if not filas:
            st.warning("El workbook no trae valores simulables (Solicitado/Propuesto).")
            return

        st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)

        desvios = [
            esc["desvio_qxp"] for esc in (res["solicitado"], res["propuesto"])
            if esc and esc.get("desvio_qxp") is not None
        ]
        if desvios and max(desvios) < 1e-6:
            st.success(
                "✅ El motor de la app reproduce el workbook: las dos rutas "
                "(reconstruido y Q×P del negocio) coinciden (desvío < 0,0001%)."
            )
        elif desvios:
            st.warning(
                f"Desvío máximo entre rutas: {max(desvios) * 100:.4f}%. "
                "Revisá que el workbook no tenga filas con Q×P inconsistentes."
            )


def _render_waiting_state(consumo_loaded: bool, valores_loaded: bool) -> None:
    st.info(
        "**Esperando datos** — Abrí la sección **«Carga de datos»** del menú "
        "izquierdo y subí los archivos (o corré `python scripts/ingest.py`)."
    )
    st.markdown(f"""
    - {"✔ cargado" if consumo_loaded else "✘ pendiente"} — **Consumo** (xlsx/csv)
    - {"✔ cargado" if valores_loaded else "✘ pendiente"} — **Valores** (xlsx/csv)
    """)