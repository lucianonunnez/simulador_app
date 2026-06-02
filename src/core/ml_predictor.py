"""
Predictor ML: carga modelos pre-entrenados y genera predicciones.

Maneja 3 métricas × 2 modelos = 6 modelos:
- LightGBM (importe, precio, cantidad) → .txt
- Pablo corregido (importe, precio, cantidad) → .keras + scalers.pkl

La lógica de feature engineering (lags, medias móviles, estacionalidad) se
replica de `preparar_datos.py` que usamos en Colab, para que la app genere
las mismas features que usó el entrenamiento. Sin eso, los modelos
darían basura.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import streamlit as st

from core.logging_config import audit, get_logger

log = get_logger(__name__)

# Imports lazy para que la app no falle si TF no está instalado
_tf = None
_lgb = None


# ============================================================================
# CONSTANTES (deben coincidir con preparar_datos.py del notebook Colab)
# ============================================================================
MODELS_DIR = Path("models")
LAGS = [1, 2, 3]
VENTANAS_MOV = [3, 6]
METRICS = ["importe", "precio", "cantidad"]
MODELS = ["lightgbm", "pablo_corregido"]


# ============================================================================
# CARGA DE MODELOS (con caché)
# ============================================================================
@st.cache_resource(show_spinner="🔵 Cargando LightGBM...")
def load_lightgbm(metric: Literal["importe", "precio", "cantidad"]):
    """Carga un modelo LightGBM entrenado."""
    import lightgbm as lgb
    path = MODELS_DIR / f"lightgbm_{metric}.txt"
    if not path.exists():
        raise FileNotFoundError(f"No se encontró {path}. ¿Subiste los modelos al repo?")
    booster = lgb.Booster(model_file=str(path))
    audit("model_loaded", model="lightgbm", metric=metric)
    return booster


@st.cache_resource(show_spinner="🧠 Cargando red neuronal...")
def load_pablo(metric: Literal["importe", "precio", "cantidad"]):
    """Carga modelo Pablo corregido + sus scalers."""
    from tensorflow.keras.models import load_model

    path_model = MODELS_DIR / f"pablo_corregido_{metric}.keras"
    path_scalers = MODELS_DIR / "scalers_pablo.pkl"

    if not path_model.exists():
        raise FileNotFoundError(f"No se encontró {path_model}")
    if not path_scalers.exists():
        raise FileNotFoundError(f"No se encontró {path_scalers}")

    model = load_model(path_model, compile=False)
    with open(path_scalers, "rb") as f:
        scalers_all = pickle.load(f)
    scalers = scalers_all.get(metric)
    if scalers is None:
        raise ValueError(f"Scalers para métrica '{metric}' no encontrados en pkl")

    return model, scalers["scaler_X"], scalers["scaler_y"]


@st.cache_data(show_spinner="📊 Cargando métricas...")
def load_metricas() -> dict:
    """Carga el JSON de métricas (MAE, R², features, etc.)."""
    path = MODELS_DIR / "metricas_final.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


# ============================================================================
# FEATURE ENGINEERING (debe replicar el de Colab EXACTAMENTE)
# ============================================================================
def compute_target(df: pd.DataFrame, metric: str) -> pd.Series:
    """Calcula la métrica objetivo según el tipo."""
    if metric == "importe":
        return df["Importe CM"]
    elif metric == "cantidad":
        return df["Cantidad CM"]
    elif metric == "precio":
        return np.where(
            df["Cantidad CM"] > 0,
            df["Importe CM"] / df["Cantidad CM"],
            np.nan,
        )
    raise ValueError(f"Métrica desconocida: {metric}")


def construir_panel(df_consumo: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Construye panel Prestador × Prestación × Mes con calendario completo."""
    df = df_consumo.copy()
    df["mes_dt"] = pd.to_datetime(df["Mes"], format="%m-%Y", errors="coerce")
    df = df.dropna(subset=["mes_dt"])
    df["Cantidad CM"] = pd.to_numeric(df["Cantidad CM"], errors="coerce").fillna(0)
    df["Importe CM"] = pd.to_numeric(df["Importe CM"], errors="coerce").fillna(0)
    df["target_raw"] = compute_target(df, metric)

    if metric == "precio":
        df = df.dropna(subset=["target_raw"])
        def wmean(g):
            w = g["Cantidad CM"]
            return (g["target_raw"] * w).sum() / w.sum() if w.sum() > 0 else g["target_raw"].mean()
        agg = (
            df.groupby(["Prestador ID", "Prestacion ID", "mes_dt"])
            .apply(wmean, include_groups=False)
            .reset_index(name="valor")
        )
    else:
        agg = (
            df.groupby(["Prestador ID", "Prestacion ID", "mes_dt"])["target_raw"]
            .sum()
            .reset_index(name="valor")
        )

    # Rellenar calendario completo
    meses_todos = pd.date_range(start=agg["mes_dt"].min(), end=agg["mes_dt"].max(), freq="MS")
    entidades = agg[["Prestador ID", "Prestacion ID"]].drop_duplicates()
    grid = (
        entidades.assign(key=1)
        .merge(pd.DataFrame({"mes_dt": meses_todos, "key": 1}), on="key")
        .drop(columns="key")
    )
    panel = grid.merge(agg, on=["Prestador ID", "Prestacion ID", "mes_dt"], how="left")
    panel["fue_activo"] = panel["valor"].notna().astype(int)
    panel["valor"] = panel["valor"].fillna(0)

    return panel.sort_values(["Prestador ID", "Prestacion ID", "mes_dt"]).reset_index(drop=True)


