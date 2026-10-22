# Arquitectura

## Vista general

```
                    ┌──────────────────────────── Streamlit (src/) ───────────────────────────┐
 exports            │                                                                          │
 MicroStrategy ──►  │  modules/  ── orquesta cada página (Simulador, Desvíos, Predicción ML)   │
 (xlsx / csv)       │     │                                                                    │
     │              │  ui/       ── controles, tabs, gráficos, tema y formatos es-AR           │
     ▼              │     │                                                                    │
 scripts/ingest.py  │  core/     ── dominio: carga de datos, simulación, anomalías, ML, auth   │
     │              │     │                                                                    │
     ▼              └─────┼────────────────────────────────────────────────────────────────────┘
 ┌──────────────┐         │ consultas con filtros (prestador / mes)
 │ DuckDB local │ ◄───────┤
 └──────────────┘         │
 ┌──────────────┐         │
 │ PostgreSQL   │ ◄───────┘ (opcional, si hay SUPABASE_DATABASE_URL)
 └──────────────┘
```

La aplicación es un monolito Streamlit organizado en tres capas:

| Capa | Responsabilidad | Ejemplos |
|---|---|---|
| `core/` | Lógica de dominio, sin dependencias de UI salvo el caché de Streamlit. | `simulator.py`, `anomaly.py`, `ml_predictor.py`, `data_loader.py` |
| `ui/` | Componentes de presentación reutilizables. | `simulator_tabs.py`, `theme.py`, `formatters.py` |
| `modules/` | Composición de cada página a partir de `core` + `ui`. | `module1.py` … `module3.py` |

`streamlit_app.py` resuelve autenticación, navegación y preserva el estado de
los widgets al cambiar de módulo.

## Datos

- **Ingesta** (`scripts/ingest.py`, también invocable desde la UI vía
  `core/ingest_runner.py`): lee exports de MicroStrategy (xlsx o csv), los
  normaliza al contrato de columnas (`core/excel_utils.py`) y hace upsert en
  DuckDB por `(Prestador ID, Mes)` para consumo y `(Prestador ID, Mes Vigencia)`
  para valores. Es idempotente: cada archivo se identifica por hash SHA-256 +
  mes asignado.
- **Lectura** (`core/data_loader.py`): consultas con filtros empujados a SQL,
  conexión read-only cacheada y un cursor por consulta (las conexiones DuckDB
  no son thread-safe y Streamlit atiende cada sesión en un hilo). El caché se
  invalida por huella del archivo de base, no solo por TTL.
- **Fuente remota** (`core/db_remote.py`): mismo contrato en un schema de
  PostgreSQL. Se activa solo si hay configuración; si no, el módulo ni se
  importa.

Contrato de columnas y formato de origen: [`DATOS.md`](DATOS.md).

## Motor de simulación

`core/simulator.py`:

1. Deduplica el tarifario quedándose con la vigencia más reciente por
   prestador / convenio / prestación (parser de meses único: tolera
   `MM-YYYY`, nombres en español y datetimes).
2. Cruza consumo con tarifas. La clave suma `Tipo Clase CM` cuando ambos lados
   la traen, para que una prestación pueda valer distinto según el ámbito.
3. Aplica aumentos por capas (general, por nomenclador, por prestación; en % o
   $) y exclusiones *No pauta*, y proyecta escenarios *Solicitado* y
   *Propuesto*.
4. Reporta la **cobertura** del cruce por filas y por importe: con datos
   reales, ~98 % de las filas tienen tarifa pero solo ~73 % del importe, así
   que la UI muestra ambas.

El motor está validado contra workbooks de negociación reales
(`tests/test_simulaciones_negocio.py` y el validador de la UI,
`core/workbook_validacion.py`).

## Detección de desvíos

`core/anomaly.py` implementa dos enfoques:

- **Temporal:** z-score o IQR sobre ventana móvil por serie.
- **Estructural:** percentil o z-score de cada entidad contra sus pares.

## Modelos

`core/ml_predictor.py` reconstruye el panel mensual (prestador × prestación),
genera lags (1–3), medias móviles (3 y 6) y estacionalidad, y puntúa con los
modelos de `models/`.

| Modelo | Métrica | R² (test) | MAE (test) |
|---|---|---:|---:|
| LightGBM | importe | 0,67 | 492.655 |
| LightGBM | precio | 0,45 | 56.143 |
| LightGBM | cantidad | 0,94 | 6,3 |
| Red neuronal | importe / precio / cantidad | 0,18 / 0,36 / 0,28 | — |

Entrenamiento: 42.560 filas / test 12.160 (`models/metricas_final.json`).

### Limitaciones conocidas

- **Backtest, no forecast.** El panel llega hasta el último mes observado: la
  pestaña *Predicción* re-puntúa meses históricos. Extender el panel a `t+1`
  con lags del pasado es el siguiente paso natural.
- **Leakage en `fue_activo`.** La feature indica si la entidad facturó en el
  mes objetivo; en cantidad equivale a `cantidad > 0`, lo que infla el R².
  Los `activo_lag_*` sí son legítimos. Requiere re-entrenar sin ella.
- **Categóricas.** LightGBM mapea categorías por código entero; hoy se derivan
  del dataset en uso. Para paridad exacta conviene exportar las categorías de
  entrenamiento en `metricas_final.json` y reconstruir con
  `pd.Categorical(..., categories=...)`.
- **Reproducibilidad.** El pipeline de entrenamiento vive fuera del repo; no
  hay versionado de modelos ni intervalos de predicción.

## Autenticación y sesión

- `streamlit-authenticator` con usuarios en `secrets.toml` (bcrypt).
- `core/ratelimit.py`: bloqueo por usuario intentado (5 fallos / 10 min) y por
  IP (15 fallos), 15 min de bloqueo. Vive en memoria del proceso.
- `core/audit.py`: eventos de login en JSON Lines.

## Decisiones de diseño

| Decisión | Motivo |
|---|---|
| DuckDB embebido como fuente por defecto | Los datos son sensibles y en el entorno original no podían salir de la máquina; DuckDB da SQL columnar con push-down y spill a disco sin servidor. |
| PostgreSQL como fuente opcional | Habilita uso multiusuario/centralizado sin cambiar el contrato ni el código de los módulos. |
| Ingesta manual + idempotente | Los exports se descargan a mano por límites del origen (~1M filas por export); el upsert por `(Prestador, Mes)` permite cargar por partes. |
| TensorFlow opcional | Agrega ~950 MB a la imagen y la red no supera a LightGBM; el módulo degrada a LightGBM-only. |

## Evolución sugerida

1. Desacoplar `core/` de `st.cache_*` (inyectar el caché) para reutilizarlo
   fuera de Streamlit.
2. Exponer `core/` como API (FastAPI) y dejar Streamlit como cliente.
3. Mover el estado de rate-limit a un store compartido para poder escalar
   horizontalmente.
4. Pipeline de entrenamiento versionado (features + modelos + métricas).
