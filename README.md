# Simulador de Costo Médico

Aplicación web (Streamlit) para analizar y simular el costo médico de
prestadores a partir de datos agregados de consumo y tarifas (nunca a nivel
paciente).

| Módulo | Qué resuelve |
|---|---|
| **1. Simulador de aumentos** | Impacto financiero de cambios de tarifa: escenarios *Solicitado vs Propuesto*, aumentos por capas (% o $ por prestación / nomenclador), Extrapauta, exclusiones *No pauta*, cobertura del tarifario y validación contra workbooks de negociación. |
| **2. Detección de desvíos** | Anomalías de costo por prestador, prestación o grupo: análisis temporal (z-score / IQR con ventana móvil) y estructural (percentil / z-score contra pares). |
| **3. Predicción ML** | Backtest de importe, cantidad y precio con modelos pre-entrenados (LightGBM; red neuronal Keras opcional), comparativa de modelos y métricas. |

**Stack:** Python 3.11 · Streamlit · pandas · DuckDB · PostgreSQL (opcional) ·
LightGBM · scikit-learn · TensorFlow/Keras (opcional) · Plotly.

---

## Inicio rápido

El paquete incluye un generador de **datos sintéticos**, así que la app se
puede levantar completa sin acceso a datos productivos.

### Docker Compose (recomendado)

```bash
cp .env.example .env          # completar SIMULADOR_PASSWORD
docker compose up --build
```

Abrir <http://localhost:8501> e ingresar con `SIMULADOR_USER` (default
`admin`) y la contraseña definida. En el primer arranque el contenedor genera
el dataset de demo y lo carga en DuckDB (volumen `simulador-data`).

### Local

```bash
make install demo-data        # venv + dependencias + datos sintéticos
SIMULADOR_PASSWORD='...' .venv/bin/python scripts/gen_credentials.py --from-env
make run
```

Sin `make`: `python3.11 -m venv .venv`, `pip install -r requirements.txt`,
`python scripts/generate_demo_data.py --ingest` y
`streamlit run src/streamlit_app.py` desde la raíz del repo.

### Kubernetes

Manifiestos en [`deploy/k8s/`](deploy/k8s/) (Deployment, Service, PVC y
ejemplos de Secret e Ingress):

```bash
docker build -t <registry>/simulador-cm:0.6.0 . && docker push <registry>/simulador-cm:0.6.0
kubectl create secret generic simulador-credentials \
  --from-literal=SIMULADOR_USER=admin \
  --from-literal=SIMULADOR_PASSWORD='...' \
  --from-literal=SIMULADOR_COOKIE_KEY="$(openssl rand -hex 32)"
kubectl apply -k deploy/k8s/     # ajustar la imagen en kustomization.yaml
```

Detalle de configuración, recursos y consideraciones de escalado en
[`docs/DESPLIEGUE.md`](docs/DESPLIEGUE.md).

---

## Configuración

Toda la configuración de runtime entra por variables de entorno o por
`.streamlit/secrets.toml` (nunca se versiona ni se incluye en la imagen).

| Variable | Default | Descripción |
|---|---|---|
| `SIMULADOR_USER` | `admin` | Usuario de acceso (si no se monta un `secrets.toml`). |
| `SIMULADOR_PASSWORD` | — | Contraseña del usuario. Obligatoria sin `secrets.toml`. |
| `SIMULADOR_COOKIE_KEY` | aleatoria | Clave de firma de la cookie de sesión. Fijarla mantiene las sesiones entre reinicios. |
| `DEMO_DATA` | `false` | `true`: si no hay base, genera el dataset sintético al arrancar. |
| `SUPABASE_DATABASE_URL` | — | Fuente PostgreSQL en lugar de DuckDB local. Ver [`docs/SUPABASE.md`](docs/SUPABASE.md). |
| `STREAMLIT_SERVER_BASE_URL_PATH` | — | Servir bajo un subpath (ej. `simulador`). |
| `PORT` | `8501` | Puerto HTTP del contenedor. |

Para varios usuarios, montar un `secrets.toml` completo (formato en
[`.streamlit/secrets.toml.example`](.streamlit/secrets.toml.example)).

---

## Datos

La app trabaja con dos datasets: **consumo** (cantidad e importe por
prestador / prestación / mes) y **valores** (tarifario con vigencia). El
contrato de columnas, el formato de los exports de origen y el proceso de
ingesta están en [`docs/DATOS.md`](docs/DATOS.md).

```bash
python scripts/generate_demo_data.py --ingest      # dataset sintético
python scripts/ingest.py                           # ingesta incremental desde data/raw/
python scripts/ingest.py --status                  # estado de la base
```

Fuentes soportadas, resueltas en runtime: **DuckDB local**
(`data/simulador.duckdb`, default), **PostgreSQL / Supabase** (si está
configurado) y **archivos subidos** desde la propia UI.

---

## Modelos

`models/` contiene los modelos pre-entrenados (uno por métrica: importe,
cantidad, precio) y sus métricas de entrenamiento:

- `lightgbm_*.txt` — modelo principal.
- `pablo_corregido_*.keras` + `scalers_pablo.pkl` — red neuronal opcional;
  requiere `pip install -r requirements-nn.txt` (o
  `docker build --build-arg WITH_NN=true .`).

El feature engineering (lags, medias móviles, estacionalidad) está en
`src/core/ml_predictor.py` y replica el pipeline de entrenamiento. Ver
[`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md#modelos) para limitaciones
conocidas.

---

## Desarrollo

```bash
make dev          # dependencias + ruff + pytest
make lint
make test
```

- CI en GitHub Actions: ruff + pytest en Python 3.11.
- `tests/test_simulaciones_negocio.py` reconcilia el motor contra workbooks
  reales de negociación; como son datos sensibles no se versionan y los tests
  se saltean sin ellos (ver `tests/fixtures/simulaciones/README.md`).

## Estructura

```
src/
├── core/            lógica de dominio: datos, simulación, anomalías, ML, auth
├── ui/              componentes de presentación, tema y formatos es-AR
├── modules/         una página por módulo
└── streamlit_app.py entry point
scripts/             ingesta, datos de demo, credenciales, healthcheck
models/              modelos pre-entrenados y métricas
deploy/k8s/          manifiestos Kubernetes
deploy/lan/          despliegue on-premise en Windows (Caddy + TLS)
docker/              entrypoint del contenedor
docs/                arquitectura, datos, despliegue, Supabase
tests/               unitarios, ingesta, regresión de negocio
```

## Seguridad

- Login obligatorio (`streamlit-authenticator`, contraseñas con bcrypt cost 12).
- Bloqueo ante fuerza bruta: 5 intentos fallidos en 10 min por usuario
  (umbral mayor por IP) → 15 min de bloqueo.
- Auditoría de login en `logs/auth_audit.log` (JSON Lines, con IP vía
  `X-Forwarded-For`).
- XSRF y CORS habilitados; credenciales y datos fuera de la imagen.

Más detalle en [`docs/DESPLIEGUE.md`](docs/DESPLIEGUE.md#seguridad).
