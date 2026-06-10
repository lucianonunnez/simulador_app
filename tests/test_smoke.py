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

from core import ratelimit
from core.anomaly import compute_metric, detect_structural_anomalies, parse_month
from core.cachekeys import df_fingerprint
from core.excel_utils import (
    CONSUMO_NUMERIC_COLS,
    EXPECTED_VALORES_COLS,
    clean_dataset,
    load_excel_smart,
    normalize_month_series,
    normalize_mstr_columns,
    to_numeric_tolerante,
)
from core.ml_predictor import _is_usable_model_file
from core.simulator import (
    apply_simulation,
    impact_metrics,
    merge_coverage,
    merge_datasets,
    merge_match_rate,
)
from ui.formatters import (
    format_currency,
    format_currency_full,
    format_quantity,
    safe_pct,
)


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
def test_merge_degrada_a_dos_claves_sin_convenio_id():
    """El export crudo de consumo no trae 'Convenio ID': el merge debe degradar
    a Prestador + Prestación, resolviendo la vigencia más reciente (sin fan-out
    aunque el tarifario tenga la misma prestación en dos convenios)."""
    consumo = pd.DataFrame({
        "Prestador ID": [1130], "Convenio ID": [pd.NA],
        "Prestacion ID": [100], "Cantidad CM": [10],
    })
    valores = pd.DataFrame({
        "Prestador ID": [1130, 1130],
        "Convenio ID": [1, 2],            # misma prestación en dos convenios
        "Prestacion ID": [100, 100],
        "Mes Vigencia": ["01-2025", "06-2025"],
        "Valor Convenido a HOY": [80.0, 90.0],
    })
    merged = merge_datasets(consumo, valores)
    assert len(merged) == 1                                  # sin fan-out
    assert merged.loc[0, "Valor Convenido a HOY"] == 90.0    # vigencia más reciente


def test_merge_mixto_xlsx_curado_mas_export_crudo():
    """El caso real del usuario: la tabla de consumo junta archivos curados
    (con Convenio ID) y exports crudos (Convenio ID NULL). Ambos tipos de fila
    deben encontrar tarifa (dos pasadas), sin fan-out, y la fila cruda hereda
    el convenio del tarifario."""
    consumo = pd.DataFrame({
        "Prestador ID": [1130, 1130],
        "Convenio ID": [7, pd.NA],          # curada / cruda
        "Prestacion ID": [100, 100],
        "Cantidad CM": [3, 5],
    })
    valores = pd.DataFrame({
        "Prestador ID": [1130, 1130],
        "Convenio ID": [7, 7],
        "Prestacion ID": [100, 100],
        "Mes Vigencia": ["01-2025", "06-2025"],
        "Valor Convenido a HOY": [80.0, 90.0],
    })
    merged = merge_datasets(consumo, valores)
    assert len(merged) == 2                                   # ambas filas con tarifa
    assert (merged["Valor Convenido a HOY"] == 90.0).all()    # vigencia más reciente
    assert merged["Convenio ID"].notna().all()                # la cruda heredó el convenio
    assert "Convenio ID_val" not in merged.columns


def test_impact_metrics_formulas_del_workbook():
    """Réplica de la cabecera del workbook de negociación: con aumento plano,
    Impacto % == % aplicado, mensual = total / n_meses, y Extrapauta mide el
    exceso sobre la pauta de referencia."""
    df = pd.DataFrame({
        "Prestador ID": [1, 1], "Convenio ID": [1, 1], "Prestacion ID": [10, 20],
        "Nomenclador": ["A", "A"], "Cantidad CM": [10, 5],
        "Valor Convenido a HOY": [100.0, 200.0],
    })
    sim = apply_simulation(df, months=1, mode="plano", flat_pct=2.9)
    m = impact_metrics(sim, pauta_pct=2.2, n_meses=12)

    # Σ Ideal = 10*100 + 5*200 = 2000
    assert m["total_actual"] == pytest.approx(2000.0)
    assert m["impacto_pct"] == pytest.approx(0.029)              # = % aplicado
    assert m["impacto"] == pytest.approx(2000 * 0.029)           # 58.0
    assert m["impacto_mensual"] == pytest.approx(m["impacto"] / 12)
    # Extrapauta = Σ Sim − Σ Ideal × (1 + pauta) = 2058 − 2044 = 14
    assert m["extrapauta"] == pytest.approx(2058.0 - 2044.0)
    assert m["extrapauta_pct"] == pytest.approx(2058.0 / 2044.0 - 1)


