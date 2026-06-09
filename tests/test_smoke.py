"""
Smoke tests de la lógica de cálculo pura (sin Streamlit).

Objetivo: blindar las fórmulas centrales para que cualquier cambio futuro que
las altere falle en CI. Es un punto de partida deliberadamente chico —
ampliar agregando casos por módulo.

Los módulos bajo prueba (core.simulator, core.anomaly, ui.formatters) son puros
y solo dependen de pandas/numpy, así que estos tests corren sin TensorFlow ni
el resto del stack pesado. Requieren PYTHONPATH=src (lo fija el hook de inicio
y el workflow de CI).
"""

import numpy as np
import pandas as pd
import pytest

from core.anomaly import compute_metric
from core.simulator import apply_simulation, merge_datasets
from ui.formatters import format_currency, format_currency_full


# ----------------------------------------------------------------------------
# core.simulator
# ----------------------------------------------------------------------------
def test_merge_datasets_une_por_claves():
    consumo = pd.DataFrame({
        "Prestador ID": [1], "Convenio ID": [10], "Prestacion ID": [100],
        "Cantidad CM": [3],
    })
    valores = pd.DataFrame({
        "Prestador ID": [1], "Convenio ID": [10], "Prestacion ID": [100],
        "Valor Convenido a HOY": [50.0],
    })
    merged = merge_datasets(consumo, valores)
    assert len(merged) == 1
    assert merged.loc[0, "Valor Convenido a HOY"] == 50.0


def test_apply_simulation_aumento_plano():
    df = pd.DataFrame({
        "Prestador ID": [1], "Convenio ID": [10], "Prestacion ID": [100],
        "Nomenclador": ["A"], "Cantidad CM": [2], "Valor Convenido a HOY": [100.0],
    })
    out = apply_simulation(df, months=1, mode="plano", flat_pct=10.0)
    # Ideal = 2 * 100 * 1 = 200 ; Simulado con +10% = 2 * 110 * 1 = 220
    assert out.loc[0, "Consumo Ideal"] == pytest.approx(200.0)
    assert out.loc[0, "Valor Ofrecido"] == pytest.approx(110.0)
    assert out.loc[0, "Consumo Simulado"] == pytest.approx(220.0)
    assert out.loc[0, "% Aumento"] == pytest.approx(10.0)


# ----------------------------------------------------------------------------
# core.anomaly
# ----------------------------------------------------------------------------
def test_compute_metric_precio_unitario_evita_division_por_cero():
    df = pd.DataFrame({"Importe CM": [100.0, 50.0], "Cantidad CM": [4, 0]})
    precio = compute_metric(df, "precio_unitario")
    assert precio[0] == 25.0          # 100 / 4
    assert np.isnan(precio[1])        # cantidad 0 -> NaN, no excepción


# ----------------------------------------------------------------------------
# ui.formatters
# ----------------------------------------------------------------------------
def test_format_currency_abreviado():
    assert format_currency(0) == "$0.00"
    assert format_currency(1_500) == "$1.50k"
    assert format_currency(2_000_000) == "$2.00M"
    assert format_currency(-2_000_000) == "-$2.00M"


def test_format_currency_full_con_separadores():
    assert format_currency_full(1_234_567.89) == "$1,234,567.89"
