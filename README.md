---
title: Simulador Costo Médico
emoji: 🏥
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 8501
pinned: false
license: other
---

# 🏥 Simulador de Costo Médico

[![CI](https://github.com/lucianonunnez/simulador_app/actions/workflows/ci.yml/badge.svg)](https://github.com/lucianonunnez/simulador_app/actions/workflows/ci.yml)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue)
![Versión](https://img.shields.io/badge/versión-v0.6.0-informational)

Aplicación interna (Streamlit) para análisis y simulación de costo médico de
prestadores. Trabaja con datos **agregados por prestador/prestación** (nunca a
nivel paciente). Estado: **operativa en v0.6.0**, uso interno.

## Módulos

1. **Simulador de Aumentos** — Proyección de impacto financiero por cambios de
   tarifas: escenarios *Solicitado vs Propuesto*, aumentos en capas mixtos
   (%/$ por prestación o nomenclador), Extrapauta, exclusiones "No pauta",
   tarifario fechado con cobertura del merge visible, comparativa por
   prestador, contexto de inflación (IPC INDEC) y **validador contra workbooks
   reales de negociación** (reconciliación fila a fila y por headline).
2. **Detección de Desvíos** — Anomalías en costos por prestador, prestación o
   grupo: análisis **temporal** (z-score / IQR con ventana móvil) y
   **estructural** (percentil / z-score contra pares).
3. **Predicción ML** — Pronóstico de costo con modelos pre-entrenados
   (LightGBM + red neuronal Keras) para importe, cantidad y precio, con
   comparativa de modelos y métricas de performance.

## Fuentes de datos

La app resuelve la fuente en runtime, con fallback automático:

| Fuente | Cuándo se usa | Detalle |
|---|---|---|
| **Supabase / PostgreSQL** | Si hay bloque `[supabase]` en secrets (o `SUPABASE_DATABASE_URL`) | Fuente de verdad central y multiusuario. Schema `simulador`. Ver [`docs/SUPABASE.md`](docs/SUPABASE.md) |
| **DuckDB local** | Default sin config de Supabase | `data/simulador.duckdb`, 100% local |
| **Archivos subidos** | Siempre disponible desde el sidebar («Carga de datos») | xlsx/csv propios, modos *Base / Solo subidos / Combinar* |

> La ingesta (`scripts/ingest.py`) hoy escribe **solo a DuckDB local**; la
> carga hacia Supabase se hace por separado (ver `docs/SUPABASE.md`).

## Ingesta de datos

Los datos se descargan **manualmente** de MicroStrategy (política de IT: sin
sincronización automática). Detalle de extracción en
[`FUENTE_DATOS.md`](FUENTE_DATOS.md). Dos rutas:

**a) Bandeja unificada** — dejar los archivos (xlsx **o csv** crudos) en
`data/a_procesar/` con el período en el nombre (ej. `05-2026-Consumo-1584.xlsx`)
y usar el botón **«Ingerir y unificar ahora»** dentro de la app, o:

```bash
python scripts/ingest.py --archivar   # ingiere y archiva a data/procesado/
```

**b) Carpetas clásicas** — dejar los Excel en `data/raw/consumo/` y
`data/raw/valores/`, después:

```bash
python scripts/ingest.py            # ingesta incremental e idempotente
python scripts/ingest.py --rebuild  # reconstruye la base desde cero
python scripts/ingest.py --status   # ver qué hay cargado
python scripts/ingest.py --solo ARCHIVO --mes MM-YYYY  # un archivo puntual
```

La ingesta es idempotente (hash SHA-256 por archivo) con upsert por
`(Prestador ID, Mes)` y tolera el formato crudo de MicroStrategy (encodings
raros, columnas `Unnamed:`, números como texto).

## Cómo correrlo

Guía completa paso a paso en [`CÓMO_CORRERLO.md`](CÓMO_CORRERLO.md). Resumen:

```bash
# 1. Python 3.11 + dependencias
pip install -r requirements.txt

# 2. Modelos ML (van por Git LFS)
git lfs pull

# 3. Credenciales (sin esto la app NO arranca):
#    copiar .streamlit/secrets.toml.example -> .streamlit/secrets.toml
#    y generar cookie_key + hashes bcrypt con:
python scripts/gen_credentials.py

# 4. Levantar (desde la raíz del repo: los paths data/, models/, logs/ son relativos)
streamlit run src/streamlit_app.py
```

En Windows corporativo (proxy + OneDrive): usar `deploy/setup.ps1`, que arma el
venv fuera de OneDrive e instala con `--trusted-host`.

## Autenticación y seguridad

- Login obligatorio con `streamlit-authenticator` (passwords **hasheados con
  bcrypt**, nunca en texto plano) definido en `.streamlit/secrets.toml`
  (gitignoreado; plantilla en `.streamlit/secrets.toml.example`).
- **Lockout anti fuerza bruta**: 5 intentos fallidos en 10 min → bloqueo 15 min.
- **Auditoría de login** en JSON Lines: `logs/auth_audit.log` (con IP vía
  `X-Forwarded-For` detrás de proxy).
- Datos y secrets fuera del repo (`data/`, `secrets.toml` gitignoreados).
- Hardening de despliegue (binding, TLS, firewall):
  [`docs/DESPLIEGUE_SEGURO.md`](docs/DESPLIEGUE_SEGURO.md).

## Despliegue

- **LAN segura (actual):** `deploy/run_secure.ps1` levanta Streamlit en
  `127.0.0.1` y **Caddy** como reverse proxy TLS en `:8443`
  (`deploy/Caddyfile`). Ajustar IP/rutas a tu equipo antes de usar.
- **Docker:** `docker build -t simulador . && docker run -p 8501:8501 ...`
  La imagen **no incluye** `data/` ni `secrets.toml`: montar volumen e
  inyectar secrets en runtime. Ojo: `git lfs pull` antes del build para no
  copiar punteros LFS a la imagen.
- **Hugging Face Spaces:** soportado por el front-matter de este README
  (sdk: docker). Requiere `enableCORS/enableXsrfProtection = false` en
  `.streamlit/config.toml` (hoy endurecido para LAN) y secrets del Space.

## Modelos ML (`models/`)

Modelos pre-entrenados fuera del repo (Colab): 3 **LightGBM** (`.txt`) y 3
redes **Keras** (`.keras`) — una por métrica (importe, cantidad, precio) — más
`scalers_pablo.pkl` (**Git LFS**, correr `git lfs pull`) y las métricas de
entrenamiento en `metricas_*.json`. La app detecta punteros LFS sin resolver y
avisa en lugar de fallar.

## Stack

Streamlit 1.38 · pandas ≥2.2 / NumPy · Plotly · DuckDB · psycopg2 (Supabase) ·
scikit-learn 1.6.1 · LightGBM · TensorFlow/Keras (`tensorflow-cpu <2.17`) ·
streamlit-authenticator + bcrypt · openpyxl · requests (API INDEC).

## Desarrollo y calidad

```bash
pip install -r requirements-dev.txt
ruff check src tests            # lint
PYTHONPATH=src pytest tests/ -q # tests
```

- **CI** en GitHub Actions (`.github/workflows/ci.yml`): ruff + pytest en
  Python 3.11 para cada push a `main` y PR (instala liviano, sin TF/LightGBM).
- **Regresión contra simulaciones reales del negocio**
  (`tests/test_simulaciones_negocio.py`): reconcilia el motor de la app contra
  workbooks ya resueltos por el equipo de negociación. Los `.xlsx` son datos
  sensibles y **no se versionan**: ver
  [`tests/fixtures/simulaciones/README.md`](tests/fixtures/simulaciones/README.md)
  (o `SIM_FIXTURES_DIR`). Sin los archivos, esos tests se saltean.

## Estructura del repo

```
src/
├── core/      → lógica pura: datos, simulación, anomalías, ML, auth-support
├── ui/        → presentación: controles, tabs, tema, formatos es-AR
├── modules/   → orquestación: una página por módulo
└── streamlit_app.py → entry point
scripts/       → ingest.py, gen_credentials.py
models/        → modelos ML pre-entrenados (LFS para .pkl)
deploy/        → setup.ps1, run_secure.ps1, Caddyfile
docs/          → SUPABASE.md, DESPLIEGUE_SEGURO.md
tests/         → smoke + regresión de negocio + conector remoto
data/          → (no versionada) DuckDB local, bandeja de ingesta
```

## Documentación

| Documento | Contenido |
|---|---|
| [`ARQUITECTURA.md`](ARQUITECTURA.md) | Cómo está armado y plan de evolución |
| [`FUENTE_DATOS.md`](FUENTE_DATOS.md) | Extracción desde MicroStrategy |
| [`CÓMO_CORRERLO.md`](CÓMO_CORRERLO.md) | Guía de instalación y ejecución |
| [`docs/SUPABASE.md`](docs/SUPABASE.md) | Fuente de datos remota (PostgreSQL) |
| [`docs/DESPLIEGUE_SEGURO.md`](docs/DESPLIEGUE_SEGURO.md) | Hardening del despliegue en LAN |

## Estado y roadmap

- ✅ Fase 0 (limpieza) y Fase 1 (DuckDB local + ingesta) — completadas.
- ✅ Conector Supabase/PostgreSQL (lectura) con fallback a DuckDB.
- ✅ CI, auditoría de login, rate-limit, validador de workbooks.
- ⏭️ Ingesta hacia Supabase; rol read-only en Postgres (hoy la conexión usa
  `postgres`, que bypasea RLS).
- ⏭️ Compliance de datos médicos en cloud antes de productivo.
- ⏭️ Fases 2–3: backend FastAPI + frontend dedicado (ver `ARQUITECTURA.md`).