def test_merge_match_rate_detecta_tarifario_ajeno():
    """Un tarifario de OTRO prestador da merge vacío: el match-rate debe ser 0
    (validado con exports reales, donde fallaba en silencio)."""
    consumo = pd.DataFrame({
        "Prestador ID": [1130, 1130], "Convenio ID": [1, 1],
        "Prestacion ID": [10, 20], "Cantidad CM": [5, 3],
    })
    valores_ajeno = pd.DataFrame({
        "Prestador ID": [99785], "Convenio ID": [1],
        "Prestacion ID": [10], "Valor Convenido a HOY": [100.0],
    })
    merged = merge_datasets(consumo, valores_ajeno)
    assert merge_match_rate(consumo, merged) == 0.0

    # Cobertura parcial: solo una de dos prestaciones tiene tarifa
    valores_propio = valores_ajeno.assign(**{"Prestador ID": [1130]})
    merged = merge_datasets(consumo, valores_propio)
    assert merge_match_rate(consumo, merged) == pytest.approx(0.5)


def test_merge_coverage_por_importe_no_se_enmascara():
    """Hallazgo de la base real: 98% de filas con tarifa pero solo 73% del
    dinero. La cobertura por importe debe revelar lo que la de filas oculta."""
    consumo = pd.DataFrame({
        "Prestador ID": [1, 1], "Convenio ID": [1, 1],
        "Prestacion ID": [10, 20], "Cantidad CM": [5, 1],
        "Importe CM": [100.0, 900.0],          # la fila SIN tarifa concentra el 90%
    })
    valores = pd.DataFrame({
        "Prestador ID": [1], "Convenio ID": [1],
        "Prestacion ID": [10], "Valor Convenido a HOY": [20.0],
    })
    merged = merge_datasets(consumo, valores)
    cob = merge_coverage(consumo, merged)
    assert cob["filas"] == pytest.approx(0.5)          # 1 de 2 filas
    assert cob["importe"] == pytest.approx(0.1)        # pero solo 10% de la plata
    assert cob["importe_sin_tarifa"] == pytest.approx(900.0)


def test_dedup_vigencia_con_meses_en_espanol():
    """Hallazgo de la base real: 80% de las vigencias son texto en español
    ("Septiembre 2024") y caían a NaT -> la 'vigencia más reciente' quedaba
    arbitraria. El dedup debe resolverlas con el parser único."""
    consumo = pd.DataFrame({
        "Prestador ID": [1], "Convenio ID": [1],
        "Prestacion ID": [10], "Cantidad CM": [2],
    })
    valores = pd.DataFrame({
        "Prestador ID": [1, 1, 1], "Convenio ID": [1, 1, 1],
        "Prestacion ID": [10, 10, 10],
        "Mes Vigencia": ["Abril 2011", "Septiembre 2024", "Enero 2020"],
        "Valor Convenido a HOY": [10.0, 99.0, 50.0],
    })
    merged = merge_datasets(consumo, valores)
    assert len(merged) == 1
    assert merged.loc[0, "Valor Convenido a HOY"] == 99.0   # Septiembre 2024 gana


def test_compute_metric_precio_unitario_evita_division_por_cero():
    df = pd.DataFrame({"Importe CM": [100.0, 50.0], "Cantidad CM": [4, 0]})
    precio = compute_metric(df, "precio_unitario")
    assert precio[0] == 25.0          # 100 / 4
    assert np.isnan(precio[1])        # cantidad 0 -> NaN, no excepción


