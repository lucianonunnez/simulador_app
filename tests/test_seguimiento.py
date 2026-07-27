"""
Tests de la lógica de seguimiento de pauta por prestación (core.seguimiento).

Blindan las fórmulas de la planilla contra los números reales del seguimiento
del Hospital Universitario Austral (Consulta Guardia): el acumulado compuesto de
inflación (14,7%), pauta otorgada (12,8%) y % prestación (19,8%), y el % mes a
mes derivado del valor de la prestación.

Puros: solo dependen de pandas. Requieren PYTHONPATH=src.
"""

import pandas as pd
import pytest

from core.seguimiento import (
    acumulado_compuesto,
    meses_del_anio,
    serie_valor_por_mes,
    variacion_mensual,
)


# ----------------------------------------------------------------------------
# acumulado_compuesto — replica los "Acum" de la planilla real
# ----------------------------------------------------------------------------
def test_acumulado_compuesto_reproduce_hua():
    # Inflación ene-may: 2,90 · 2,90 · 3,40 · 2,60 · 2,10  -> 14,7%
    infl = [2.90, 2.90, 3.40, 2.60, 2.10]
    assert acumulado_compuesto(infl) == pytest.approx(14.69, abs=0.02)

    # Pauta otorgada: 2,14 · 2,40 · 2,40 · 2,55 · 2,70  -> 12,8%
    pauta = [2.14, 2.40, 2.40, 2.55, 2.70]
    assert acumulado_compuesto(pauta) == pytest.approx(12.80, abs=0.02)

    # % Prestación: 3,00 · 2,40 · 2,40 · 8,00 · 2,70  -> 19,8%
    pct = [3.00, 2.40, 2.40, 8.00, 2.70]
    assert acumulado_compuesto(pct) == pytest.approx(19.79, abs=0.02)


def test_acumulado_compuesto_es_compuesto_no_suma():
    # Si fuera suma daría 4,0; compuesto da 2,02%.
    assert acumulado_compuesto([2.0, 2.0]) == pytest.approx(4.04, abs=1e-6)


def test_acumulado_compuesto_ignora_vacios():
    assert acumulado_compuesto([2.9, None, float("nan"), 2.9]) == pytest.approx(
        acumulado_compuesto([2.9, 2.9]), abs=1e-9
    )
    assert acumulado_compuesto([None, float("nan")]) is None
    assert acumulado_compuesto([]) is None


# ----------------------------------------------------------------------------
# variacion_mensual — % mes a mes del valor de la prestación
# ----------------------------------------------------------------------------
def test_variacion_mensual_reproduce_hua():
    # Valor Consulta Guardia feb-may, con enero (26.440,83) como base previa.
    serie = [27075.41, 27725.22, 29943.24, 30751.71]
    out = variacion_mensual(serie, base_previa=26440.83)
    assert out == pytest.approx([2.40, 2.40, 8.00, 2.70], abs=0.01)


def test_variacion_mensual_sin_base_el_primero_es_none():
    out = variacion_mensual([100.0, 110.0], base_previa=None)
    assert out[0] is None
    assert out[1] == pytest.approx(10.0, abs=1e-9)


def test_variacion_mensual_arrastra_sobre_huecos():
    # Un mes sin valor no rompe: el siguiente compara contra el último conocido.
    out = variacion_mensual([100.0, None, 121.0], base_previa=None)
    assert out[0] is None          # sin base previa
    assert out[1] is None          # mes vacío
    assert out[2] == pytest.approx(21.0, abs=1e-9)   # 121 vs 100 (arrastrado)


# ----------------------------------------------------------------------------
# serie_valor_por_mes — toma el valor de la vigencia de cada mes
# ----------------------------------------------------------------------------
def test_serie_valor_por_mes_mapea_por_vigencia():
    df = pd.DataFrame({
        "Mes Vigencia": ["01-2026", "Marzo 2026"],      # texto es-AR también
        "Valor Convenido a HOY": [100.0, 108.0],
    })
    meses = ["12-2025", "01-2026", "02-2026", "03-2026"]
    out = serie_valor_por_mes(df, meses)
    assert out[0] is None                       # sin vigencia en dic-2025
    assert out[1] == pytest.approx(100.0)       # ene-2026
    assert out[2] is None                       # feb-2026 sin vigencia (queda en blanco)
    assert out[3] == pytest.approx(108.0)       # mar-2026 ("Marzo 2026")


def test_serie_valor_por_mes_toma_ultima_carga_del_mes():
    df = pd.DataFrame({
        "Mes Vigencia": ["05-2026", "05-2026"],
        "Valor Convenido a HOY": [30000.0, 30751.71],   # recarga del mismo mes
    })
    out = serie_valor_por_mes(df, ["05-2026"])
    assert out[0] == pytest.approx(30751.71)


def test_serie_valor_por_mes_sin_columnas_devuelve_none():
    out = serie_valor_por_mes(pd.DataFrame({"otra": [1]}), ["01-2026", "02-2026"])
    assert out == [None, None]


# ----------------------------------------------------------------------------
# meses_del_anio
# ----------------------------------------------------------------------------
def test_meses_del_anio():
    meses = meses_del_anio(2026)
    assert len(meses) == 12
    assert meses[0] == "01-2026"
    assert meses[-1] == "12-2026"