def agregar_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Agrega lags, medias móviles, estacionalidad."""
    df = panel.copy()
    g = df.groupby(["Prestador ID", "Prestacion ID"])

    for lag in LAGS:
        df[f"lag_{lag}"] = g["valor"].shift(lag)
        df[f"activo_lag_{lag}"] = g["fue_activo"].shift(lag)

    for v in VENTANAS_MOV:
        df[f"rolling_mean_{v}"] = g["valor"].transform(
            lambda s: s.shift(1).rolling(v, min_periods=1).mean()
        )
        df[f"rolling_std_{v}"] = g["valor"].transform(
            lambda s: s.shift(1).rolling(v, min_periods=2).std()
        )

    df["mes_num"] = df["mes_dt"].dt.month
    df["trimestre"] = df["mes_dt"].dt.quarter
    return df


def enriquecer_con_categoricas(df_features: pd.DataFrame, df_consumo: pd.DataFrame) -> pd.DataFrame:
    """Agrega Nomenclador, Tipo Clase CM, Gama tomando la moda por entidad."""
    cats = [c for c in ["Nomenclador", "Tipo Clase CM", "Gama"] if c in df_consumo.columns]
    if not cats:
        return df_features
    modas = (
        df_consumo.groupby(["Prestador ID", "Prestacion ID"])[cats]
        .agg(lambda x: x.mode().iloc[0] if len(x.mode()) > 0 else None)
        .reset_index()
    )
    return df_features.merge(modas, on=["Prestador ID", "Prestacion ID"], how="left")


# ============================================================================
# PREDICCIÓN
# ============================================================================
def predecir_lightgbm(
    df_consumo: pd.DataFrame,
    metric: str,
    filtro_prestador: int = None,
    filtro_prestacion: str = None,
) -> pd.DataFrame:
    """
    Genera predicciones con LightGBM.

    Devuelve un DataFrame con columnas:
        Prestador ID, Prestacion ID, mes_dt, valor_real, prediccion
    """
    model = load_lightgbm(metric)
    metricas = load_metricas().get(f"lightgbm_{metric}", {})
    features = metricas.get("features", [])
    cats = metricas.get("categorical_features", [])

    # Preparar features igual que en entrenamiento
    panel = construir_panel(df_consumo, metric)
    df_feat = agregar_features(panel)
    df_feat = enriquecer_con_categoricas(df_feat, df_consumo)

    # Filtros opcionales
    if filtro_prestador is not None:
        df_feat = df_feat[df_feat["Prestador ID"] == filtro_prestador]
    if filtro_prestacion is not None:
        df_feat = df_feat[df_feat["Prestacion ID"].astype(str) == str(filtro_prestacion)]

    if len(df_feat) == 0:
        return pd.DataFrame()

    # Descartar filas con NaN en features requeridas
    feat_req = [c for c in features if c in df_feat.columns]
    df_feat = df_feat.dropna(subset=[c for c in feat_req if c.startswith("lag_") or c.startswith("rolling_")])

    if len(df_feat) == 0:
        return pd.DataFrame()

    # Convertir categóricas
    for c in cats:
        if c in df_feat.columns:
            df_feat[c] = df_feat[c].astype("category")

    # Alinear columnas: features esperadas
    X = df_feat[[c for c in features if c in df_feat.columns]].copy()

    # Predecir
    y_pred = model.predict(X)

    out = df_feat[["Prestador ID", "Prestacion ID", "mes_dt", "valor"]].copy()
    out = out.rename(columns={"valor": "valor_real"})
    out["prediccion"] = y_pred
    return out.reset_index(drop=True)


def predecir_pablo(
    df_consumo: pd.DataFrame,
    metric: str,
    filtro_prestador: int = None,
    filtro_prestacion: str = None,
) -> pd.DataFrame:
    """Genera predicciones con red neuronal Pablo corregida."""
    model, scaler_X, scaler_y = load_pablo(metric)
    metricas = load_metricas().get(f"pablo_corregido_{metric}", {})
    features = metricas.get("features", [])

    panel = construir_panel(df_consumo, metric)
    df_feat = agregar_features(panel)
    df_feat = enriquecer_con_categoricas(df_feat, df_consumo)

    if filtro_prestador is not None:
        df_feat = df_feat[df_feat["Prestador ID"] == filtro_prestador]
    if filtro_prestacion is not None:
        df_feat = df_feat[df_feat["Prestacion ID"].astype(str) == str(filtro_prestacion)]

    if len(df_feat) == 0:
        return pd.DataFrame()

    # Descartar NaN en lags/rolling
    lag_cols = [c for c in df_feat.columns if c.startswith("lag_") or c.startswith("rolling_")]
    df_feat = df_feat.dropna(subset=lag_cols)

    if len(df_feat) == 0:
        return pd.DataFrame()

    # Pablo usa one-hot de categóricas (como en el notebook)
    cats = [c for c in ["Nomenclador", "Tipo Clase CM", "Gama"] if c in df_feat.columns]
    num = [c for c in df_feat.columns if c not in cats + ["Prestador ID", "Prestacion ID", "mes_dt", "valor"]]

    if cats:
        dummies = pd.get_dummies(df_feat[cats], prefix=cats, dummy_na=True)
        X = pd.concat([
            df_feat[num].reset_index(drop=True),
            dummies.reset_index(drop=True),
        ], axis=1)
    else:
        X = df_feat[num].copy().reset_index(drop=True)

    # Alinear con features originales del entrenamiento
    X = X.reindex(columns=features, fill_value=0).fillna(0)

    # Scale, predecir, unscale
    X_scaled = scaler_X.transform(X)
    y_pred_scaled = model.predict(X_scaled, verbose=0)
    y_pred = scaler_y.inverse_transform(y_pred_scaled).ravel()

    out = df_feat[["Prestador ID", "Prestacion ID", "mes_dt", "valor"]].copy().reset_index(drop=True)
    out = out.rename(columns={"valor": "valor_real"})
    out["prediccion"] = y_pred
    return out


# ============================================================================
# FEATURE IMPORTANCE (solo LightGBM lo soporta)
# ============================================================================
def get_feature_importance(metric: str, top_n: int = 15) -> pd.DataFrame:
    """Devuelve DataFrame con feature importance de LightGBM."""
    try:
        model = load_lightgbm(metric)
    except FileNotFoundError:
        return pd.DataFrame()

    importance = model.feature_importance(importance_type="gain")
    names = model.feature_name()
    df = pd.DataFrame({"feature": names, "importance": importance})
    df = df.sort_values("importance", ascending=False).head(top_n)
    return df.reset_index(drop=True)


# ============================================================================
# UTILIDADES
# ============================================================================
def modelos_disponibles() -> dict[str, bool]:
    """Chequea qué modelos están presentes en disco."""
    status = {}
    for m in MODELS:
        for metric in METRICS:
            key = f"{m}_{metric}"
            if m == "lightgbm":
                path = MODELS_DIR / f"lightgbm_{metric}.txt"
            else:
                path = MODELS_DIR / f"pablo_corregido_{metric}.keras"
            status[key] = path.exists()

    # Scalers para Pablo
    status["scalers_pablo"] = (MODELS_DIR / "scalers_pablo.pkl").exists()
    return status