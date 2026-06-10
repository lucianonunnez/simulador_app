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
  - Cada archivo se identifica por hash SHA-256; si ya se ingirió, se saltea
    (volver a correr el script no duplica datos).
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


def _ensure_log(con) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {db.INGEST_LOG_TABLE} (
            file_hash   VARCHAR PRIMARY KEY,
            file_name   VARCHAR,
            tipo        VARCHAR,
            rows        BIGINT,
            ingested_at TIMESTAMP
        )
        """
    )


def _already_ingested(con, file_hash: str) -> bool:
    row = con.execute(
        f"SELECT 1 FROM {db.INGEST_LOG_TABLE} WHERE file_hash = ?", [file_hash]
    ).fetchone()
    return row is not None


def _align_to_table(con, table: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Alinea las columnas del df al esquema de la tabla ya existente:
    agrega las que falten (NULL) y descarta las de más, para que el esquema
    quede estable entre archivos de descargas distintas.
    """
    cols = [
        r[0]
        for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position",
            [table],
        ).fetchall()
    ]
    return df.reindex(columns=cols)


def _upsert(con, table: str, key: tuple, df: pd.DataFrame) -> None:
    """Reemplaza las filas de los (key) presentes en df e inserta las nuevas."""
    if not db.table_exists(con, table):
        con.register("df_new", df)
        con.execute(f'CREATE TABLE "{table}" AS SELECT * FROM df_new')
        con.unregister("df_new")
        return

    df = _align_to_table(con, table, df)

    keys_df = df[list(key)].drop_duplicates()
    cond = " AND ".join(f't."{k}" IS NOT DISTINCT FROM kk."{k}"' for k in key)

    con.register("df_new", df)
    con.register("keys_new", keys_df)
    con.execute(
        f'DELETE FROM "{table}" AS t '
        f'WHERE EXISTS (SELECT 1 FROM keys_new AS kk WHERE {cond})'
    )
    con.execute(f'INSERT INTO "{table}" SELECT * FROM df_new')
    con.unregister("df_new")
    con.unregister("keys_new")


def _archivar(path: Path) -> None:
    """Mueve un archivo ya procesado a <carpeta>/procesados/ (la base DuckDB es
    la fuente unificada; los archivos de entrada son solo material crudo)."""
    dest_dir = path.parent / "procesados"
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / path.name
    if dest.exists():
        dest = dest_dir / f"{path.stem}_{datetime.now():%Y%m%d%H%M%S}{path.suffix}"
    path.rename(dest)
    print(f"    archivado -> {dest}")


def _process_file(con, tipo: str, ds: dict, path: Path, rebuild: bool,
                  mes: str | None = None) -> tuple[int, bool]:
    """Procesa un archivo. Devuelve (filas_insertadas, procesado_ok) — ok
    incluye 'ya estaba ingerido' (es archivable)."""
    file_hash = _file_hash(path)
    if not rebuild and _already_ingested(con, file_hash):
        print(f"  - {path.name}: ya ingerido, saltando")
        return 0, True

    content = path.read_bytes()
    try:
        df = xu.load_excel_smart(content, ds["expected"])
    except Exception as e:
        print(f"  ! {path.name}: no se pudo leer ({e}) — saltando")
        return 0, False

    # El export CRUDO de consumo no trae el período en el archivo: se asigna
    # desde --mes. Tampoco trae 'Convenio ID' (la columna 'Convenio' es un
    # flag): queda NULL y el merge degrada a Prestador + Prestación.
    if tipo == "consumo" and "Mes" not in df.columns:
        if mes:
            df["Mes"] = mes
            print(f"    (export sin columna 'Mes': asignado {mes} desde --mes)")
        else:
            print(f"  ! {path.name}: el export no trae columna 'Mes'. "
                  f"Corré con --mes MM-YYYY para ingerirlo — saltando")
            return 0, False
    if tipo == "consumo" and "Convenio ID" not in df.columns:
        df["Convenio ID"] = pd.NA
        print("    (export sin 'Convenio ID': queda NULL; "
              "el merge usará Prestador + Prestación)")

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
        _upsert(con, ds["table"], ds["key"], df)
        con.execute(
            f"INSERT INTO {db.INGEST_LOG_TABLE} VALUES (?, ?, ?, ?, ?) "
            f"ON CONFLICT (file_hash) DO NOTHING",
            [file_hash, path.name, tipo, len(df), datetime.now()],
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
            filas, ok = _process_file(con, tipo, ds, path, args.rebuild, args.mes)
            total += filas
            if ok and args.archivar:
                _archivar(path)

    print(f"\nListo. {total:,} filas procesadas en esta corrida.")
    _print_status(con)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
