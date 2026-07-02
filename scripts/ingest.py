#!/usr/bin/env python3
"""
Ingesta idempotente de los Excel de MicroStrategy hacia DuckDB (local).

Flujo de trabajo (cumple la política de IT: SOLO descarga manual + script):
  1. Bajás los reportes de MicroStrategy a mano (por grupos de prestadores, por
     el límite de ~1M filas) y los dejás en:
         data/raw/consumo/*.xlsx   -> tabla 'consumo'
         data/raw/valores/*.xlsx   -> tabla 'valores'
  2. Corrés este script. Construye/actualiza data/simulador.duckdb.

Uso:
    python scripts/ingest.py            # ingiere lo nuevo de data/raw/
    python scripts/ingest.py --rebuild  # reconstruye la base desde cero
    python scripts/ingest.py --status   # muestra qué hay cargado

Idempotencia:
  - Cada archivo se identifica por hash SHA-256 + el mes que se le asigna de
    AFUERA (--mes o el nombre del archivo, para los consumos crudos sin
    columna 'Mes'); si ya se ingirió con ese mes, se saltea (volver a correr
    el script no duplica datos). Corregir el mes y re-correr SÍ re-ingiere;
    --force re-ingiere aunque nada haya cambiado.
  - OJO: re-ingerir con el mes corregido NO borra las filas que la corrida
    equivocada dejó bajo el otro mes (no hay trazabilidad de origen por fila);
    el camino seguro tras un mes mal cargado es reconstruir con --rebuild.
  - El upsert reemplaza SOLO las filas de los pares (Prestador ID, Mes) que
    trae el archivo nuevo, sin pisar otros prestadores del mismo mes. Esto hace
    seguro bajar los datos "de a partes".
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# Permite ejecutar el script desde la raíz del repo sin instalar el paquete.
_SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))

from core import db  # noqa: E402
from core import excel_utils as xu  # noqa: E402

RAW_DIR = Path("data") / "raw"

# Bandeja unificada: cualquier export se suelta acá (sin separar por carpeta);
# el tipo se detecta por contenido y el mes desde el nombre del archivo.
# Lo procesado OK se mueve a PROCESADO_DIR.
INBOX_DIR = Path("data") / "a_procesar"
PROCESADO_DIR = Path("data") / "procesado"

DATASETS = {
    "consumo": {
        "dir": RAW_DIR / "consumo",
        "table": db.CONSUMO_TABLE,
        "expected": xu.EXPECTED_CONSUMO_COLS,
        "numeric": xu.CONSUMO_NUMERIC_COLS,
        "key": db.CONSUMO_KEY,
    },
    "valores": {
        "dir": RAW_DIR / "valores",
        "table": db.VALORES_TABLE,
        "expected": xu.EXPECTED_VALORES_COLS,
        "numeric": xu.VALORES_NUMERIC_COLS,
        "key": db.VALORES_KEY,
    },
}


# ============================================================================
# HELPERS
# ============================================================================
def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# La identidad de una ingesta es (hash, mes asignado): el 'Mes' de los consumos
# crudos viene de AFUERA (--mes o el nombre del archivo), así que el mismo
# archivo re-corrido con el mes CORREGIDO es otra ingesta, no un duplicado.
_LOG_SCHEMA_SQL = f"""
    CREATE TABLE IF NOT EXISTS {db.INGEST_LOG_TABLE} (
        file_hash   VARCHAR,
        file_name   VARCHAR,
        tipo        VARCHAR,
        rows        BIGINT,
        ingested_at TIMESTAMP,
        mes         VARCHAR DEFAULT '',
        PRIMARY KEY (file_hash, mes)
    )