def test_parse_month_acepta_espanol_y_canonico():
    """parse_month delega en el parser único: tolera MM-YYYY y español."""
    out = parse_month(pd.Series(["05-2026", "Mayo 2026", "banana"]))
    assert out[0] == pd.Timestamp("2026-05-01")
    assert out[1] == pd.Timestamp("2026-05-01")
    assert pd.isna(out[2])


def test_percentil_estructural_rechaza_umbral_de_zscore():
    """Regresión: un umbral tipo z-score (2.0) aplicado al método percentil
    marcaba ~100% de los registros como anómalos. Ahora falla ruidosamente."""
    df = pd.DataFrame({
        "Prestacion ID": [1, 1, 1], "Mes": ["01-2025"] * 3,
        "Importe CM": [100.0, 110.0, 500.0], "Cantidad CM": [1, 1, 1],
    })
    with pytest.raises(ValueError):
        detect_structural_anomalies(df, ["Prestacion ID", "Mes"],
                                    method="percentile", threshold=2.0)
    # Default por método: percentile -> 95 (no hereda el 2.0 del z-score)
    out = detect_structural_anomalies(df, ["Prestacion ID", "Mes"],
                                      method="percentile")
    assert out["is_anomaly_structural"].mean() < 1.0   # no marca todo


# ----------------------------------------------------------------------------
# core.ratelimit — lockout de login
# ----------------------------------------------------------------------------
def test_ratelimit_bloquea_tras_max_intentos():
    ratelimit.reset()
    t0 = 1_000_000.0
    for i in range(ratelimit.MAX_INTENTOS - 1):
        ratelimit.registrar_fallo("usuario", ahora=t0 + i)
    assert ratelimit.segundos_bloqueado("usuario", ahora=t0 + 10) == 0

    ratelimit.registrar_fallo("usuario", ahora=t0 + 5)        # 5to fallo
    assert ratelimit.segundos_bloqueado("usuario", ahora=t0 + 10) > 0
    # Pasado el bloqueo, se libera
    assert ratelimit.segundos_bloqueado(
        "usuario", ahora=t0 + 5 + ratelimit.BLOQUEO_SEG + 1
    ) == 0
    # Otro usuario no se ve afectado
    assert ratelimit.segundos_bloqueado("otro", ahora=t0 + 10) == 0
    ratelimit.reset()


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


def test_df_fingerprint_distingue_contenido():
    """La huella barata de caché debe ser estable para el mismo contenido y
    distinta cuando cambian los datos numéricos (filtro, prestador, mes)."""
    a = pd.DataFrame({"x": [1, 2], "y": ["a", "b"]})
    b = pd.DataFrame({"x": [1, 3], "y": ["a", "b"]})
    assert df_fingerprint(a) == df_fingerprint(a.copy())
    assert df_fingerprint(a) != df_fingerprint(b)            # contenido distinto
    assert df_fingerprint(a) != df_fingerprint(a.head(1))    # largo distinto


def test_format_int_es_ar():
    from ui.formatters import format_int
    assert format_int(644_984) == "644.984"
    assert format_int(0) == "0"


def test_safe_pct_evita_inf_y_nan():
    assert safe_pct(50, 200) == pytest.approx(25.0)
    assert safe_pct(10, 0) is None          # división por cero -> None, no inf
    assert safe_pct(10, float("nan")) is None
    assert safe_pct(float("nan"), 10) is None


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


def test_to_numeric_tolerante_negativos_contables():
    """Los exports reales traen negativos entre paréntesis: '(5,477,196)'."""
    out = to_numeric_tolerante(pd.Series(["(5,477,196)", "(2.50)"]))
    assert out[0] == -5477196
    assert out[1] == pytest.approx(-2.50)


