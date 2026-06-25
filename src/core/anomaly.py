"""
Detección de desvíos y anomalías en costos médicos.

Métodos disponibles (todos estadísticos en este hito):

TEMPORAL (vs histórica propia):
    * z_score:  Z-score con ventana móvil.
    * iqr:      Rango intercuartílico con ventana móvil.

ESTRUCTURAL (vs pares comparables):
    * percentile: ¿En qué percentil queda este valor vs sus pares?
    * z_score_cross: Z-score vs la distribución de pares del mismo mes.

El módulo es puro (sin Streamlit). Recibe DataFrames y devuelve DataFrames
con columnas adicionales que marcan si cada registro es anómalo.

Diseñado para ser extendido con métodos ML en el Hito 5.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


# ============================================================================
# TIPOS
# ============================================================================
AnalysisType = Literal["temporal", "estructural", "ambos"]
Metric = Literal["precio_unitario", "importe_total", "cantidad"]
TemporalMethod = Literal["z_score", "iqr"]
StructuralMethod = Literal["percentile", "z_score_cross"]


# ============================================================================
# PREPARACIÓN DE DATOS
# ============================================================================
def compute_metric(df: pd.DataFrame, metric: Metric) -> pd.Series:
    """
    Calcula la serie de la métrica elegida.

    - precio_unitario = Importe CM / Cantidad CM
    - importe_total = Importe CM
    - cantidad = Cantidad CM
    """
    if metric == "precio_unitario":
        # Evita división por cero. Filas con Cantidad=0 → NaN (se ignoran después).
        return np.where(
            df["Cantidad CM"] > 0,
            df["Importe CM"] / df["Cantidad CM"],
            np.nan,
        )
    elif metric == "importe_total":
        return df["Importe CM"].values
    elif metric == "cantidad":
        return df["Cantidad CM"].values
    else:
        raise ValueError(f"Métrica desconocida: {metric}")


def parse_month(mes_str: pd.Series) -> pd.Series:
    """
    Convierte la columna 'Mes' a datetime para ordenar.

    Delega en normalize_month_series (excel_utils), el parser único de meses
    de la app: tolera 'MM-YYYY', nombres de mes en español ('Mayo 2026', como
    vienen los exports crudos) y datetimes.
    """
    from core.excel_utils import normalize_month_series

    return pd.to_datetime(
        normalize_month_series(mes_str), format="%m-%Y", errors="coerce"
    )


def build_time_series(
    df: pd.DataFrame,
    group_cols: list[str],
    metric: Metric,
    aggfunc: str = "sum",
) -> pd.DataFrame:
    """
    Construye una serie temporal agregada por `group_cols` + Mes.

    Para precio_unitario usa aggfunc='mean' forzosamente (promedio ponderado).
    Para importe_total y cantidad usa el aggfunc pasado (default 'sum').

    Returns:
        DataFrame con columnas [*group_cols, 'Mes', 'mes_dt', 'valor']
    """
    df = df.copy()
    df["mes_dt"] = parse_month(df["Mes"])
    df["__metric__"] = compute_metric(df, metric)

    # Saca filas con NaN en la métrica (ej: cantidad = 0 con precio unitario)
    df = df.dropna(subset=["__metric__"])

    # Para precio unitario usamos media ponderada por cantidad (más realista)
    if metric == "precio_unitario":
        def weighted_mean(group):
            weights = group["Cantidad CM"]
            if weights.sum() == 0:
                return group["__metric__"].mean()
            return (group["__metric__"] * weights).sum() / weights.sum()

        agg = (
            df.groupby(group_cols + ["Mes", "mes_dt"], dropna=False)
            .apply(weighted_mean, include_groups=False)
            .reset_index(name="valor")
        )
    else:
        agg = (
            df.groupby(group_cols + ["Mes", "mes_dt"], dropna=False)["__metric__"]
            .agg(aggfunc)
            .reset_index(name="valor")
        )

    return agg.sort_values(group_cols + ["mes_dt"]).reset_index(drop=True)


# ============================================================================
# DETECCIÓN TEMPORAL
# ============================================================================
def detect_temporal_anomalies(
    ts: pd.DataFrame,
    group_cols: list[str],
    method: TemporalMethod = "z_score",
    window: int = 6,
    threshold: float = 2.0,
) -> pd.DataFrame:
    """
    Detecta desvíos temporales: el valor actual es "raro" vs la historia propia.

    Args:
        ts: DataFrame de build_time_series (tiene columnas group_cols, 'mes_dt', 'valor')
        group_cols: columnas que definen la entidad (ej: ['Prestador ID'])
        method: 'z_score' o 'iqr'
        window: cantidad de meses de historia a considerar
        threshold:
            * Para z_score: cantidad de desvíos estándar (típico 2 o 3)
            * Para iqr: multiplicador del IQR (típico 1.5)

    Returns:
        El mismo DataFrame + columnas:
            * media_movil, std_movil (solo z_score)
            * q1_movil, q3_movil (solo iqr)
            * z_score o iqr_ratio
            * is_anomaly_temporal (bool)
            * severidad_temporal (float, |z_score| o ratio en iqr)
    """
    result = ts.copy().sort_values(group_cols + ["mes_dt"]).reset_index(drop=True)

    if method == "z_score":
        # Rolling por grupo: media y std de los últimos `window` meses
        # min_periods=3 evita calcular con muy pocos datos
        result["media_movil"] = result.groupby(group_cols)["valor"].transform(
            lambda s: s.rolling(window, min_periods=3).mean().shift(1)
        )
        result["std_movil"] = result.groupby(group_cols)["valor"].transform(
            lambda s: s.rolling(window, min_periods=3).std().shift(1)
        )

        # Z-score: cuántos desvíos está lejos de la media histórica
        result["z_score"] = (result["valor"] - result["media_movil"]) / result["std_movil"]
        result["z_score"] = result["z_score"].replace([np.inf, -np.inf], np.nan)

        result["is_anomaly_temporal"] = result["z_score"].abs() >= threshold
        result["severidad_temporal"] = result["z_score"].abs()

    elif method == "iqr":
        result["q1_movil"] = result.groupby(group_cols)["valor"].transform(
            lambda s: s.rolling(window, min_periods=3).quantile(0.25).shift(1)
        )
        result["q3_movil"] = result.groupby(group_cols)["valor"].transform(
            lambda s: s.rolling(window, min_periods=3).quantile(0.75).shift(1)
        )
        iqr = result["q3_movil"] - result["q1_movil"]

        lower = result["q1_movil"] - threshold * iqr
        upper = result["q3_movil"] + threshold * iqr

        result["iqr_ratio"] = np.where(
            result["valor"] > upper,
            (result["valor"] - upper) / iqr.replace(0, np.nan),
            np.where(
                result["valor"] < lower,
                (lower - result["valor"]) / iqr.replace(0, np.nan),
                0,
            ),
        )

        result["is_anomaly_temporal"] = (result["valor"] < lower) | (result["valor"] > upper)
        result["severidad_temporal"] = result["iqr_ratio"].abs()

    return result


# ============================================================================
# DETECCIÓN ESTRUCTURAL
# ============================================================================
def detect_structural_anomalies(
    df: pd.DataFrame,
    peer_group_cols: list[str],
    method: StructuralMethod = "percentile",
    threshold: float | None = None,
    metric: Metric = "precio_unitario",
) -> pd.DataFrame:
    """
    Detecta desvíos estructurales: este registro es raro vs sus pares comparables.

    "Pares" = filas que comparten peer_group_cols. Ej: si peer_group_cols=['Prestacion ID', 'Mes'],
    comparás los prestadores que cobraron la misma prestación el mismo mes.

    Args:
        df: DataFrame de consumo enriquecido
        peer_group_cols: columnas que definen "el grupo de pares". Ej:
            ['Prestacion ID', 'Mes'] para comparar prestadores entre sí.
        method: 'percentile' o 'z_score_cross'
        threshold:
            * percentile: para método 'percentile', los valores sobre este percentil
              (ej 90 = top 10%) se marcan. Para el lado bajo, se usa 100-threshold.
            * z_score_cross: cantidad de desvíos respecto de la media del grupo.
        metric: la métrica sobre la que operar

    Returns:
        DataFrame con columnas:
            * __metric__, valor_grupo (media del grupo), desvio_vs_grupo
            * is_anomaly_structural (bool)
            * severidad_structural (float)
    """
    # Default por método: un umbral pensado para z-score (2-3) aplicado al
    # método percentil marcaría ~100% de los registros como anómalos.
    if threshold is None:
        threshold = 95.0 if method == "percentile" else 2.0
    if method == "percentile" and not (50.0 <= threshold <= 100.0):
        raise ValueError(
            f"Para method='percentile' el threshold es un percentil en [50, 100] "
            f"(recibido: {threshold}). ¿Pasaste un umbral de z-score?"
        )

    result = df.copy()
    result["__metric__"] = compute_metric(result, metric)
    result = result.dropna(subset=["__metric__"])

    if method == "percentile":
        # Para cada grupo de pares, calcular percentil del valor actual
        def pct_rank(s):
            return s.rank(pct=True) * 100

        result["percentil_grupo"] = result.groupby(peer_group_cols)["__metric__"].transform(pct_rank)

        # Marca como anómalo si queda en los extremos (top o bottom)
        result["is_anomaly_structural"] = (
            (result["percentil_grupo"] >= threshold) |
            (result["percentil_grupo"] <= (100 - threshold))
        )

        # Severidad: cuánto se aleja del centro (50%)
        result["severidad_structural"] = (result["percentil_grupo"] - 50).abs() / 50

    elif method == "z_score_cross":
        # Media y std del grupo de pares (cross-section, no temporal)
        result["media_grupo"] = result.groupby(peer_group_cols)["__metric__"].transform("mean")
        result["std_grupo"] = result.groupby(peer_group_cols)["__metric__"].transform("std")
        # std == 0 (grupos de un solo elemento) → NaN para evitar división por cero
        result["std_grupo"] = result["std_grupo"].replace(0, np.nan)

        result["z_score_cross"] = (
            (result["__metric__"] - result["media_grupo"]) / result["std_grupo"]
        ).replace([np.inf, -np.inf], np.nan)

        result["is_anomaly_structural"] = result["z_score_cross"].abs() >= threshold
        result["severidad_structural"] = result["z_score_cross"].abs()

    return result


# ============================================================================
# RANKING DE ALERTAS
# ============================================================================
def build_alerts_ranking(
    ts_with_anomalies: pd.DataFrame,
    entity_cols: list[str],
    last_month_only: bool = True,
    top_n: int = 50,
) -> pd.DataFrame:
    """
    Construye un ranking de alertas ordenadas por severidad.

    Args:
        ts_with_anomalies: serie temporal con columna 'is_anomaly_temporal' y 'severidad_temporal'
        entity_cols: columnas que identifican la entidad (ej: ['Prestador Desc', 'Prestacion Desc'])
        last_month_only: si True, solo muestra alertas del último mes disponible
        top_n: cantidad máxima de alertas a devolver

    Returns:
        DataFrame ordenado por severidad descendente.
    """
    anomalies = ts_with_anomalies[ts_with_anomalies["is_anomaly_temporal"] == True].copy()

    if last_month_only and len(anomalies) > 0:
        last_month = anomalies["mes_dt"].max()
        anomalies = anomalies[anomalies["mes_dt"] == last_month]

    anomalies = anomalies.sort_values("severidad_temporal", ascending=False)
    return anomalies.head(top_n).reset_index(drop=True)