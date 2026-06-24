#!/usr/bin/env python3
"""
Ingesta idempotente de los Excel de MicroStrategy hacia Supabase (PostgreSQL).

Flujo de trabajo:
  1. Bajás los reportes de MicroStrategy a mano y los dejás en:
         data/raw/consumo/*.xlsx   -> tabla simulador.consumo
         data/raw/valores/*.xlsx   -> tabla simulador.valores
  2. Corrés este script con DATABASE_URL configurado.

Uso:
    DATABASE_URL="postgresql://..." python scripts/ingest.py
    python scripts/ingest.py --rebuild  # reconstruye borrando filas existentes
    python scripts/ingest.py --status   # muestra qué hay cargado

Idempotencia:
  - Cada archivo se identifica por hash SHA-256; si ya se ingirió, se saltea.
  - El upsert reemplaza SOLO las filas de los pares (Prestador ID, Mes/Mes
    Vigencia) del archivo nuevo, sin pisar otros prestadores del mismo mes.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import psycopg2
import psycopg2.extras

_SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))

from core import db  # noqa: E402
from core import excel_utils as xu  # noqa: E402

RAW_DIR = Path("data") / "raw"
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


def _clean_val(v):
    """Convierte pandas NA/NaN a None para psycopg2."""
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _ensure_log(con: psycopg2.extensions.connection) -> None:
    """Crea la tabla de log de ingesta si no existe (safety net)."""
    with con.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS simulador."{db.INGEST_LOG_TABLE}" (
                file_hash   VARCHAR PRIMARY KEY,
                file_name   VARCHAR,
                tipo        VARCHAR,
                rows        BIGINT,
                ingested_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
            """
        )


def _already_ingested(con: psycopg2.extensions.connection, file_hash: str) -> bool:
    with con.cursor() as cur:
        cur.execute(
            f'SELECT 1 FROM "{db.INGEST_LOG_TABLE}" WHERE file_hash = %s',
            [file_hash],
        )
        return cur.fetchone() is not None


