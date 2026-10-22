#!/usr/bin/env python3
"""
Genera un dataset SINTÉTICO de demo (consumo + valores) con el mismo contrato
de columnas que los exports de MicroStrategy.

Sirve para levantar la app en un entorno sin acceso a los datos reales
(evaluación, CI, cluster de pruebas). Ningún valor sale de datos productivos:
prestadores, convenios y montos son inventados con una semilla fija, así que
el resultado es reproducible.

Uso:
    python scripts/generate_demo_data.py                 # -> data/raw/{consumo,valores}/
    python scripts/generate_demo_data.py --ingest        # genera + carga en DuckDB
    python scripts/generate_demo_data.py --meses 36 --prestadores 12 --seed 7

Lo generado tiene:
  - Tarifas con actualizaciones trimestrales (pauta ~ inflación + ruido).
  - Consumo mensual con estacionalidad, tendencia y ruido.
  - Algunos desvíos inyectados (picos de importe/cantidad) para que el
    Módulo 2 tenga algo que detectar.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"

PRESTADORES = [
    (900101, "Sanatorio Central Demo"),
    (900102, "Clínica del Parque Demo"),
    (900103, "Hospital Privado Norte Demo"),
    (900104, "Instituto de Diagnóstico Demo"),
    (900105, "Centro Médico Sur Demo"),
    (900106, "Clínica San Martín Demo"),
    (900107, "Policlínico Oeste Demo"),
    (900108, "Centro Oncológico Demo"),
    (900109, "Laboratorio Integral Demo"),
    (900110, "Clínica Pediátrica Demo"),
    (900111, "Centro de Rehabilitación Demo"),
    (900112, "Instituto Cardiovascular Demo"),
]

# (Nomenclador, Tipo Clase CM, prefijo de código, valor base, consumo base, descripciones)
CATALOGO = [
    ("Consultas", "Ambulatorio", 420100, 18_000, 140,
     ["Consulta médica", "Consulta especialista", "Consulta pediátrica",
      "Consulta de guardia", "Consulta domiciliaria"]),
    ("Laboratorio", "Ambulatorio", 660100, 4_500, 320,
     ["Hemograma completo", "Glucemia", "Uremia", "Creatinina", "Hepatograma",
      "Perfil lipídico", "TSH", "Orina completa", "Eritrosedimentación",
      "Ionograma"]),
    ("Diagnóstico por Imágenes", "Ambulatorio", 180100, 42_000, 60,
     ["Radiografía de tórax", "Ecografía abdominal", "Tomografía de cerebro",
      "Resonancia de rodilla", "Mamografía bilateral", "Ecodoppler venoso"]),
    ("Prácticas Ambulatorias", "Ambulatorio", 170100, 26_000, 45,
     ["Electrocardiograma", "Ergometría", "Holter 24 hs", "Espirometría",
      "Audiometría", "Endoscopía digestiva alta"]),
    ("Intervenciones Quirurgicas", "Internación", 120100, 480_000, 6,
     ["Colecistectomía laparoscópica", "Apendicectomía", "Hernioplastia inguinal",
      "Artroscopía de rodilla", "Cesárea", "Reemplazo total de cadera"]),
    ("Prestaciones Sanatoriales", "Internación", 431000, 210_000, 30,
     ["Día de internación clínica", "Día de UTI", "Día de unidad coronaria",
      "Día de internación pediátrica", "Derecho de quirófano"]),
    ("Medicamentos", "Internación", 2000100, 9_500, 90,
     ["Ceftriaxona 1 g", "Omeprazol 40 mg iny.", "Enoxaparina 40 mg",
      "Paracetamol 1 g iny.", "Vancomicina 500 mg"]),
]

CONVENIOS = [
    (5101, "Convenio General - Ambulatorio"),
    (5102, "Convenio General - Internación"),
]
CATEGORIAS = ["Afinidad", "Corporativo", "Directo"]
MEGACUENTAS = ["SOCIOS DIRECTOS", "EMPRESAS", "OBRAS SOCIALES"]
GAMAS = ["Media", "Media superior", "Alta"]
CARTILLAS = ["PLAN 200", "PLAN 300", "PLAN 400"]


def _meses(n: int, hasta: pd.Period) -> list[pd.Period]:
    return list(pd.period_range(end=hasta, periods=n, freq="M"))


def _catalogo_prestaciones() -> pd.DataFrame:
    filas = []
    for nomenclador, clase, prefijo, valor, consumo, descs in CATALOGO:
        for i, desc in enumerate(descs):
            filas.append({
                "Nomenclador": nomenclador,
                "Tipo Clase CM": clase,
                "Prestacion ID": prefijo + i + 1,
                "Prestacion Desc": desc,
                "valor_base": valor * (0.8 + 0.08 * i),
                "consumo_base": consumo,
                "convenio": CONVENIOS[1] if clase == "Internación" else CONVENIOS[0],
            })
    return pd.DataFrame(filas)


def generar(meses: int, n_prestadores: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    periodos = _meses(meses, pd.Period(pd.Timestamp.today(), freq="M") - 1)
    catalogo = _catalogo_prestaciones()

    consumo, valores = [], []
    for pid, pdesc in PRESTADORES[:n_prestadores]:
        escala_precio = rng.uniform(0.75, 1.35)    # prestadores más caros/baratos
        escala_volumen = rng.uniform(0.4, 2.0)
        # Cada prestador ofrece un subconjunto del catálogo.
        oferta = catalogo.sample(frac=rng.uniform(0.6, 1.0), random_state=int(rng.integers(1e9)))

        for _, p in oferta.iterrows():
            valor = p["valor_base"] * escala_precio * rng.uniform(0.9, 1.1)
            conv_id, conv_desc = p["convenio"]
            for k, per in enumerate(periodos):
                # Tarifa inicial + actualización trimestral (pauta 6-12%).
                actualiza = k > 0 and per.month % 3 == 1
                if actualiza:
                    valor *= 1 + rng.uniform(0.06, 0.12)
                if k == 0 or actualiza:
                    valores.append({
                        "Prestador ID": pid, "Prestador Desc": pdesc,
                        "Convenio ID": conv_id, "Convenio Desc": conv_desc,
                        "Prestacion ID": p["Prestacion ID"],
                        "Prestacion Desc": p["Prestacion Desc"],
                        "Mes Vigencia": per.strftime("%m-%Y"),
                        "Valor Convenido a HOY": round(valor, 2),
                    })

                estacional = 1 + 0.15 * np.sin(2 * np.pi * (per.month - 4) / 12)
                tendencia = 1 + 0.01 * k
                lam = max(p["consumo_base"] * escala_volumen * estacional * tendencia, 0.5)
                cantidad = int(rng.poisson(lam))
                if cantidad == 0:
                    continue
                precio = valor * rng.uniform(0.97, 1.03)
                # Desvíos inyectados (~1%): facturación anómala.
                if rng.random() < 0.01:
                    if rng.random() < 0.5:
                        cantidad = int(cantidad * rng.uniform(2.5, 4.0))
                    else:
                        precio *= rng.uniform(1.8, 2.6)

                consumo.append({
                    "Prestador ID": pid, "Prestador Desc": pdesc,
                    "Convenio ID": conv_id, "Convenio Desc": conv_desc,
                    "Mes": per.strftime("%m-%Y"),
                    "Tipo Categoria": rng.choice(CATEGORIAS),
                    "Megacuenta": rng.choice(MEGACUENTAS),
                    "Gama": rng.choice(GAMAS),
                    "Cartilla": rng.choice(CARTILLAS),
                    "Tipo Clase CM": p["Tipo Clase CM"],
                    "Nomenclador": p["Nomenclador"],
                    "Prestacion ID": p["Prestacion ID"],
                    "Prestacion Desc": p["Prestacion Desc"],
                    "Cantidad CM": cantidad,
                    "Importe CM": round(cantidad * precio, 2),
                })

    return pd.DataFrame(consumo), pd.DataFrame(valores)


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera datos sintéticos de demo")
    ap.add_argument("--meses", type=int, default=24, help="meses de historia (default 24)")
    ap.add_argument("--prestadores", type=int, default=8,
                    help=f"cantidad de prestadores (máx {len(PRESTADORES)})")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=RAW_DIR, help="directorio de salida")
    ap.add_argument("--ingest", action="store_true",
                    help="además ejecuta scripts/ingest.py --rebuild")
    args = ap.parse_args()

    n = min(max(args.prestadores, 1), len(PRESTADORES))
    consumo, valores = generar(args.meses, n, args.seed)

    (args.out / "consumo").mkdir(parents=True, exist_ok=True)
    (args.out / "valores").mkdir(parents=True, exist_ok=True)
    f_consumo = args.out / "consumo" / "demo_consumo.csv"
    f_valores = args.out / "valores" / "demo_valores.csv"
    consumo.to_csv(f_consumo, index=False, encoding="utf-8")
    valores.to_csv(f_valores, index=False, encoding="utf-8")

    print(f"consumo: {len(consumo):,} filas -> {f_consumo.relative_to(ROOT)}")
    print(f"valores: {len(valores):,} filas -> {f_valores.relative_to(ROOT)}")

    if args.ingest:
        return subprocess.call(
            [sys.executable, str(ROOT / "scripts" / "ingest.py"), "--rebuild"], cwd=ROOT
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
