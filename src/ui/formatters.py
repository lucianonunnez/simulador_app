"""Helpers de formato para mostrar números en la UI (localización es-AR)."""

from __future__ import annotations

import pandas as pd


def _es_ar(value: float, decimals: int = 2) -> str:
    """
    Formatea un número al estilo argentino: punto para miles, coma para decimales.

    Python da formato US (`1,234,567.89`); acá lo damos vuelta a `1.234.567,89`.
    """
    us = f"{value:,.{decimals}f}"  # 1,234,567.89
    return us.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def format_currency(value: float) -> str:
    """Moneda abreviada es-AR: $1,20M, $15,30 mil, $234,50"""
    if pd.isna(value) or value == 0:
        return "$0,00"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1_000_000:
        return f"{sign}${_es_ar(abs_val / 1_000_000)}M"
    if abs_val >= 1_000:
        return f"{sign}${_es_ar(abs_val / 1_000)} mil"
    return f"{sign}${_es_ar(abs_val)}"


def format_currency_full(value: float) -> str:
    """Moneda completa es-AR: $1.234.567,89"""
    if pd.isna(value) or value == 0:
        return "$0,00"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    return f"{sign}${_es_ar(abs_val)}"


def format_quantity(value: float) -> str:
    """Cantidad es-AR: 1.234,56"""
    if pd.isna(value) or value == 0:
        return "0,00"
    return _es_ar(value)


def format_int(value: float) -> str:
    """Entero es-AR: 1.234.567 (para contadores de filas/registros)."""
    if pd.isna(value):
        return "0"
    return _es_ar(float(value), decimals=0)


def safe_pct(num: float, den: float) -> float | None:
    """
    num / den * 100, o None si el denominador es 0/NaN.

    Evita que aparezcan 'inf%' o 'nan%' en pantalla cuando una base es cero
    (ej: error % contra un valor real que ese mes fue 0).
    """
    if den is None or pd.isna(den) or den == 0 or num is None or pd.isna(num):
        return None
    return float(num) / float(den) * 100
