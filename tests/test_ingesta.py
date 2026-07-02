"""
Tests de la ingesta (scripts/ingest.py) contra una base DuckDB TEMPORAL.

Sin Streamlit: se importan los helpers del script directamente (main() solo
corre bajo __main__, así que importar el módulo no dispara el CLI). Cubren
los tres blindajes de la ingesta:
  - El esquema de la tabla NO lo fija el primer archivo (unión con el contrato
    + ALTER TABLE para columnas nuevas, sin pérdida silenciosa).
  - El upsert reemplaza SOLO el par (Prestador, Mes) del archivo, con aviso
    cuando el reemplazo pisa muchas más filas de las que inserta.
  - La identidad de ingesta es (hash, mes asignado): el mismo archivo con el
    mes corregido NO se saltea; --force re-ingiere aunque nada haya cambiado.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# DuckDB es la base de la ingesta. En un entorno mínimo sin duckdb (p. ej. si
# el CI se corriera aún más liviano) estos tests se saltean en vez de romper la
# colección; con el stack completo corren normalmente. Va ANTES de importar
# ingest / core.db, que también dependen de duckdb.
duckdb = pytest.importorskip("duckdb")

# El script vive en scripts/ (no es un paquete): se agrega al path a mano.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import ingest  # noqa: E402
from core import db  # noqa: E402
from core.excel_utils import EXPECTED_CONSUMO_COLS  # noqa: E402

KEY = ("Prestador ID", "Mes")

# CSV curado de consumo con TODAS las columnas del contrato (una fila).
_HEADER_CURADO = (
    "Prestador ID,Prestador Desc,Convenio ID,Convenio Desc,Mes,Tipo Categoria,"
    "Megacuenta,Gama,Cartilla,Tipo Clase CM,Nomenclador,Prestacion Desc,"
    "Prestacion ID,Cantidad CM,Importe CM"
)

# Export CRUDO de consumo: sin 'Mes' (viene de afuera) ni 'Convenio ID'
# (los completa _preparar_consumo); el resto del contrato presente.
_HEADER_CRUDO = (
    "Prestador ID,Prestador Desc,Convenio Desc,Tipo Categoria,Megacuenta,"
    "Gama,Cartilla,Tipo Clase CM,Nomenclador,Prestacion Desc,Prestacion ID,"
    "Cantidad CM,Importe CM"
)


def _fila_curada(prestador: int, mes: str, extra: str = "") -> str:
    return (f"{prestador},Clinica {prestador},10,Convenio A,{mes},Sanatorial,"
            f"No,Media,Si,Ambulatorio,NBU,Consulta,100,5,1000{extra}")


@pytest.fixture
def con(tmp_path):
    con = duckdb.connect(str(tmp_path / "test.duckdb"))
    ingest._ensure_log(con)
    yield con
    con.close()


def _cols_tabla(con, tabla: str) -> list:
    return [
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position", [tabla],
        ).fetchall()
    ]


# ----------------------------------------------------------------------------
# Esquema: el primer archivo NO fija la tabla / columnas nuevas no se pierden
# ----------------------------------------------------------------------------
def test_primer_archivo_parcial_no_amputa_el_esquema(con):
    """Tabla creada desde un df SIN 'Tipo Clase CM': debe nacer con la unión
    del df + el contrato, y el archivo completo posterior conserva su valor
    (antes se descartaba en silencio y se apagaba el merge por ámbito)."""
    parcial = pd.DataFrame({
        "Prestador ID": [1], "Mes": ["01-2025"],
        "Prestacion ID": [100], "Cantidad CM": [5], "Importe CM": [500.0],
    })
    ingest._upsert(con, "consumo_t", KEY, parcial, EXPECTED_CONSUMO_COLS)
    assert EXPECTED_CONSUMO_COLS <= set(_cols_tabla(con, "consumo_t"))

    completo = pd.DataFrame({
        "Prestador ID": [2], "Mes": ["01-2025"], "Prestacion ID": [100],
        "Cantidad CM": [3], "Importe CM": [300.0],
        "Tipo Clase CM": ["Internación"],
    })
    ingest._upsert(con, "consumo_t", KEY, completo, EXPECTED_CONSUMO_COLS)
    out = con.execute(
        'SELECT "Tipo Clase CM" FROM consumo_t WHERE "Prestador ID" = 2'
    ).fetchall()
    assert out == [("Internación",)]   # no se perdió en el reindex


def test_ingesta_columna_nueva_hace_alter_y_no_descarta(con, tmp_path, capsys):
    """Flujo completo con _process_file: un archivo posterior con una columna
    que la tabla no tiene la AGREGA (ALTER TABLE) en vez de descartarla."""
    ds = ingest.DATASETS["consumo"]
    f1 = tmp_path / "consumo_a.csv"
    f1.write_text(f"{_HEADER_CURADO}\n{_fila_curada(1, '01-2025')}\n",
                  encoding="utf-8")
    f2 = tmp_path / "consumo_b.csv"
    f2.write_text(
        f"{_HEADER_CURADO},Columna Extra\n"
        f"{_fila_curada(2, '01-2025', extra=',dato nuevo')}\n",
        encoding="utf-8",
    )

    filas, ok = ingest._process_file(con, "consumo", ds, f1, rebuild=False)
    assert ok and filas == 1
    filas, ok = ingest._process_file(con, "consumo", ds, f2, rebuild=False)
    assert ok and filas == 1

    assert "Columna Extra" in _cols_tabla(con, db.CONSUMO_TABLE)
    assert "columnas nuevas" in capsys.readouterr().out
    extra = con.execute(
        f'SELECT "Prestador ID", "Columna Extra" FROM "{db.CONSUMO_TABLE}" '
        f'ORDER BY "Prestador ID"'
    ).fetchall()
    assert extra == [(1, None), (2, "dato nuevo")]  # filas viejas quedan NULL


# ----------------------------------------------------------------------------
# Upsert por (Prestador, Mes)
# ----------------------------------------------------------------------------
def test_upsert_reemplaza_solo_el_par_prestador_mes(con):
    inicial = pd.DataFrame({
        "Prestador ID": [1, 1, 2],
        "Mes": ["01-2025", "02-2025", "01-2025"],
        "Cantidad CM": [5, 7, 9],
    })
    ingest._upsert(con, "t", KEY, inicial, set())

    nuevo = pd.DataFrame({
        "Prestador ID": [1], "Mes": ["01-2025"], "Cantidad CM": [50],
    })
    ingest._upsert(con, "t", KEY, nuevo, set())

    out = con.execute(
        'SELECT "Prestador ID", "Mes", "Cantidad CM" FROM t ORDER BY 1, 2'
    ).fetchall()
    # El par (1, 01-2025) se reemplazó; los otros dos pares quedaron intactos.
    assert out == [(1, "01-2025", 50), (1, "02-2025", 7), (2, "01-2025", 9)]


def test_upsert_avisa_cuando_el_reemplazo_es_mucho_mas_chico(con, capsys):
    """Re-export PARCIAL: si las filas nuevas son < 50% de las borradas del
    par, tiene que salir el aviso con los números (diseño destructivo)."""
    grande = pd.DataFrame({
        "Prestador ID": [1] * 10, "Mes": ["01-2025"] * 10,
        "Cantidad CM": list(range(10)),
    })
    ingest._upsert(con, "t", KEY, grande, set())
    chico = pd.DataFrame({
        "Prestador ID": [1], "Mes": ["01-2025"], "Cantidad CM": [99],
    })
    ingest._upsert(con, "t", KEY, chico, set())

    salida = capsys.readouterr().out
    assert "ATENCIÓN" in salida
    assert "10" in salida and "1" in salida   # borradas e insertadas

    # Mismo tamaño (re-ingesta normal): sin aviso.
    ingest._upsert(con, "t", KEY, chico, set())
    assert "ATENCIÓN" not in capsys.readouterr().out


# ----------------------------------------------------------------------------
# Identidad hash + mes / --force
# ----------------------------------------------------------------------------
def test_mismo_archivo_con_mes_corregido_no_se_saltea(con, tmp_path):
    """Consumo crudo (sin 'Mes' en el contenido ni en el nombre): re-correrlo
    con el mismo mes se saltea; con el mes CORREGIDO se re-ingiere."""
    ds = ingest.DATASETS["consumo"]
    raw = tmp_path / "consumo_crudo.csv"
    raw.write_text(
        f"{_HEADER_CRUDO}\n"
        "1,Clinica Uno,Convenio A,Sanatorial,No,Media,Si,Ambulatorio,NBU,"
        "Consulta,100,5,1000\n",
        encoding="utf-8",
    )

    filas, ok = ingest._process_file(con, "consumo", ds, raw,
                                     rebuild=False, mes="01-2025")
    assert ok and filas == 1

    # Mismo archivo, mismo mes -> idempotente (se saltea).
    filas, ok = ingest._process_file(con, "consumo", ds, raw,
                                     rebuild=False, mes="01-2025")
    assert ok and filas == 0

    # Mismo hash, mes corregido -> es OTRA ingesta, NO se saltea.
    filas, ok = ingest._process_file(con, "consumo", ds, raw,
                                     rebuild=False, mes="02-2025")
    assert ok and filas == 1
    meses = {
        r[0] for r in con.execute(
            f'SELECT DISTINCT "Mes" FROM "{db.CONSUMO_TABLE}"'
        ).fetchall()
    }
    assert meses == {"01-2025", "02-2025"}


def test_force_reingiere_sin_duplicar(con, tmp_path):
    ds = ingest.DATASETS["consumo"]
    f = tmp_path / "consumo_x.csv"
    f.write_text(f"{_HEADER_CURADO}\n{_fila_curada(1, '01-2025')}\n",
                 encoding="utf-8")

    filas, ok = ingest._process_file(con, "consumo", ds, f, rebuild=False)
    assert ok and filas == 1
    filas, ok = ingest._process_file(con, "consumo", ds, f, rebuild=False)
    assert ok and filas == 0            # sin --force: saltea

    filas, ok = ingest._process_file(con, "consumo", ds, f,
                                     rebuild=False, force=True)
    assert ok and filas == 1            # con --force: re-ingiere...
    assert db.table_count(con, db.CONSUMO_TABLE) == 1   # ...sin duplicar


def test_migracion_del_log_viejo_conserva_lo_ingerido(tmp_path):
    """Bases anteriores (log con PK solo por hash): _ensure_log migra a la
    identidad (hash, mes) sin perder los registros existentes."""
    con = duckdb.connect(str(tmp_path / "vieja.duckdb"))
    con.execute(
        f"""
        CREATE TABLE {db.INGEST_LOG_TABLE} (
            file_hash   VARCHAR PRIMARY KEY,
            file_name   VARCHAR,
            tipo        VARCHAR,
            rows        BIGINT,
            ingested_at TIMESTAMP
        )
        """
    )
    con.execute(
        f"INSERT INTO {db.INGEST_LOG_TABLE} "
        f"VALUES ('abc123', 'consumo.csv', 'consumo', 10, now())"
    )
    ingest._ensure_log(con)

    # Lo viejo migró con mes '' y sigue contando como ingerido.
    assert ingest._already_ingested(con, "abc123", "") is True
    # El mismo hash con OTRO mes es una ingesta nueva (y se puede registrar).
    assert ingest._already_ingested(con, "abc123", "05-2026") is False
    con.execute(
        f"INSERT INTO {db.INGEST_LOG_TABLE} "
        f"VALUES ('abc123', 'consumo.csv', 'consumo', 10, now(), '05-2026')"
    )
    con.close()
