"""
Tabs del Módulo 3 (Predicción ML):
    1. Predicción → gráfico histórico + forecast
    2. Comparativa → LightGBM vs Pablo corregido lado a lado
    3. Feature Importance → qué variables pesan más
    4. Pablo original → sección museo (Opción P3)
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
from ui.formatters import format_currency, format_currency_full, format_quantity


METRIC_LABEL = {
    "importe": "Importe Total",
    "precio": "Precio Unitario",
    "cantidad": "Cantidad",
}


def render_tabs(df_consumo: pd.DataFrame, config: dict) -> None:
    tabs = st.tabs([
        "🎯 Predicción",
        "📊 Comparativa",
        "🔍 Feature Importance",
        "📚 Pablo Original",
        "ℹ️ Sobre los modelos",
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
    st.subheader("🎯 Predicción")

    if not config["models"]:
        st.warning("Seleccioná al menos un modelo en el sidebar.")
        return

    st.caption(
        f"Métrica: **{METRIC_LABEL[config['metric']]}** · "
        f"Modelos: **{', '.join(config['models'])}**"
    )

    # Selector de modelo principal a graficar
    modelo_principal = st.radio(
        "Modelo principal para graficar",
        config["models"],
        horizontal=True,
        format_func=lambda x: "LightGBM" if x == "lightgbm" else "Red Neuronal (Pablo)",
    )

    with st.spinner(f"Generando predicciones con {modelo_principal}..."):
        if modelo_principal == "lightgbm":
            pred = predecir_lightgbm(df, config["metric"], config["filtro_prestador"])
        else:
            pred = predecir_pablo(df, config["metric"], config["filtro_prestador"])

    if len(pred) == 0:
        st.warning(
            "⚠️ No hay suficientes datos para este filtro. "
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
    c1.metric("📊 Registros", f"{len(pred):,}")
    c2.metric("📅 Meses", len(ts))

    fmt = format_currency if config["metric"] in ("importe", "precio") else format_quantity
    total_real = ts["real"].sum()
    total_pred = ts["prediccion"].sum()
    error_pct = ((total_pred - total_real) / total_real * 100) if total_real > 0 else 0

    c3.metric("💰 Real total", fmt(total_real))
    c4.metric("🎯 Predicho total", fmt(total_pred), f"{error_pct:+.1f}%")

    # --- Gráfico ---
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=ts["mes_dt"], y=ts["real"],
        mode="lines+markers",
        line=dict(color="#2c3e50", width=2),
        marker=dict(size=8),
        name="Valor real",
    ))
    fig.add_trace(go.Scatter(
        x=ts["mes_dt"], y=ts["prediccion"],
        mode="lines+markers",
        line=dict(color="#667eea", width=2, dash="dash"),
        marker=dict(size=8, symbol="diamond"),
        name=f"Predicción ({modelo_principal})",
    ))
    fig.update_layout(
        title=f"{METRIC_LABEL[config['metric']]} — real vs predicho",
        xaxis_title="Mes",
        yaxis_title=METRIC_LABEL[config["metric"]],
        hovermode="x unified",
        height=450,
    )
    st.plotly_chart(fig, use_container_width=True)

    # --- Tabla de detalle ---
    with st.expander("📋 Ver detalle por mes"):
        display = ts.copy()
        display["Mes"] = display["mes_dt"].dt.strftime("%m-%Y")
        display["Real"] = display["real"].apply(fmt)
        display["Predicho"] = display["prediccion"].apply(fmt)
        display["Error %"] = ((display["prediccion"] - display["real"]) / display["real"] * 100).apply(
            lambda x: f"{x:+.1f}%" if pd.notna(x) and x != float("inf") else "-"
        )
        st.dataframe(
            display[["Mes", "Real", "Predicho", "Error %"]],
            use_container_width=True,
            hide_index=True,
        )


# ============================================================================
# TAB 2 — COMPARATIVA LADO A LADO
# ============================================================================
def _tab_comparativa(df: pd.DataFrame, config: dict) -> None:
    st.subheader("📊 Comparativa de modelos")

    if len(config["models"]) < 2:
        st.info(
            "💡 Activá **ambos modelos** en el sidebar (LightGBM + Pablo corregido) "
            "para ver la comparativa lado a lado."
        )
        return

    # Métricas del entrenamiento
    metricas_all = load_metricas()
    st.write("### 🏆 Métricas de evaluación (calculadas en el entrenamiento)")

    rows = []
    for model_name in ["lightgbm", "pablo_corregido"]:
        key = f"{model_name}_{config['metric']}"
        m = metricas_all.get(key, {})
        rows.append({
            "Modelo": "LightGBM" if model_name == "lightgbm" else "Red Neuronal (Pablo)",
            "MAE": f"{m.get('mae', 0):,.2f}",
            "R²": f"{m.get('r2', 0):.4f}",
            "N train": f"{m.get('n_train', 0):,}",
            "N test": f"{m.get('n_test', 0):,}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.caption(
        "**MAE** (Mean Absolute Error): error promedio en unidades originales. Menor = mejor. "
        "**R²**: qué porcentaje de la variabilidad explica el modelo. Mayor = mejor (máx 1.0)."
    )

    st.divider()

    # Predicciones lado a lado
    st.write("### 📈 Predicciones aplicadas sobre tus datos")

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
        line=dict(color="#2c3e50", width=3),
    ))
    fig.add_trace(go.Scatter(
        x=ts_lgb["mes_dt"], y=ts_lgb["pred"],
        mode="lines+markers", name="LightGBM",
        line=dict(color="#1f77b4", width=2, dash="dash"),
    ))
    fig.add_trace(go.Scatter(
        x=ts_pablo["mes_dt"], y=ts_pablo["pred"],
        mode="lines+markers", name="Red Neuronal (Pablo)",
        line=dict(color="#9467bd", width=2, dash="dot"),
    ))
    fig.update_layout(
        title="Real vs ambos modelos",
        xaxis_title="Mes",
        yaxis_title=METRIC_LABEL[config["metric"]],
        hovermode="x unified",
        height=500,
    )
    st.plotly_chart(fig, use_container_width=True)


# ============================================================================
# TAB 3 — FEATURE IMPORTANCE
# ============================================================================
def _tab_feature_importance(config: dict) -> None:
    st.subheader("🔍 Feature Importance (LightGBM)")
    st.caption(
        "Qué variables pesan más para predecir la métrica elegida. "
        "Solo LightGBM lo soporta de forma interpretable."
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
        title=f"Top 15 features — Modelo: LightGBM {config['metric']}",
    )
    fig.update_traces(marker_color="#667eea")
    fig.update_layout(height=500)
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("📖 ¿Qué significa cada feature?"):
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
# TAB 4 — PABLO ORIGINAL (Opción P3: mostrar como museo)
# ============================================================================
def _tab_pablo_original() -> None:
    st.subheader("📚 Enfoque original de Pablo")

    st.info(
        "Esta sección muestra el **notebook original** del primer intento de Pablo, "
        "conservado como referencia histórica. **No se usa en producción** por el motivo explicado abajo."
    )

    st.write("### 🧠 Arquitectura propuesta por Pablo")
    st.code("""
    # Arquitectura del modelo (Keras)
    model = Sequential([
        Dense(6, activation='relu'),    # Capa oculta 1
        Dense(3, activation='relu'),    # Capa oculta 2
        Dense(1),                       # Capa de salida (lineal)
    ])
    model.compile(optimizer='adam', loss='mae')

    # Entrenamiento
    early_stop = EarlyStopping(patience=15, restore_best_weights=True)
    model.fit(
        X_train, y_train,
        batch_size=20,
        epochs=200,
        validation_data=(X_test, y_test),
        callbacks=[early_stop],
    )
    """, language="python")

    st.write("### ⚠️ Problema detectado: data leakage")
    st.markdown("""
    El notebook original usaba como features **todas las columnas de todos los meses disponibles**:

    ```python
    target_col_names = ['CM Agosto 2023']
    feature_cols_names = [c for c in numeric_cols if c not in target_col_names]
    ```

    El problema es que `numeric_cols` incluye **meses posteriores al target** (Septiembre 2023, Octubre 2023, ..., hasta el último mes del dataset). Es decir, el modelo usa **información del futuro** para predecir el pasado.

    **Consecuencia:** los resultados del notebook se ven muy buenos (R² alto, MAE bajo), pero **no son reproducibles en producción** — al momento de predecir el próximo mes, naturalmente no tenemos los meses siguientes.
    """)

    st.write("### ✅ Cómo se corrigió para la app")
    st.markdown("""
    En el Módulo 3 usamos la **misma arquitectura de Pablo** (`Dense(6,relu) → Dense(3,relu) → Dense(1)`)
    pero cambiamos las features:

    - ❌ **Antes:** columnas de todos los meses (incluyendo futuros).
    - ✅ **Ahora:** lags (valor hace 1, 2, 3 meses), medias móviles, estacionalidad.

    Esto permite que el modelo funcione para **predicciones reales** en escenarios de producción,
    respetando la arquitectura original que Pablo propuso.
    """)

    st.write("### 📊 Comparativa ambos enfoques")
    st.markdown("""
    | Aspecto | Pablo original | Pablo corregido (en esta app) |
    |---------|----------------|--------------------------------|
    | Arquitectura | `Dense(6,relu)→Dense(3,relu)→Dense(1)` | **Idéntica** |
    | Optimizer / Loss | `adam / mae` | **Idénticos** |
    | Batch size / Epochs | `20 / 200` | **Idénticos** |
    | Early Stopping | `patience=15` | **Idéntico** |
    | Features | Columnas de todos los meses (leakage) | Lags + rolling del pasado |
    | Data leakage | ❌ Sí | ✅ No |
    | Uso en producción | ❌ No válido | ✅ Sí |
    """)


# ============================================================================
# TAB 5 — SOBRE LOS MODELOS
# ============================================================================
def _tab_sobre_modelos() -> None:
    st.subheader("ℹ️ Sobre los modelos")

    st.write("### 🔵 LightGBM")
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

    st.write("### 🧠 Red Neuronal (Pablo corregido)")
    st.markdown("""
    **Qué es:** la arquitectura propuesta originalmente por Pablo, aplicada sin data leakage.

    **Arquitectura:**
    ```
    Input → Dense(6, relu) → Dense(3, relu) → Dense(1, linear)
    Optimizer: Adam  |  Loss: MAE  |  Batch: 20  |  Epochs: max 200
    EarlyStopping: patience 15 sobre val_loss
    ```

    **Por qué en general da peor que LightGBM:**
    - Es una red muy chica (~50 parámetros)
    - Las redes neuronales no suelen dominar en datos tabulares
    - Para ganar necesitaríamos una arquitectura mucho más grande + más regularización

    **Por qué la mantenemos:**
    - Respeta el trabajo original de Pablo
    - Sirve como baseline de comparación
    - Permite explorar cómo escalan arquitecturas distintas con los mismos datos
    """)

    st.write("### 🎯 Entrenamiento")
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
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.caption(
        "💡 **Tip:** los modelos se re-entrenan corriendo `entrenar_modelos.ipynb` "
        "en Google Colab con los datos más recientes y subiendo el ZIP resultante al repo."
    )
