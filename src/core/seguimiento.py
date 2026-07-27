"""
Seguimiento de pauta por prestación (lógica pura, sin Streamlit).

Reproduce la planilla de seguimiento que usa el negocio para una prestación
puntual de un prestador (p. ej. "Consulta de Guardia" del Hospital Universitario
Austral), mes a mes:

    Inflación (INDEC) · Pauta otorgada · Valor de la prestación ($) · % Prestación

más una columna **Acum** (acumulado del año). Las filas de % se acumulan de forma
COMPUESTA (no se suman): así el acumulado replica el de la planilla real
(verificado contra la tabla de HUA: inflación 14,7% · pauta 12,8% · % prestación
19,8%).

Todas las funciones son puras (entra data, sale data) para poder testearlas sin
levantar la UI.
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd

from core.excel_utils import VALORES_MES_COL, normalize_month_series

VALOR_COL = "Valor Convenido a HOY"

# Nombres de mes en español, en orden, para armar las columnas de la planilla.
MESES_ES_FULL = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def meses_del_anio(anio: int) -> list[str]:
    """Claves canónicas 'MM-YYYY' de los 12 meses de un año, de enero a diciembre."""
    return [f"{m:02d}-{anio}" for m in range(1, 13)]


def acumulado_compuesto(pcts: Iterable[float | None]) -> float | None:
    """
    Acumulado COMPUESTO de una serie de porcentajes mensuales, en % (no fracción).

    Cada valor está en unidades de porcentaje (2,9 = 2,9%). Ignora los meses sin
    dato (None/NaN). Devuelve el % acumulado del período, o None si no hay ningún
    dato.

        acum = (Π (1 + pᵢ/100) − 1) · 100

    Ej: [2,9 · 2,9 · 3,4 · 2,6 · 2,1] -> 14,69% (la planilla real muestra 14,7%).
    """
    vals = [float(p) for p in pcts if p is not None and not pd.isna(p)]
    if not vals:
        return None
    acc = 1.0
    for p in vals:
        acc *= 1 + p / 100.0
    return (acc - 1) * 100.0


def serie_valor_por_mes(
    df_valores: pd.DataFrame, meses: list[str]
) -> list[float | None]:
    """
    Valor de la prestación en cada mes pedido, tomándolo de la vigencia de ESE mes.

    `df_valores` debe venir ya filtrado a un prestador + prestación; usa las
    columnas 'Mes Vigencia' y 'Valor Convenido a HOY'. `meses` son claves
    'MM-YYYY'. Devuelve una lista alineada a `meses`: el valor cuya vigencia cae
    en ese mes, o None si ese mes no tiene vigencia registrada (queda en blanco,
    como en la planilla, para completar a mano).

    Si un mes tuviera más de una fila, se toma la última (criterio del negocio:
    la carga más reciente pisa a la anterior).
    """
    if df_valores is None or len(df_valores) == 0:
        return [None] * len(meses)
    if VALORES_MES_COL not in df_valores.columns or VALOR_COL not in df_valores.columns:
        return [None] * len(meses)

    tmp = df_valores[[VALORES_MES_COL, VALOR_COL]].copy()
    tmp["_k"] = normalize_month_series(tmp[VALORES_MES_COL])
    tmp["_val"] = pd.to_numeric(tmp[VALOR_COL], errors="coerce")
    tmp = tmp.dropna(subset=["_k", "_val"])
    if tmp.empty:
        return [None] * len(meses)

    # Última carga por mes de vigencia.
    mapa = tmp.groupby("_k")["_val"].last().to_dict()
    return [mapa.get(m) for m in meses]


def variacion_mensual(
    serie: list[float | None], base_previa: float | None = None
) -> list[float | None]:
    """
    % de variación mes a mes de una serie de valores ($), en %.

    Para cada mes con valor, calcula el aumento respecto del último valor
    conocido previo (arrastrando por encima de los meses en blanco). `base_previa`
    es el valor del mes anterior al primero de la serie (p. ej. el diciembre del
    año pasado), para poder calcular el % del primer mes. Devuelve una lista del
    mismo largo que `serie`; None donde no hay valor o no hay base positiva.

    Ej: base 26.440,83 → [27.075,41 · 27.725,22 · 29.943,24 · 30.751,71]
        -> [2,40% · 2,40% · 8,00% · 2,70%]  (coincide con la planilla de HUA).
    """
    out: list[float | None] = []
    prev = base_previa
    for v in serie:
        if v is None or pd.isna(v):
            out.append(None)
            continue
        if prev is None or pd.isna(prev) or prev == 0:
            out.append(None)
        else:
            out.append((float(v) / float(prev) - 1) * 100.0)
        prev = float(v)
    return out
