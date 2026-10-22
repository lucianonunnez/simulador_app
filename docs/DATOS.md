# Datos

## Datasets

### Consumo

Cantidad e importe facturado por prestador, prestación y mes.

| Columna | Tipo | Notas |
|---|---|---|
| `Prestador ID` / `Prestador Desc` | int / str | |
| `Convenio ID` / `Convenio Desc` | int / str | El export crudo no trae `Convenio ID`; queda nulo y el cruce usa Prestador + Prestación. |
| `Mes` | `MM-YYYY` | Período de liquidación. |
| `Tipo Categoria`, `Megacuenta`, `Gama`, `Cartilla` | str | Segmentación comercial. |
| `Tipo Clase CM` | str | Ámbito: `Ambulatorio`, `Internación`, … |
| `Nomenclador` | str | Agrupador de prestaciones. |
| `Prestacion ID` / `Prestacion Desc` | int / str | |
| `Cantidad CM` | num | |
| `Importe CM` | num | |

Clave de upsert: `(Prestador ID, Mes)`.

### Valores (tarifario)

| Columna | Tipo | Notas |
|---|---|---|
| `Prestador ID` / `Prestador Desc` | int / str | |
| `Convenio ID` / `Convenio Desc` | int / str | |
| `Prestacion ID` / `Prestacion Desc` | int / str | |
| `Mes Vigencia` | `MM-YYYY` | Inicio de vigencia de la tarifa. |
| `Valor Convenido a HOY` | num | |

Clave de upsert: `(Prestador ID, Mes Vigencia)`. El simulador toma, para cada
prestación, la vigencia más reciente.

## Origen

Los datos productivos provienen de dos reportes de MicroStrategy (proyecto
*Costo Médico*): **consumo** y **valores**. Se descargan manualmente por
grupos de prestadores y/o períodos, porque el origen no exporta más de ~1M
filas por vez; la ingesta está diseñada para cargar por partes.

### Formato de los exports

`core/excel_utils.py` normaliza el formato crudo al contrato:

- **Formato y encoding variables:** xlsx o CSV (UTF-8 con BOM, o Mac Roman con
  finales de línea CR). Se detecta por contenido.
- **Columnas en pares ID/descripción** con encabezados `Unnamed: N` y orden
  variable según el reporte (`normalize_mstr_columns`).
- **Números como texto:** coma de miles, espacios y negativos contables
  (`"1,130 "`, `"(5,477,196)"`) → `to_numeric_tolerante`.
- **Meses en español** (`"Mayo 2026"`) → `MM-YYYY`.
- **Filas de total** al final → se descartan.

### Limitaciones del export de consumo

- **No incluye el período.** Se asigna desde el nombre del archivo
  (`05-2026-Consumo.xlsx`, `consumo 12-2025.xlsx`) o con `--mes MM-YYYY`. Solo
  es válido para exports de un único mes; para exports multi-mes hay que
  agregar el atributo *Mes* al reporte de origen.
- **No incluye `Convenio ID`** (ver arriba).

### Internación

Los módulos día de internación (por sala: UTI, clínica, pediatría, etc.) no
vienen en el tarifario estándar sino en una planilla aparte, en formato ancho
(una columna por mes de vigencia). Hoy quedan fuera de la simulación
(equivalen a *No pauta*). Integrarlos requiere ingerir esa planilla como
fuente de tarifas adicional, pasándola a formato largo.

### Pauta de aumento

La pauta de referencia sale del IPC del INDEC (`core/indec.py`). En los
workbooks de negociación, *Valor propuesto* = `valor actual × (1 + pauta)` y
*Valor solicitado* es el monto que pide el prestador.

## Ingesta

```bash
python scripts/ingest.py              # incremental desde data/raw/{consumo,valores}/
python scripts/ingest.py --archivar   # procesa la bandeja data/a_procesar/ y archiva
python scripts/ingest.py --rebuild    # reconstruye la base
python scripts/ingest.py --status
python scripts/ingest.py --solo ARCHIVO --mes MM-YYYY
```

- **Bandeja unificada** (`data/a_procesar/`): el tipo de dataset se detecta
  por contenido; lo procesado se mueve a `data/procesado/`.
- **Idempotencia:** hash SHA-256 + mes asignado. Re-ingerir el mismo archivo
  se saltea; `--force` lo fuerza.
- **Upsert destructivo por par:** un re-export parcial de un
  `(Prestador, Mes)` reemplaza todas las filas de ese par. La ingesta avisa si
  el archivo nuevo trae menos de la mitad de filas que las que reemplaza.

## Datos de demo

`scripts/generate_demo_data.py` genera un dataset sintético con el mismo
contrato: 8 prestadores ficticios (hasta 12), 24 meses, actualizaciones de
tarifa trimestrales, estacionalidad y ~1 % de desvíos inyectados para el
Módulo 2. Es determinístico (`--seed`).

```bash
python scripts/generate_demo_data.py --ingest --meses 36 --prestadores 12
```

Todo `data/` está excluido del control de versiones y de la imagen Docker.