"""


def _ensure_log(con) -> None:
    if db.table_exists(con, db.INGEST_LOG_TABLE):
        cols = [
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = ?",
                [db.INGEST_LOG_TABLE],
            ).fetchall()
        ]
        if "mes" in cols:
            return
        # Migración de bases anteriores (identidad SOLO por hash, PK simple):
        # se recrea el log con la clave (hash, mes); lo ya ingerido queda
        # registrado con mes '' y sigue contando como ingerido.
        con.execute(
            f"ALTER TABLE {db.INGEST_LOG_TABLE} RENAME TO _ingest_log_v1"
        )
        con.execute(_LOG_SCHEMA_SQL)
        con.execute(
            f"INSERT INTO {db.INGEST_LOG_TABLE} SELECT *, '' FROM _ingest_log_v1"
        )
        con.execute("DROP TABLE _ingest_log_v1")
        return
    con.execute(_LOG_SCHEMA_SQL)


def _already_ingested(con, file_hash: str, mes_id: str) -> bool:
    row = con.execute(
        f"SELECT 1 FROM {db.INGEST_LOG_TABLE} WHERE file_hash = ? AND mes = ?",
        [file_hash, mes_id],
    ).fetchone()
    return row is not None


def _align_to_table(con, table: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Alinea las columnas del df al esquema de la tabla ya existente: completa
    en el df las que falten (NULL) y, si el archivo trae columnas que la tabla
    NO tiene, las agrega a la tabla (ALTER TABLE ADD COLUMN) en vez de
    descartarlas en silencio — un export más rico que el primero no pierde datos.
    """
    cols = [
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position",
            [table],
        ).fetchall()
    ]
    nuevas = [c for c in df.columns if c not in cols]
    if nuevas:
        # El tipo de cada columna nueva lo infiere DuckDB del propio df.
        con.register("df_cols_nuevas", df[nuevas])
        tipos = {
            r[0]: r[1]
            for r in con.execute("DESCRIBE SELECT * FROM df_cols_nuevas").fetchall()
        }
        con.unregister("df_cols_nuevas")
        for c in nuevas:
            con.execute(f'ALTER TABLE "{table}" ADD COLUMN "{c}" {tipos[c]}')
        print(f"    (columnas nuevas agregadas a '{table}': {sorted(nuevas)}; "
              f"en las filas ya cargadas quedan NULL)")
        cols += nuevas
    return df.reindex(columns=cols)


def _upsert(con, table: str, key: tuple, df: pd.DataFrame, expected: set) -> None:
    """Reemplaza las filas de los (key) presentes en df e inserta las nuevas."""
    if not db.table_exists(con, table):
        # La tabla nace con la UNIÓN del esquema del archivo y las columnas
        # esperadas del dataset: si el primer archivo trae menos columnas
        # (p.ej. un export crudo sin 'Tipo Clase CM'), las que falten quedan
        # como VARCHAR NULL en vez de amputarse del esquema para siempre.
        con.register("df_new", df)
        con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM df_new')
        con.unregister("df_new")
        for col in sorted(set(expected) - set(df.columns)):
            con.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" VARCHAR')
        return

    df = _align_to_table(con, table, df)

    keys_df = df[list(key)].drop_duplicates()
    cond = " AND ".join(f't."{k}" IS NOT DISTINCT FROM kk."{k}"' for k in key)

    con.register("df_new", df)
    con.register("keys_new", keys_df)
    borradas = con.execute(
        f'DELETE FROM "{table}" AS t '
        f'WHERE EXISTS (SELECT 1 FROM keys_new AS kk WHERE {cond})'
    ).fetchone()[0]
    con.execute(f'INSERT INTO "{table}" SELECT * FROM df_new')
    con.unregister("df_new")
    con.unregister("keys_new")

    # El reemplazo por (key) es POR DISEÑO destructivo dentro de cada par: si
    # el archivo nuevo trae bastante menos filas que las que pisa, casi seguro
    # es un re-export PARCIAL y el resto del par se está perdiendo. Avisamos.
    if borradas and len(df) < borradas * 0.5:
        print(
            f"  ! ATENCIÓN: el reemplazo por {key} borró {borradas:,} fila(s) "
            f"y el archivo nuevo insertó solo {len(df):,}. Si el re-export era "
            f"parcial, el resto de esos pares SE PERDIÓ: re-ingerí el export "
            f"completo del período."
        )


def _archivar(path: Path, dest_dir: Path | None = None) -> None:
    """Mueve un archivo ya procesado a <carpeta>/procesados/ (o al destino
    indicado). La base DuckDB es la fuente unificada; los archivos de entrada
    son solo material crudo."""
    dest_dir = dest_dir if dest_dir is not None else path.parent / "procesados"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    if dest.exists():
        dest = dest_dir / f"{path.stem}_{datetime.now():%Y%m%d%H%M%S}{path.suffix}"
    path.rename(dest)
    print(f"    archivado -> {dest}")


