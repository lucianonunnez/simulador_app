"""
Lógica pura del simulador de aumentos.

Sin dependencias de Streamlit. Todas las funciones son puras:
entra un DataFrame y unos parámetros, sale otro DataFrame con las columnas nuevas.

Esto permite:
- Testear las funciones sin levantar la UI.
- Reusarlas desde otros módulos (ej: Módulo 3 de ML puede usar merge_datasets).
"""

from __future__ import annotations

from typing import Dict, Literal

import numpy as np
import pandas as pd


MERGE_KEYS = ["Prestador ID", "Convenio ID", "Prestacion ID"]

# Columna de vigencia del tarifario (histórico de tarifas por prestación).
VALORES_MES_COL = "Mes Vigencia"


# ============================================================================
# NORMALIZACIÓN
# ============================================================================
def normalize_dataframes(
    df_consumo: pd.DataFrame, df_valores: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Normaliza tipos de datos en las claves de merge y columnas numéricas.
    Devuelve copias, no modifica los originales.
    """
    df_consumo = df_consumo.copy()
    df_valores = df_valores.copy()

    # Claves: forzar a Int64 (permite NaN)
    for col in MERGE_KEYS:
        if col in df_consumo.columns:
            df_consumo[col] = pd.to_numeric(df_consumo[col], errors="coerce").astype("Int64")
        if col in df_valores.columns:
            df_valores[col] = pd.to_numeric(df_valores[col], errors="coerce").astype("Int64")

    # Numéricas
    if "Cantidad CM" in df_consumo.columns:
        df_consumo["Cantidad CM"] = pd.to_numeric(
            df_consumo["Cantidad CM"], errors="coerce"
        ).fillna(0)

    if "Valor Convenido a HOY" in df_valores.columns:
        df_valores["Valor Convenido a HOY"] = pd.to_numeric(
            df_valores["Valor Convenido a HOY"], errors="coerce"
        ).fillna(0)

    return df_consumo, df_valores


# ============================================================================
# MERGE
# ============================================================================
def _dedup_vigencia(df_valores: pd.DataFrame) -> pd.DataFrame:
    """
    Deja UNA tarifa por clave de merge: la de la vigencia más reciente.

    El tarifario ('valores') tiene histórico: varias filas 'Mes Vigencia' por
    prestación. Como el merge NO une por mes, sin esto cada fila de consumo
    matchearía todas las vigencias -> producto cartesiano -> Consumo Ideal/Simulado
    inflados (doble conteo). Tomamos la vigencia más reciente porque la columna de
    interés es "Valor Convenido a HOY" (el valor vigente).

    NOTA: si en el futuro se quisiera el valor histórico exacto de cada mes de
    consumo, esto debería reemplazarse por un as-of join (vigencia <= mes consumo).
    """
    if VALORES_MES_COL not in df_valores.columns:
        return df_valores
    if not set(MERGE_KEYS).issubset(df_valores.columns):
        return df_valores

    tmp = df_valores.copy()
    tmp["_vig_dt"] = pd.to_datetime(tmp[VALORES_MES_COL], format="%m-%Y", errors="coerce")
    tmp = (
        tmp.sort_values("_vig_dt", na_position="first")
        .drop_duplicates(subset=MERGE_KEYS, keep="last")
        .drop(columns="_vig_dt")
    )
    return tmp


def merge_datasets(df_consumo: pd.DataFrame, df_valores: pd.DataFrame) -> pd.DataFrame:
    """
    Une consumo con valores usando Prestador + Convenio + Prestación.

    Cada fila de consumo se enriquece con el "Valor Convenido a HOY" del tarifario.
    Se deduplica el tarifario a una vigencia por clave para evitar doble conteo.
    """
    df_valores = _dedup_vigencia(df_valores)

    df_merged = pd.merge(
        df_consumo,
        df_valores,
        on=MERGE_KEYS,
        how="inner",
        suffixes=("", "_val"),
        validate="m:1",  # cada clave del tarifario es única tras el dedup
    )

    # Si el merge con 3 claves no dio nada, intentar con clave concatenada
    # (a veces los tipos de datos no matchean aunque semánticamente sean iguales)
    if len(df_merged) == 0:
        c = df_consumo.copy()
        v = df_valores.copy()
        c["_key"] = (
            c["Prestador ID"].astype(str) + "|" +
            c["Convenio ID"].astype(str) + "|" +
            c["Prestacion ID"].astype(str)
        )
        v["_key"] = (
            v["Prestador ID"].astype(str) + "|" +
            v["Convenio ID"].astype(str) + "|" +
            v["Prestacion ID"].astype(str)
        )
        df_merged = pd.merge(c, v, on="_key", how="inner", suffixes=("", "_val"))
        drop_cols = [
            col for col in df_merged.columns
            if col.endswith("_val") and col.replace("_val", "") in MERGE_KEYS
        ]
        df_merged = df_merged.drop(columns=drop_cols + ["_key"], errors="ignore")

    return df_merged


# ============================================================================
# SIMULACIÓN DE AUMENTOS
# ============================================================================
IncreaseMode = Literal["plano", "por_nomenclador", "por_prestacion"]


def apply_simulation(
    df_merged: pd.DataFrame,
    months: int,
    mode: IncreaseMode,
    flat_pct: float = 0.0,
    nomenclador_pcts: Dict[str, float] | None = None,
    prestacion_pcts: Dict[int, float] | None = None,
) -> pd.DataFrame:
    """
    Aplica aumentos y calcula Consumo Ideal vs Simulado.

    Fórmulas:
        Consumo Ideal    = Cantidad CM * Valor Convenido a HOY * meses
        Valor Ofrecido   = Valor Convenido a HOY * (1 + aumento%)
        Consumo Simulado = Cantidad CM * Valor Ofrecido * meses
        % Aumento        = (Valor Ofrecido / Valor Convenido a HOY - 1) * 100

    Args:
        df_merged: resultado de merge_datasets, con columnas Cantidad CM y
            Valor Convenido a HOY.
        months: cantidad de meses a proyectar.
        mode: "plano", "por_nomenclador" o "por_prestacion".
        flat_pct: usado cuando mode="plano".
        nomenclador_pcts: dict {nomenclador: %} cuando mode="por_nomenclador".
        prestacion_pcts: dict {prestacion_id: %} cuando mode="por_prestacion".

    Returns:
        DataFrame con columnas nuevas: Consumo Ideal, Valor Ofrecido,
        Consumo Simulado, % Aumento.
    """
    df = df_merged.copy()

    # Consumo ideal (al valor actual)
    df["Consumo Ideal"] = df["Cantidad CM"] * df["Valor Convenido a HOY"] * months

    # Aplicar aumentos según el modo elegido
    if mode == "plano":
        df["Valor Ofrecido"] = df["Valor Convenido a HOY"] * (1 + flat_pct / 100)

    elif mode == "por_nomenclador":
        df["Valor Ofrecido"] = df["Valor Convenido a HOY"].copy()
        for nom, pct in (nomenclador_pcts or {}).items():
            mask = df["Nomenclador"] == nom
            df.loc[mask, "Valor Ofrecido"] = (
                df.loc[mask, "Valor Convenido a HOY"] * (1 + pct / 100)
            )

    elif mode == "por_prestacion":
        df["Valor Ofrecido"] = df["Valor Convenido a HOY"].copy()
        for pid, pct in (prestacion_pcts or {}).items():
            mask = df["Prestacion ID"] == pid
            df.loc[mask, "Valor Ofrecido"] = (
                df.loc[mask, "Valor Convenido a HOY"] * (1 + pct / 100)
            )
    else:
        raise ValueError(f"Modo desconocido: {mode}")

    # Consumo simulado + % de aumento efectivo
    df["Consumo Simulado"] = df["Cantidad CM"] * df["Valor Ofrecido"] * months

    df["% Aumento"] = np.where(
        df["Valor Convenido a HOY"] > 0,
        (df["Valor Ofrecido"] / df["Valor Convenido a HOY"] - 1) * 100,
        0.0,
    )

    return df


# ============================================================================
# AGREGACIONES PARA LOS TABS
# ============================================================================
def aggregate_top_n(
    df: pd.DataFrame,
    group_col: str,
    value_cols: list[str],
    top_n: int = 25,
    others_label: str = "Otros",
) -> pd.DataFrame:
    """
    Agrupa por `group_col`, se queda con los top_n por la primera value_col,
    y unifica el resto como "Otros".
    """
    grouped = df.groupby(group_col, dropna=False)[value_cols].sum().reset_index()
    grouped = grouped.sort_values(value_cols[0], ascending=False)

    if len(grouped) <= top_n:
        return grouped

    top = grouped.head(top_n)
    rest = grouped.iloc[top_n:]

    otros_row = {group_col: others_label}
    for col in value_cols:
        otros_row[col] = rest[col].sum()

    return pd.concat([top, pd.DataFrame([otros_row])], ignore_index=True)