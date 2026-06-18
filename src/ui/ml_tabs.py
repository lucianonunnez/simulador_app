"""
Tabs del Módulo 3 (Predicción ML):
    1. Predicción → gráfico histórico + forecast
    2. Comparativa → LightGBM vs Red Neuronal lado a lado
    3. Variables influyentes → qué variables pesan más
    4. Detalle técnico → iteración de la red + corrección de data leakage
    5. Sobre los modelos → explicación técnica
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.ml_predictor import (
    get_feature_importance,
    load_metricas,
    predecir_lightgbm,
    predecir_pablo,
)
from ui.exporters import render_export_buttons
from ui.formatters import format_currency, format_quantity, safe_pct
from ui.insights import insight_prediccion
from ui.theme import (
    COLOR_PRINCIPAL,
    COLOR_SECUNDARIO,
    COLOR_TERCIARIO,
    layout_base,
)


METRIC_LABEL = {
    "importe": "Importe Total",
    "precio": "Precio Unitario",
    "cantidad": "Cantidad",
}

# Nombres internos de los modelos -> etiqueta visible al usuario.
# (Las claves internas "lightgbm"/"pablo_corregido" mapean a archivos y JSON;
# no se tocan, solo cambia lo que ve el usuario.)
MODEL_LABEL = {
    "lightgbm": "LightGBM",
    "pablo_corregido": "Red Neuronal",
}


def render_tabs(df_consumo: pd.DataFrame, config: dict) -> None:
    tabs = st.tabs([
        "Predicción",
        "Comparativa",
        "Variables influyentes",
        "Detalle técnico",
        "Sobre los modelos",
    ])

    with tabs[0]:
        _tab_prediccion(df_consumo, config)

    with tabs[1]:
        _tab_comparativa(df_consumo, config)

    with tabs[2]:
        _tab_feature_importance(config)

    with tabs[3]:
        _tab_pablo_original()

    with tabs[4]:
        _tab_sobre_modelos()


# ============================================================================
# TAB 1 — PREDICCIÓN
# ============================================================================
def _tab_prediccion(df: pd.DataFrame, config: dict) -> None:
    st.subheader("Predicción")

    if not config["models"]:
        st.warning("Seleccioná al menos un modelo en el sidebar.")
        return

    st.caption(
        f"Métrica: **{METRIC_LABEL[config['metric']]}** · "
        f"Modelos: **{', '.join(MODEL_LABEL.get(m, m) for m in config['models'])}**"
    )

    # Selector de modelo principal a graficar
    modelo_principal = st.radio(
        "Modelo principal para graficar",
        config["models"],
        horizontal=True,
        format_func=lambda x: MODEL_LABEL.get(x, x),
    )

    with st.spinner(f"Generando predicciones con {modelo_principal}..."):
        if modelo_principal == "lightgbm":
            pred = predecir_lightgbm(df, config["metric"], config["filtro_prestador"])
        else:
            pred = predecir_pablo(df, config["metric"], config["filtro_prestador"])

    if len(pred) == 0:
        st.warning(
            "No hay suficientes datos para este filtro. "
            "Probá con otro prestador o quitá el filtro."
        )
        return

    # --- Agrupar por mes para ver el agregado temporal ---
    ts = (
        pred.groupby("mes_dt")
        .agg(real=("valor_real", "sum"), prediccion=("prediccion", "sum"))
        .reset_index()
        .sort_values("mes_dt")
    )

    # --- Métricas resumen ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Registros", f"{len(pred):,}")
    c2.metric("Meses", len(ts))

    fmt = format_currency if config["metric"] in ("importe", "precio") else format_quantity
    total_real = ts["real"].sum()
    total_pred = ts["prediccion"].sum()
    error_pct = safe_pct(total_pred - total_real, total_real)

    c3.metric("Real total", fmt(total_real))
    c4.metric("Predicho total", fmt(total_pred),
              f"{error_pct:+.1f}%" if error_pct is not None else None)

    # --- Gráfico ---
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ts["mes_dt"], y=ts["real"],
        mode="lines+markers",
        line=dict(color=COLOR_SECUNDARIO, width=2),
        marker=dict(size=8),
        name="Valor real",
    ))
    fig.add_trace(go.Scatter(
        x=ts["mes_dt"], y=ts["prediccion"],
        mode="lines+markers",
        line=dict(color=COLOR_PRINCIPAL, width=2, dash="dash"),
        marker=dict(size=8, symbol="diamond"),
        name=f"Predicción ({MODEL_LABEL.get(modelo_principal, modelo_principal)})",
    ))
    layout = layout_base(title=f"{METRIC_LABEL[config['metric']]} — real vs predicho")
    layout["xaxis"]["title"] = dict(text="Mes")
    layout["yaxis"]["title"] = dict(text=METRIC_LABEL[config["metric"]])
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)

    texto = insight_prediccion(ts["real"].tolist(), ts["prediccion"].tolist())
    if texto:
        st.caption(texto)

    # --- Tabla de detalle ---
    with st.expander("Ver detalle por mes"):
        display = ts.copy()
        display["Mes"] = display["mes_dt"].dt.strftime("%m-%Y")
        display["Real"] = display["real"].apply(fmt)
        display["Predicho"] = display["prediccion"].apply(fmt)
        display["Error %"] = [
            f"{p:+.1f}%" if (p := safe_pct(pred - real, real)) is not None else "-"
            for pred, real in zip(display["prediccion"], display["real"])
        ]
        tabla_pred = display[["Mes", "Real", "Predicho", "Error %"]]
        st.dataframe(tabla_pred, use_container_width=True, hide_index=True)
        render_export_buttons(
            tabla_pred,
            filename="prediccion_por_mes",
            title="Predicción por mes — Real vs Predicho",
            key="ml_prediccion",
        )


# ============================================================================
# TAB 2 — COMPARATIVA LADO A LADO
# ============================================================================
def _tab_comparativa(df: pd.DataFrame, config: dict) -> None:
    st.subheader("Comparativa de modelos")

    if len(config["models"]) < 2:
        st.info(
            "Activá **ambos modelos** en el sidebar (LightGBM + Red Neuronal) "
            "para ver la comparativa lado a lado."
        )
        return

    # Métricas del entrenamiento
    metricas_all = load_metricas()
    st.write("### Métricas de evaluación (calculadas en el entrenamiento)")

    rows = []
    for model_name in ["lightgbm", "pablo_corregido"]:
        key = f"{model_name}_{config['metric']}"
        m = metricas_all.get(key, {})
        rows.append({
            "Modelo": MODEL_LABEL.get(model_name, model_name),
            "MAE": f"{m.get('mae', 0):,.2f}",
            "R²": f"{m.get('r2', 0):.4f}",
            "N train": f"{m.get('n_train', 0):,}",
            "N test": f"{m.get('n_test', 0):,}",
        })
    df_comp = pd.DataFrame(rows)
    st.dataframe(df_comp, use_container_width=True, hide_index=True)
    render_export_buttons(
        df_comp,
        filename="comparativa_modelos",
        title="Comparativa de modelos — Métricas de evaluación",
        key="ml_comparativa",
    )

    st.caption(
        "**MAE** (Mean Absolute Error): error promedio en unidades originales. Menor = mejor. "
        "**R²**: qué porcentaje de la variabilidad explica el modelo. Mayor = mejor (máx 1.0)."
    )

    st.divider()

    # Predicciones lado a lado
    st.write("### Predicciones aplicadas sobre tus datos")

    with st.spinner("Generando predicciones de ambos modelos..."):
        pred_lgb = predecir_lightgbm(df, config["metric"], config["filtro_prestador"])
        pred_pablo = predecir_pablo(df, config["metric"], config["filtro_prestador"])

    if len(pred_lgb) == 0 or len(pred_pablo) == 0:
        st.warning("No hay suficientes datos para generar predicciones.")
        return

    # Agregar por mes
    ts_lgb = pred_lgb.groupby("mes_dt").agg(real=("valor_real", "sum"), pred=("prediccion", "sum")).reset_index()
    ts_pablo = pred_pablo.groupby("mes_dt").agg(real=("valor_real", "sum"), pred=("prediccion", "sum")).reset_index()

    # Gráfico combinado
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ts_lgb["mes_dt"], y=ts_lgb["real"],
        mode="lines+markers", name="Valor real",
        line=dict(color=COLOR_SECUNDARIO, width=3),
    ))
    fig.add_trace(go.Scatter(
        x=ts_lgb["mes_dt"], y=ts_lgb["pred"],
        mode="lines+markers", name="LightGBM",
        line=dict(color=COLOR_PRINCIPAL, width=2, dash="dash"),
    ))
    fig.add_trace(go.Scatter(
        x=ts_pablo["mes_dt"], y=ts_pablo["pred"],
        mode="lines+markers", name="Red Neuronal",
        line=dict(color=COLOR_TERCIARIO, width=2, dash="dot"),
    ))
    layout = layout_base(title="Real vs ambos modelos", height=500)
    layout["xaxis"]["title"] = dict(text="Mes")
    layout["yaxis"]["title"] = dict(text=METRIC_LABEL[config["metric"]])
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)


# ============================================================================
# TAB 3 — FEATURE IMPORTANCE
# ============================================================================
def _tab_feature_importance(config: dict) -> None:
    st.subheader("Variables más influyentes")
    st.caption(
        "Qué variables pesan más para predecir la métrica elegida. "
        "Solo el modelo LightGBM lo expone de forma interpretable."
    )

    df_imp = get_feature_importance(config["metric"], top_n=15)

    if len(df_imp) == 0:
        st.warning("No se pudo obtener feature importance. ¿Está el modelo LightGBM cargado?")
        return

    fig = px.bar(
        df_imp.sort_values("importance"),
        x="importance",
        y="feature",
        orientation="h",
        title=f"Top 15 variables — LightGBM ({METRIC_LABEL[config['metric']]})",
    )
    fig.update_traces(marker_color=COLOR_PRINCIPAL)
    layout = layout_base(
        title=f"Top 15 variables — LightGBM ({METRIC_LABEL[config['metric']]})",
        height=500,
    )
    layout["hovermode"] = "closest"
    fig.update_layout(**layout)
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("¿Qué significa cada feature?"):
        st.markdown("""
        - **lag_1, lag_2, lag_3**: valor del mes pasado, hace 2 meses, hace 3 meses.
        - **rolling_mean_3, rolling_mean_6**: promedio de los últimos 3 o 6 meses (sin incluir el actual).
        - **rolling_std_3, rolling_std_6**: desvío de los últimos 3 o 6 meses.
        - **activo_lag_1/2/3**: flag binario de si hubo actividad ese mes pasado.
        - **mes_num**: mes del año (1-12) para capturar estacionalidad.
        - **trimestre**: trimestre (1-4).
        - **Nomenclador, Tipo Clase CM, Gama**: variables categóricas del contexto.
        """)


# ============================================================================
# TAB 4 — DETALLE TÉCNICO (iteración de la red neuronal)
# ============================================================================
def _tab_pablo_original() -> None:
    st.subheader("Detalle técnico de la red neuronal")

    st.info(
        "Esta sección documenta una **iteración inicial** de la red neuronal y la "
        "corrección metodológica que se le aplicó. Es referencia técnica; **la app "
        "usa la versión corregida**."
    )

    st.write("### Arquitectura de la red")
    st.code("""
    # Arquitectura del modelo (Keras)
    model = Sequential([
        Dense(6, activation='relu'),    # Capa oculta 1
        Dense(3, activation='relu'),    # Capa oculta 2
        Dense(1),                       # Capa de salida (lineal)
    ])
    model.compile(optimizer='adam', loss='mae', metrics=['mae', 'mse'])

    # Entrenamiento
    early_stop = EarlyStopping(monitor='val_loss', patience=15)
    model.fit(
        X_train, y_train,
        batch_size=20,
        epochs=200,
        validation_data=(X_test, y_test),
        callbacks=[early_stop],
    )
    """, language="python")

    st.write("### Problema detectado: data leakage")
    st.markdown("""
    La iteración inicial usaba como features **todas las columnas de todos los meses disponibles**:

    ```python
    target_col_names = ['CM Agosto 2023']
    feature_cols_names = [c for c in numeric_cols if c not in target_col_names]
    ```

    El problema es que `numeric_cols` incluye **meses posteriores al target** (Septiembre 2023, Octubre 2023, ..., hasta el último mes del dataset). Es decir, el modelo usaba **información del futuro** para predecir el pasado.

    Además del leakage temporal había otros dos problemas menores: el `ID` del registro
    (un identificador sin significado predictivo) entraba como feature por ser numérico,
    y los valores faltantes se rellenaban con la media de cada columna calculada sobre el
    dataset completo **antes** del split train/validación, filtrando información del set
    de validación al entrenamiento.

    **Consecuencia:** los resultados se ven muy buenos (R² alto, MAE bajo), pero **no son reproducibles en producción** — al momento de predecir el próximo mes, naturalmente no tenemos los meses siguientes.
    """)

    st.write("### Cómo se corrigió para la app")
    st.markdown("""
    En el Módulo 3 mantenemos la **misma arquitectura** (`Dense(6,relu) → Dense(3,relu) → Dense(1)`)
    pero cambiamos las features:

    - **Antes:** columnas de todos los meses (incluyendo futuros).
    - **Ahora:** lags (valor hace 1, 2, 3 meses), medias móviles, estacionalidad.

    Esto permite que el modelo funcione para **predicciones reales** en escenarios de producción.
    """)

    st.write("### Comparativa de ambos enfoques")
    st.markdown("""
    | Aspecto | Iteración inicial | Versión corregida (en esta app) |
    |---------|----------------|--------------------------------|
    | Arquitectura | `Dense(6,relu)→Dense(3,relu)→Dense(1)` | **Idéntica** |
    | Optimizer / Loss | `adam / mae` | **Idénticos** |
    | Batch size / Epochs | `20 / 200` | **Idénticos** |
    | Early Stopping | `monitor='val_loss', patience=15` (sin `restore_best_weights`) | `patience=15` |
    | Features | Columnas de todos los meses + ID (leakage) | Lags + rolling del pasado |
    | Data leakage | Sí | No |
    | Uso en producción | No válido | Sí |
    """)

    st.caption(
        "Nota de reproducibilidad: el notebook de la iteración inicial, tal como fue "
        "entregado, no corre de punta a punta (una celda falla por una variable sin "
        "definir y otra referencia un scaler con otro nombre); los resultados que "
        "muestra provienen de una ejecución anterior del kernel."
    )


# ============================================================================
# TAB 5 — SOBRE LOS MODELOS
# ============================================================================
def _tab_sobre_modelos() -> None:
    st.subheader("Sobre los modelos")

    st.write("### LightGBM")
    st.markdown("""
    **Qué es:** algoritmo de gradient boosting basado en árboles de decisión.
    Es el estándar de la industria para problemas tabulares.

    **Ventajas:**
    - Muy rápido de entrenar y predecir
    - Maneja categóricas nativamente (sin necesidad de one-hot)
    - Tolera NaN
    - Feature importance interpretable
    - Normalmente gana contra redes neuronales en datos tabulares

    **Config usada:**
    ```
    num_leaves=31, learning_rate=0.05, feature_fraction=0.9,
    bagging_fraction=0.8, num_boost_round=500, early_stopping=30
    ```
    """)

    st.write("### Red Neuronal")
    st.markdown("""
    **Qué es:** una red neuronal feed-forward, aplicada sin data leakage.

    **Arquitectura:**
    ```
    Input → Dense(6, relu) → Dense(3, relu) → Dense(1, linear)
    Optimizer: Adam  |  Loss: MAE  |  Batch: 20  |  Epochs: max 200
    EarlyStopping: patience 15 sobre val_loss
    ```

    **Por qué en general da peor que LightGBM:**
    - Es una red muy chica (~350 parámetros)
    - Las redes neuronales no suelen dominar en datos tabulares
    - Para ganar necesitaríamos una arquitectura mucho más grande + más regularización

    **Por qué la mantenemos:**
    - Sirve como baseline de comparación
    - Permite explorar cómo escalan arquitecturas distintas con los mismos datos
    """)

    st.write("### Entrenamiento")
    metricas = load_metricas()
    if metricas:
        st.write("**Métricas finales de los 6 modelos entrenados:**")
        rows = []
        for key, m in metricas.items():
            partes = key.rsplit("_", 1)
            rows.append({
                "Modelo": partes[0],
                "Métrica": partes[1],
                "MAE": f"{m.get('mae', 0):,.2f}",
                "R²": f"{m.get('r2', 0):.4f}",
                "N train": f"{m.get('n_train', 0):,}",
                "N test": f"{m.get('n_test', 0):,}",
            })
        df_entr = pd.DataFrame(rows)
        st.dataframe(df_entr, use_container_width=True, hide_index=True)
        render_export_buttons(
            df_entr,
            filename="metricas_entrenamiento",
            title="Métricas finales de los modelos entrenados",
            key="ml_entrenamiento",
        )

    st.caption(
        "**Nota:** los modelos son estáticos (entrenados una vez y cargados desde "
        "disco). Se prevé re-entrenarlos con datos más recientes en futuras versiones."
    )
