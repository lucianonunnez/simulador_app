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
from core.excel_utils import (
    CONSUMO_NUMERIC_COLS,
    clean_dataset,
    normalize_month_series,
    to_numeric_tolerante,
)
from core.ml_predictor import _is_usable_model_file
from core.simulator import apply_simulation, merge_datasets
from ui.formatters import format_currency, format_currency_full, format_quantity


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


def test_merge_no_duplica_por_multiples_vigencias():
    """Regresión del fan-out: varias 'Mes Vigencia' por clave NO deben duplicar
    el consumo; se toma la vigencia más reciente."""
    consumo = pd.DataFrame({
        "Prestador ID": [1], "Convenio ID": [10], "Prestacion ID": [100],
        "Cantidad CM": [3],
    })
    valores = pd.DataFrame({
        "Prestador ID": [1, 1, 1],
        "Convenio ID": [10, 10, 10],
        "Prestacion ID": [100, 100, 100],
        "Mes Vigencia": ["01-2024", "06-2024", "03-2024"],
        "Valor Convenido a HOY": [50.0, 90.0, 70.0],
    })
    merged = merge_datasets(consumo, valores)
    assert len(merged) == 1                                   # no fan-out
    assert merged.loc[0, "Valor Convenido a HOY"] == 90.0     # 06-2024 es la más reciente


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
# ui.formatters (localización es-AR: miles con '.', decimales con ',')
# ----------------------------------------------------------------------------
def test_format_currency_abreviado():
    assert format_currency(0) == "$0,00"
    assert format_currency(1_500) == "$1,50 mil"
    assert format_currency(2_000_000) == "$2,00M"
    assert format_currency(-2_000_000) == "-$2,00M"


def test_format_currency_full_es_ar():
    assert format_currency_full(1_234_567.89) == "$1.234.567,89"
    assert format_currency_full(0) == "$0,00"


def test_format_quantity_es_ar():
    assert format_quantity(1_234.56) == "1.234,56"


# ----------------------------------------------------------------------------
# core.excel_utils — normalización de mes (evita duplicar períodos)
# ----------------------------------------------------------------------------
def test_normalize_month_series_unifica_formatos():
    s = pd.Series(["01-2025", pd.Timestamp("2025-01-15"), "2025-01-31"])
    out = normalize_month_series(s)
    # Las tres representan enero 2025 -> mismo canónico 'MM-YYYY'
    assert list(out) == ["01-2025", "01-2025", "01-2025"]


def test_clean_dataset_normaliza_mes():
    df = pd.DataFrame({
        "Prestador ID": [1, 2],
        "Mes": [pd.Timestamp("2025-03-01"), "03-2025"],
        "Cantidad CM": [5, 7],
    })
    out = clean_dataset(df, CONSUMO_NUMERIC_COLS)
    assert list(out["Mes"]) == ["03-2025", "03-2025"]


def test_normalize_month_series_meses_en_espanol():
    """Los exports reales traen 'Mes Vigencia' como nombre de mes en español."""
    s = pd.Series(["Mayo 2026", "Diciembre 2024", "dic. 2025", "Enero de 2024"])
    out = normalize_month_series(s)
    assert list(out) == ["05-2026", "12-2024", "12-2025", "01-2024"]


def test_to_numeric_tolerante_formato_microstrategy():
    """Números como texto con coma de miles y espacios (formato US del export)."""
    s = pd.Series(["1,130 ", "23,653", "8,206.90", "-", "texto", 42])
    out = to_numeric_tolerante(s)
    assert out[0] == 1130
    assert out[1] == 23653
    assert out[2] == pytest.approx(8206.90)
    assert pd.isna(out[3])   # '-' es vacío, no número
    assert pd.isna(out[4])
    assert out[5] == 42


def test_clean_dataset_ids_con_coma_de_miles_no_pierden_filas():
    """Regresión: 'Prestador ID' = '1,130 ' como texto no debe volverse NaN
    (antes to_numeric directo lo descartaba junto con toda la fila)."""
    df = pd.DataFrame({
        "Prestador ID": ["1,130 ", "Total"],
        "Mes": ["01-2025", None],
        "Cantidad CM": ["23,653 ", "99"],
    })
    out = clean_dataset(df, CONSUMO_NUMERIC_COLS)
    # La fila real sobrevive con ID numérico; la fila 'Total' se descarta.
    assert len(out) == 1
    assert out.loc[0, "Prestador ID"] == 1130
    assert out.loc[0, "Cantidad CM"] == 23653


# ----------------------------------------------------------------------------
# core.ml_predictor — health-check de modelos (puntero LFS vs archivo real)
# ----------------------------------------------------------------------------
def test_is_usable_model_file_detecta_puntero_lfs(tmp_path):
    pointer = tmp_path / "modelo.pkl"
    pointer.write_text(
        "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 10077\n"
    )
    real = tmp_path / "real.txt"
    real.write_bytes(b"contenido binario real del modelo")
    missing = tmp_path / "no_existe.keras"

    assert _is_usable_model_file(pointer) is False
    assert _is_usable_model_file(real) is True
    assert _is_usable_model_file(missing) is False
