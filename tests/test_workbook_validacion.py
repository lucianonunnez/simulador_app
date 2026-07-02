"""
Cobertura en CI del validador de workbooks con un fixture SINTÉTICO.

La regresión real (tests/test_simulaciones_negocio.py) reconcilia contra
workbooks del negocio que NO se versionan (precios de prestadores) y por eso
se saltea en CI. Este test genera un workbook mínimo con openpyxl —misma
estructura de hoja 'Simulación': fila de título, encabezado con las triplas
'Valor actual/solicitado/propuesto' DUPLICADAS (unitario y Q×P), filas Pauta y
No pauta, y un subtotal sin Cantidad— para que `core.workbook_validacion`
tenga cobertura garantizada sin datos sensibles.
"""

from __future__ import annotations

from io import BytesIO

import pytest

# El fixture sintético se arma con openpyxl (mismo motor que lee los workbooks
# reales). En un entorno sin openpyxl el módulo se saltea en vez de romper.
pytest.importorskip("openpyxl")

from core.workbook_validacion import extraer_simulacion, validar_workbook  # noqa: E402

# Universo Pauta del workbook sintético (ventana anual, n_meses=12):
#   pid 101: cant 10 × vact 1000 → act 10.000 | sol 11.000 | prop 10.500
#   pid 200: cant  4 × vact  500 → act  2.000 | sol  2.200 | prop  2.000
# Totales: act 12.000 | sol 13.200 | prop 12.500
IMPACTO_SOL = 13_200 - 12_000     # 1.200
IMPACTO_PROP = 12_500 - 12_000    # 500
PCT_SOL = 13_200 / 12_000 - 1     # 10%
PCT_PROP = 12_500 / 12_000 - 1


def _workbook_sintetico(
    pid_header: str = "idPrestacion", con_datos: bool = True
) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Simulación"

    ws.append(["Simulación sintética de prueba"])  # fila de título
    ws.append([
        "Tipo Clase CM", "Nomenclador", pid_header, "Pauta/No pauta",
        "Cantidad CM",
        "Valor actual", "Valor solicitado", "Valor propuesto",   # unitarios
        "Valor actual", "Valor solicitado", "Valor propuesto",   # Q×P
    ])
    if con_datos:
        ws.append([
            "Ambulatorio", "Consultas", 101, "Pauta", 10,
            1000, 1100, 1050, 10_000, 11_000, 10_500,
        ])
        ws.append([
            "Ambulatorio", "Laboratorio", 200, "Pauta", 4,
            500, 550, 500, 2_000, 2_200, 2_000,
        ])
        # No pauta: queda fuera del universo simulable.
        ws.append([
            "Internacion", "Módulos", 300, "No pauta", 5,
            100, 120, 110, 500, 600, 550,
        ])
        # Subtotal sin Cantidad: debe saltearse.
        ws.append(["", "TOTAL", None, None, None, None, None, None])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extraer_simulacion_estructura_y_universo():
    df = extraer_simulacion(_workbook_sintetico())
    assert len(df) == 3                       # el subtotal se saltea
    assert set(df["pauta"]) == {"Pauta", "No pauta"}
    fila = df[df["pid"] == 101].iloc[0]
    assert fila["cant"] == 10 and fila["vact"] == 1000
    assert fila["qxp_prop"] == 10_500         # segunda tripla = Q×P


def test_validar_workbook_reconcilia_por_dos_rutas():
    res = validar_workbook(_workbook_sintetico())
    assert res["n_filas"] == 3 and res["n_pauta"] == 2

    sol, prop = res["solicitado"], res["propuesto"]
    assert sol["impacto"] == pytest.approx(IMPACTO_SOL)
    assert sol["impacto_pct"] == pytest.approx(PCT_SOL)
    assert prop["impacto"] == pytest.approx(IMPACTO_PROP)
    assert prop["impacto_pct"] == pytest.approx(PCT_PROP)
    assert prop["impacto_mensual"] == pytest.approx(IMPACTO_PROP / 12)
    # Las dos rutas internas (reconstruido vs Q×P del negocio) coinciden.
    assert sol["desvio_qxp"] < 1e-12
    assert prop["desvio_qxp"] < 1e-12


def test_validar_workbook_variante_encabezado_cod():
    """Los workbooks reales alternan 'idPrestacion' / 'Cod'."""
    res = validar_workbook(_workbook_sintetico(pid_header="Cod"))
    assert res["propuesto"]["impacto"] == pytest.approx(IMPACTO_PROP)


def test_validar_workbook_hoja_vacia_no_revienta():
    """Regresión: hoja 'Simulación' solo con encabezados daba KeyError."""
    res = validar_workbook(_workbook_sintetico(con_datos=False))
    assert res == {
        "n_filas": 0, "n_pauta": 0, "solicitado": None, "propuesto": None,
    }