def _preparar_consumo(df: pd.DataFrame, path: Path, mes: str | None):
    """
    Completa las columnas que el export CRUDO de consumo no trae.

    'Mes': el período no queda en el archivo -> se resuelve, en orden, desde
    el NOMBRE del archivo ('05-2026-Consumo-1584.xlsx') o desde --mes.
    'Convenio ID': el export trae un flag, no el ID -> queda NULL y el merge
    degrada a Prestador + Prestación.

    Devuelve el df listo, o None si falta el período.
    """
    if "Mes" not in df.columns:
        mes_archivo = xu.mes_desde_nombre(path.name) or mes
        if mes_archivo:
            df["Mes"] = mes_archivo
            origen = "del nombre del archivo" if xu.mes_desde_nombre(path.name) else "de --mes"
            print(f"    (export sin columna 'Mes': asignado {mes_archivo} {origen})")
        else:
            print(f"  ! {path.name}: el export no trae columna 'Mes'. "
                  f"Nombrá el archivo con el período (ej: 05-2026-Consumo-1584.xlsx) "
                  f"o corré con --mes MM-YYYY — saltando")
            return None
    if "Convenio ID" not in df.columns:
        df["Convenio ID"] = pd.NA
        print("    (export sin 'Convenio ID': queda NULL; "
              "el merge usará Prestador + Prestación)")
    return df


def _process_file(con, tipo: str | None, ds: dict | None, path: Path,
                  rebuild: bool, mes: str | None = None,
                  force: bool = False) -> tuple[int, bool]:
    """Procesa un archivo. Devuelve (filas_insertadas, procesado_ok) — ok
    incluye 'ya estaba ingerido' (es archivable).

    Con tipo=None (bandeja data/a_procesar) el tipo se detecta por el
    CONTENIDO del archivo (clasificar_dataset)."""
    file_hash = _file_hash(path)
    # Identidad de la ingesta = (hash, mes asignado de afuera): re-correr el
    # mismo archivo con el mes CORREGIDO no debe saltearse.
    mes_id = xu.mes_desde_nombre(path.name) or mes or ""
    if not rebuild and not force and _already_ingested(con, file_hash, mes_id):
        print(f"  - {path.name}: ya ingerido, saltando (--force para re-ingerir)")
        return 0, True

    content = path.read_bytes()
    try:
        expected = ds["expected"] if ds else (
            xu.EXPECTED_CONSUMO_COLS | xu.EXPECTED_VALORES_COLS
        )
        df = xu.load_excel_smart(content, expected)
    except Exception as e:
        print(f"  ! {path.name}: no se pudo leer ({e}) — saltando")
        return 0, False

    if tipo is None:
        tipo = xu.clasificar_dataset(df.columns)
        if tipo is None:
            print(f"  ! {path.name}: no parece consumo ni valores "
                  f"(sin 'Cantidad CM'/'Importe CM' ni 'Valor Convenido a HOY') — saltando")
            return 0, False
        ds = DATASETS[tipo]
        print(f"    (detectado como '{tipo}')")

    if tipo == "consumo":
        df = _preparar_consumo(df, path, mes)
        if df is None:
            return 0, False

    miss = xu.missing_columns(df, ds["expected"])
    if miss:
        print(f"  ! {path.name}: faltan columnas {sorted(miss)} — saltando")
        return 0, False

    # Limpia filas de Total/Subtotal, duplicados exactos y tipa las numéricas.
    filas_antes = len(df)
    df = xu.clean_dataset(df, ds["numeric"])
    descartadas = filas_antes - len(df)
    if descartadas:
        print(f"    ({descartadas} fila(s) de total/sin clave/duplicadas descartadas)")

    con.execute("BEGIN")
    try:
        _upsert(con, ds["table"], ds["key"], df, ds["expected"])
        con.execute(
            f"INSERT INTO {db.INGEST_LOG_TABLE} VALUES (?, ?, ?, ?, ?, ?) "
            f'ON CONFLICT (file_hash, mes) DO UPDATE SET '
            f'"rows" = excluded."rows", ingested_at = excluded.ingested_at',
            [file_hash, path.name, tipo, len(df), datetime.now(), mes_id],
        )
        con.execute("COMMIT")
    except Exception as e:
        con.execute("ROLLBACK")
        print(f"  ! {path.name}: error al insertar ({e})")
        return 0, False

    print(f"  + {path.name}: {len(df):,} filas")
    return len(df), True


