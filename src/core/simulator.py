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
def _dedup_vigencia(df_valores: pd.DataFrame, keys: list[str] | None = None) -> pd.DataFrame:
    """
    Deja UNA tarifa por clave de merge: la de la vigencia más reciente.

    El tarifario ('valores') tiene histórico: varias filas 'Mes Vigencia' por
    prestación. Como el merge NO une por mes, sin esto cada fila de consumo
    matchearía todas las vigencias -> producto cartesiano -> Consumo Ideal/Simulado
    inflados (doble conteo). Tomamos la vigencia más reciente porque la columna de
    interés es "Valor Convenido a HOY" (el valor vigente). Es el mismo criterio
    del proceso real del negocio ("Max Vigencia primeros 1" en sus workbooks).

    NOTA: si en el futuro se quisiera el valor histórico exacto de cada mes de
    consumo, esto debería reemplazarse por un as-of join (vigencia <= mes consumo).
    """
    keys = keys if keys is not None else list(MERGE_KEYS)
    if VALORES_MES_COL not in df_valores.columns:
        return df_valores
    if not set(keys).issubset(df_valores.columns):
        return df_valores

    tmp = df_valores.copy()
    tmp["_vig_dt"] = pd.to_datetime(tmp[VALORES_MES_COL], format="%m-%Y", errors="coerce")
    tmp = (
        tmp.sort_values("_vig_dt", na_position="first")
        .drop_duplicates(subset=keys, keep="last")
        .drop(columns="_vig_dt")
    )
    return tmp


def _merge_una_pasada(
    df_consumo: pd.DataFrame, df_valores: pd.DataFrame, keys: list[str]
) -> pd.DataFrame:
    """Merge inner con el tarifario deduplicado a una vigencia por clave."""
    v = _dedup_vigencia(df_valores, keys)
    return pd.merge(
        df_consumo,
        v,
        on=keys,
        how="inner",
        suffixes=("", "_val"),
        validate="m:1",  # cada clave del tarifario es única tras el dedup
    )


def merge_datasets(df_consumo: pd.DataFrame, df_valores: pd.DataFrame) -> pd.DataFrame:
    """
    Une consumo con valores usando Prestador + Convenio + Prestación,
    degradando a Prestador + Prestación para las filas sin 'Convenio ID'
    (el export CRUDO de consumo no lo trae).

    Soporta datos MIXTOS: cuando la tabla de consumo junta archivos curados
    (con Convenio ID) y exports crudos (Convenio ID NULL), el merge se hace en
    dos pasadas — 3 claves para las filas con convenio, 2 para las que no —
    así las filas crudas no quedan sin tarifa en silencio. En la pasada de 2
    claves, el Convenio ID se completa desde el tarifario matcheado.

    Cada fila de consumo se enriquece con el "Valor Convenido a HOY" del
    tarifario, resolviendo la vigencia más reciente por clave (sin doble
    conteo). Un merge vacío o parcial se reporta vía merge_match_rate().
    """
    keys2 = [k for k in MERGE_KEYS if k != "Convenio ID"]

    def _tiene_convenio(df: pd.DataFrame) -> bool:
        return "Convenio ID" in df.columns and df["Convenio ID"].notna().any()

    # Si algún lado no trae convenio en absoluto -> 2 claves para todo.
    if not (_tiene_convenio(df_consumo) and _tiene_convenio(df_valores)):
        return _merge_una_pasada(df_consumo, df_valores, keys2)

    sin_convenio = df_consumo["Convenio ID"].isna()
    if not sin_convenio.any():
        return _merge_una_pasada(df_consumo, df_valores, list(MERGE_KEYS))

    # Datos mixtos: dos pasadas.
    m1 = _merge_una_pasada(df_consumo[~sin_convenio], df_valores, list(MERGE_KEYS))
    m2 = _merge_una_pasada(df_consumo[sin_convenio], df_valores, keys2)
    if "Convenio ID_val" in m2.columns:
        # Enriquecer las filas crudas con el convenio del tarifario matcheado.
        m2["Convenio ID"] = m2["Convenio ID_val"]
        m2 = m2.drop(columns=["Convenio ID_val"])
    return pd.concat([m1, m2], ignore_index=True)


def merge_match_rate(df_consumo: pd.DataFrame, df_merged: pd.DataFrame) -> float:
    """
    Fracción (0..1) de filas de consumo que encontraron tarifa en el merge.

    El inner join descarta en silencio el consumo sin tarifa: si el tarifario
    es de otro prestador, el resultado puede ser 0 filas sin ningún error.
    Validado con datos reales: un 'valores' de otro prestador dio match 0%.
    La UI usa este número para advertir cuando la cobertura es baja.
    """
    if len(df_consumo) == 0:
        return 0.0
    # Tras el dedup de vigencia el merge es m:1 -> cada fila de df_merged
    # corresponde a exactamente una fila de consumo que matcheó.
    return min(len(df_merged) / len(df_consumo), 1.0)


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
        months: multiplicador de la cantidad. IMPORTANTE: si "Cantidad CM" ya
            es el acumulado de la ventana de liquidación (como en los exports
            del negocio, p.ej. 12 meses), debe ser 1 — con 12 el impacto se
            infla 12x. Validado contra simulaciones reales del negocio:
            months=1 reproduce el "Impacto anual" con desvío 0.0000%.
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
# MÉTRICAS DE NEGOCIACIÓN (réplica del workbook del negocio)
# ============================================================================
def impact_metrics(
    df_sim: pd.DataFrame,
    pauta_pct: float | None = None,
    n_meses: int = 12,
) -> dict:
    """
    Métricas de impacto del proceso de negociación, sobre un escenario simulado.

    Réplica 1:1 de las fórmulas del workbook real de negociación (verificadas
    contra dos simulaciones del negocio con desvío 0.0000%):

        impacto       = Σ Consumo Simulado − Σ Consumo Ideal   (ventana completa)
        impacto_pct   = Σ Simulado / Σ Ideal − 1
        impacto_mensual = impacto / n_meses
        extrapauta    = Σ Simulado − Σ Ideal × (1 + pauta)     (si hay pauta)
        extrapauta_pct = Σ Simulado / (Σ Ideal × (1+pauta)) − 1

    Args:
        df_sim: resultado de apply_simulation (sobre el universo simulable,
            es decir, ya sin las filas "No pauta"/excluidas).
        pauta_pct: % de pauta de referencia autorizado (ej: 2.2). El extrapauta
            mide cuánto excede el escenario a esa pauta. None = no calcular.
        n_meses: meses de la ventana de datos (12 si es la ventana anual del
            negocio) para el impacto mensual.
    """
    total_actual = float(df_sim["Consumo Ideal"].sum())
    total_sim = float(df_sim["Consumo Simulado"].sum())
    impacto = total_sim - total_actual
    n_meses = max(int(n_meses), 1)

    out = {
        "total_actual": total_actual,
        "total_simulado": total_sim,
        "impacto": impacto,
        "impacto_pct": (total_sim / total_actual - 1) if total_actual > 0 else 0.0,
        "impacto_mensual": impacto / n_meses,
    }

    if pauta_pct is not None:
        base_pauta = total_actual * (1 + pauta_pct / 100)
        extrapauta = total_sim - base_pauta
        out["extrapauta"] = extrapauta
        out["extrapauta_pct"] = (total_sim / base_pauta - 1) if base_pauta > 0 else 0.0
        out["extrapauta_mensual"] = extrapauta / n_meses

    return out


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