# ----------------------------------------------------------------------------
# core.excel_utils — mapeo de columnas crudas de MicroStrategy
# ----------------------------------------------------------------------------
def test_normalize_mstr_columns_estilo_consumo():
    """Consumo crudo: ID en la columna nombrada, Desc en la 'Unnamed' contigua;
    'Convenio' trae un flag (no ID) -> solo se mapea la Desc."""
    df = pd.DataFrame({
        "Prestador": ["1,130 ", "1,130 "],
        "Unnamed: 1": ["Clinica Ficticia", "Clinica Ficticia"],
        "Convenio": ["P", "0"],
        "Unnamed: 3": ["Convenio Ficticio - Amb", "Convenio Ficticio - Int"],
        "Prestacion": ["Consulta de prueba", "Práctica de prueba"],
        "Unnamed: 5": ["42010100", "150101"],
        "Cantidad CM": ["10 ", "5 "],
    })
    out = normalize_mstr_columns(df)
    assert "Prestador ID" in out.columns and "Prestador Desc" in out.columns
    assert "Convenio Desc" in out.columns
    assert "Convenio ID" not in out.columns          # el export no lo trae
    assert "Prestacion ID" in out.columns and "Prestacion Desc" in out.columns
    assert out.loc[0, "Prestacion ID"] == "42010100"
    assert not any(str(c).startswith("Unnamed") for c in out.columns)


def test_normalize_mstr_columns_no_toca_archivos_curados():
    df = pd.DataFrame({"Prestador ID": [1], "Prestador Desc": ["X"], "Mes": ["01-2025"]})
    out = normalize_mstr_columns(df)
    assert list(out.columns) == ["Prestador ID", "Prestador Desc", "Mes"]


def test_load_excel_smart_csv_utf8_bom_y_orden_invertido():
    """CSV estilo 'valores': UTF-8 con BOM, Desc en la nombrada e ID en la Unnamed."""
    csv = (
        "﻿Prestador,Unnamed: 1,Convenio,Unnamed: 3,Prestacion,Unnamed: 5,"
        "Mes Vigencia,Valor Convenido a HOY\n"
        '99999,Sanatorio Ficticio,Convenio Ficticio Ambulatorio,4962,'
        '"Biopsia de prueba, c/u",150101,Mayo 2026,"8,206.90"\n'
    ).encode("utf-8")
    df = load_excel_smart(csv, EXPECTED_VALORES_COLS)
    assert df.loc[0, "Prestador ID"] == 99999
    assert df.loc[0, "Convenio ID"] == 4962
    assert df.loc[0, "Prestacion Desc"].startswith("Biopsia")
    assert df.loc[0, "Mes Vigencia"] == "Mayo 2026"


def test_load_excel_smart_csv_mac_roman_con_cr():
    """CSV estilo 'consumo': encoding Mac OS Roman y finales de línea CR-only."""
    texto = (
        "Prestador,Unnamed: 1,Cantidad CM,Importe CM\r"
        '"1,130 ",Clínica Ñandú,"2,073 ","(5,477,196)"\r'
    )
    df = load_excel_smart(texto.encode("mac_roman"), set())
    assert df.loc[0, "Prestador ID"].strip() == "1,130"   # numérico recién en clean_dataset
    assert df.loc[0, "Prestador Desc"] == "Clínica Ñandú"   # acentos correctos


def test_clean_dataset_descarta_filas_duplicadas_exactas():
    """Anti-duplicados a nivel fila: una fila idéntica repetida dentro del
    archivo es un duplicado real (los exports son agregados) y se descarta."""
    df = pd.DataFrame({
        "Prestador ID": [1130, 1130, 1130],
        "Mes": ["01-2025", "01-2025", "01-2025"],
        "Prestacion ID": [100, 100, 200],     # las dos primeras son idénticas
        "Cantidad CM": [5, 5, 3],
    })
    out = clean_dataset(df, CONSUMO_NUMERIC_COLS)
    assert len(out) == 2
    assert out["Prestacion ID"].tolist() == [100, 200]


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