def _print_status(con) -> None:
    print("\nEstado de la base:")
    for tipo, ds in DATASETS.items():
        n = db.table_count(con, ds["table"])
        print(f"  - {ds['table']:<8}: {n:,} filas")
    if db.table_exists(con, db.INGEST_LOG_TABLE):
        files = con.execute(
            f"SELECT COUNT(*) FROM {db.INGEST_LOG_TABLE}"
        ).fetchone()[0]
        print(f"  - archivos ingeridos: {files}")


# ============================================================================
# MAIN
# ============================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="Ingesta de Excel -> DuckDB")
    ap.add_argument("--rebuild", action="store_true",
                    help="Borra y reconstruye la base desde cero")
    ap.add_argument("--status", action="store_true",
                    help="Solo muestra qué hay cargado y sale")
    ap.add_argument("--solo", metavar="ARCHIVO", default=None,
                    help="Procesa únicamente el archivo con ese nombre exacto "
                         "(permite asignar --mes distinto por archivo)")
    ap.add_argument("--archivar", action="store_true",
                    help="Mueve los archivos procesados OK a data/raw/<tipo>/procesados/ "
                         "para que la carpeta de entrada no acumule archivos viejos")
    ap.add_argument("--mes", metavar="MM-YYYY", default=None,
                    help="Período de los archivos de consumo SIN columna 'Mes' "
                         "(el export crudo de MicroStrategy no la trae). "
                         "Ej: --mes 01-2026")
    ap.add_argument("--force", action="store_true",
                    help="Re-ingiere aunque el archivo ya figure como ingerido "
                         "(mismo hash y mes). OJO: no borra las filas que una "
                         "ingesta previa dejó bajo OTRO mes; tras un mes mal "
                         "cargado el camino seguro es --rebuild")
    args = ap.parse_args()

    if args.mes and not re.fullmatch(r"\d{2}-\d{4}", args.mes):
        print(f"--mes debe ser MM-YYYY (recibido: {args.mes!r})")
        return 1

    try:
        con = db.get_connection(read_only=False)
    except Exception as e:
        if "lock" in str(e).lower():
            # DuckDB no permite un escritor mientras hay lectores abiertos.
            print(
                "ERROR: la base está bloqueada por otro proceso.\n"
                "Cerrá la app Streamlit (que mantiene lectores abiertos) "
                "antes de correr la ingesta, y reintentá."
            )
            return 1
        raise
    _ensure_log(con)

    if args.status:
        _print_status(con)
        con.close()
        return 0

    if args.rebuild:
        print("Reconstruyendo base desde cero...")
        for ds in DATASETS.values():
            con.execute(f'DROP TABLE IF EXISTS "{ds["table"]}"')
        con.execute(f"DROP TABLE IF EXISTS {db.INGEST_LOG_TABLE}")
        _ensure_log(con)

    total = 0
    for tipo, ds in DATASETS.items():
        ds["dir"].mkdir(parents=True, exist_ok=True)
        # Los exports de MicroStrategy vienen como xlsx o CSV (encoding variable);
        # load_excel_smart detecta el formato por contenido.
        files = sorted([*ds["dir"].glob("*.xlsx"), *ds["dir"].glob("*.csv")])
        if args.solo:
            files = [p for p in files if p.name == args.solo]
        print(f"[{tipo}] {len(files)} archivo(s) en {ds['dir']}")
        for path in files:
            filas, ok = _process_file(con, tipo, ds, path, args.rebuild,
                                      args.mes, args.force)
            total += filas
            if ok and args.archivar:
                _archivar(path)

    # Bandeja unificada: se suelta CUALQUIER export en data/a_procesar/ (sin
    # separar por carpeta), el tipo se detecta por contenido y el mes desde el
    # nombre ('05-2026-Consumo-1584.xlsx'). Lo procesado se mueve SIEMPRE a
    # data/procesado/ (es el contrato de la bandeja).
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    PROCESADO_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted([*INBOX_DIR.glob("*.xlsx"), *INBOX_DIR.glob("*.csv")])
    if args.solo:
        files = [p for p in files if p.name == args.solo]
    print(f"[a_procesar] {len(files)} archivo(s) en {INBOX_DIR}")
    for path in files:
        filas, ok = _process_file(con, None, None, path, args.rebuild,
                                  args.mes, args.force)
        total += filas
        if ok:
            _archivar(path, PROCESADO_DIR)

    print(f"\nListo. {total:,} filas procesadas en esta corrida.")
    _print_status(con)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