def _align_to_table(con: psycopg2.extensions.connection, table: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Alinea las columnas del df al esquema de la tabla ya existente:
    agrega las que falten (NULL) y descarta las de más.
    """
    with con.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
            [db.SCHEMA, table],
        )
        cols = [r[0] for r in cur.fetchall()]
    return df.reindex(columns=cols)


def _upsert(con: psycopg2.extensions.connection, table: str, key: tuple, df: pd.DataFrame) -> None:
    """Reemplaza las filas de los (key) presentes en df e inserta las nuevas."""
    with con.cursor() as cur:
        tabla_existe = db.table_exists(con, table)

        if not tabla_existe:
            # La tabla debería existir ya (creada por migración), pero como
            # safety net la creamos dinámicamente con el esquema del DataFrame.
            cols_def = ", ".join(f'"{c}" text' for c in df.columns)
            cur.execute(f'CREATE TABLE IF NOT EXISTS simulador."{table}" ({cols_def})')
        else:
            df = _align_to_table(con, table, df)

        # Borrar las filas que van a ser reemplazadas
        keys_df = df[list(key)].drop_duplicates()
        conditions = " AND ".join(f'"{k}" IS NOT DISTINCT FROM %s' for k in key)
        for _, row in keys_df.iterrows():
            cur.execute(
                f'DELETE FROM "{table}" WHERE {conditions}',
                [_clean_val(row[k]) for k in key],
            )

        # Insertar las filas nuevas
        if len(df) == 0:
            return

        cols = list(df.columns)
        col_names = ", ".join(f'"{c}"' for c in cols)
        data = [
            tuple(_clean_val(row[c]) for c in cols)
            for _, row in df.iterrows()
        ]
        psycopg2.extras.execute_values(
            cur,
            f'INSERT INTO "{table}" ({col_names}) VALUES %s',
            data,
            page_size=500,
        )


def _archivar(path: Path, dest_dir: Path | None = None) -> None:
    """Mueve un archivo ya procesado a la carpeta de destino."""
    dest_dir = dest_dir if dest_dir is not None else path.parent / "procesados"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    if dest.exists():
        dest = dest_dir / f"{path.stem}_{datetime.now():%Y%m%d%H%M%S}{path.suffix}"
    path.rename(dest)
    print(f"    archivado -> {dest}")


def _preparar_consumo(df: pd.DataFrame, path: Path, mes: str | None):
    """Completa las columnas que el export CRUDO de consumo no trae."""
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
        print("    (export sin 'Convenio ID': queda NULL)")
    return df


def _process_file(con, tipo: str | None, ds: dict | None, path: Path,
                  rebuild: bool, mes: str | None = None) -> tuple[int, bool]:
    """Procesa un archivo. Devuelve (filas_insertadas, procesado_ok)."""
    file_hash = _file_hash(path)
    if not rebuild and _already_ingested(con, file_hash):
        print(f"  - {path.name}: ya ingerido, saltando")
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
            print(f"  ! {path.name}: no parece consumo ni valores — saltando")
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

    filas_antes = len(df)
    df = xu.clean_dataset(df, ds["numeric"])
    descartadas = filas_antes - len(df)
    if descartadas:
        print(f"    ({descartadas} fila(s) de total/sin clave/duplicadas descartadas)")

    try:
        _upsert(con, ds["table"], ds["key"], df)
        with con.cursor() as cur:
            cur.execute(
                f'INSERT INTO "{db.INGEST_LOG_TABLE}" '
                f'(file_hash, file_name, tipo, rows, ingested_at) '
                f'VALUES (%s, %s, %s, %s, %s) ON CONFLICT (file_hash) DO NOTHING',
                [file_hash, path.name, tipo, len(df), datetime.now()],
            )
        con.commit()
    except Exception as e:
        con.rollback()
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
        with con.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{db.INGEST_LOG_TABLE}"')
            files = cur.fetchone()[0]
        print(f"  - archivos ingeridos: {files}")


# ============================================================================
# MAIN
# ============================================================================
def main() -> int:
    ap = argparse.ArgumentParser(description="Ingesta de Excel -> Supabase")
    ap.add_argument("--rebuild", action="store_true",
                    help="Borra y reconstruye la base desde cero")
    ap.add_argument("--status", action="store_true",
                    help="Solo muestra qué hay cargado y sale")
    ap.add_argument("--solo", metavar="ARCHIVO", default=None,
                    help="Procesa únicamente el archivo con ese nombre exacto")
    ap.add_argument("--archivar", action="store_true",
                    help="Mueve los archivos procesados OK a procesados/")
    ap.add_argument("--mes", metavar="MM-YYYY", default=None,
                    help="Período de los archivos de consumo SIN columna 'Mes'")
    args = ap.parse_args()

    if args.mes and not re.fullmatch(r"\d{2}-\d{4}", args.mes):
        print(f"--mes debe ser MM-YYYY (recibido: {args.mes!r})")
        return 1

    try:
        con = db.get_connection()
    except Exception as e:
        print(f"ERROR: no se pudo conectar a la base de datos.\n{e}")
        print("Asegurate de tener DATABASE_URL configurado.")
        return 1

    _ensure_log(con)
    con.commit()

    if args.status:
        _print_status(con)
        con.close()
        return 0

    if args.rebuild:
        print("Reconstruyendo base desde cero...")
        with con.cursor() as cur:
            for ds in DATASETS.values():
                cur.execute(f'DELETE FROM simulador."{ds["table"]}"')
            cur.execute(f'DELETE FROM simulador."{db.INGEST_LOG_TABLE}"')
        con.commit()

    total = 0
    for tipo, ds in DATASETS.items():
        ds["dir"].mkdir(parents=True, exist_ok=True)
        files = sorted([*ds["dir"].glob("*.xlsx"), *ds["dir"].glob("*.csv")])
        if args.solo:
            files = [p for p in files if p.name == args.solo]
        print(f"[{tipo}] {len(files)} archivo(s) en {ds['dir']}")
        for path in files:
            filas, ok = _process_file(con, tipo, ds, path, args.rebuild, args.mes)
            total += filas
            if ok and args.archivar:
                _archivar(path)

    # Bandeja unificada
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    PROCESADO_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted([*INBOX_DIR.glob("*.xlsx"), *INBOX_DIR.glob("*.csv")])
    if args.solo:
        files = [p for p in files if p.name == args.solo]
    print(f"[a_procesar] {len(files)} archivo(s) en {INBOX_DIR}")
    for path in files:
        filas, ok = _process_file(con, None, None, path, args.rebuild, args.mes)
        total += filas
        if ok:
            _archivar(path, PROCESADO_DIR)

    print(f"\nListo. {total:,} filas procesadas en esta corrida.")
    _print_status(con)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
