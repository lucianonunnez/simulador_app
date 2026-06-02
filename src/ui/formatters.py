"""Helpers de formato para mostrar números en la UI."""

from __future__ import annotations

import pandas as pd


def format_currency(value: float) -> str:
    """$1.2M, $15.3k, $234.50"""
    if pd.isna(value) or value == 0:
        return "$0.00"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:.2f}M"
    if abs_val >= 1_000:
        return f"{sign}${abs_val / 1_000:.2f}k"
    return f"{sign}${abs_val:.2f}"


def format_currency_full(value: float) -> str:
    """$1,234,567.89"""
    if pd.isna(value) or value == 0:
        return "$0.00"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    return f"{sign}${abs_val:,.2f}"


def format_quantity(value: float) -> str:
    """1,234.56"""
    if pd.isna(value) or value == 0:
        return "0.00"
    return f"{value:,.2f}"