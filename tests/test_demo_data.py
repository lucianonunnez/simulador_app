"""
Tests del generador de datos sintéticos (scripts/generate_demo_data.py).

El dataset de demo es lo que permite levantar la app sin datos productivos:
tiene que cumplir el mismo contrato de columnas que la ingesta exige y ser
reproducible con la misma semilla.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import generate_demo_data as demo  # noqa: E402
from core import excel_utils as xu  # noqa: E402


def test_cumple_el_contrato_de_columnas():
    consumo, valores = demo.generar(meses=6, n_prestadores=2, seed=1)
    assert not xu.missing_columns(consumo, xu.EXPECTED_CONSUMO_COLS)
    assert not xu.missing_columns(valores, xu.EXPECTED_VALORES_COLS)


def test_clean_dataset_no_descarta_filas():
    consumo, valores = demo.generar(meses=6, n_prestadores=2, seed=1)
    assert len(xu.clean_dataset(consumo.copy(), xu.CONSUMO_NUMERIC_COLS)) == len(consumo)
    assert len(xu.clean_dataset(valores.copy(), xu.VALORES_NUMERIC_COLS)) == len(valores)


def test_es_reproducible_con_la_misma_semilla():
    a, _ = demo.generar(meses=6, n_prestadores=2, seed=7)
    b, _ = demo.generar(meses=6, n_prestadores=2, seed=7)
    pd.testing.assert_frame_equal(a, b)


def test_cada_consumo_tiene_tarifa():
    consumo, valores = demo.generar(meses=12, n_prestadores=3, seed=3)
    clave = ["Prestador ID", "Prestacion ID"]
    con_tarifa = consumo[clave].drop_duplicates().merge(
        valores[clave].drop_duplicates(), how="left", indicator=True
    )
    assert (con_tarifa["_merge"] == "both").all()
