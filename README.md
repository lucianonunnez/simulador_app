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

Plataforma interna de análisis, proyección y detección de desvíos sobre el
costo médico. Pensada para que los equipos ejecutivos y de administración de
prestadores puedan **simular escenarios de aumentos**, **detectar anomalías de
gasto** y **proyectar el costo futuro con modelos de machine learning**, todo
sobre los mismos datos y con una experiencia unificada.

> Aplicación de uso interno. El acceso requiere autenticación y los datos de
> negocio nunca se versionan en el repositorio (ver [Seguridad](#-seguridad-de-datos)).

---

## 📑 Tabla de contenidos

- [Funcionalidades](#-funcionalidades)
- [Arquitectura](#-arquitectura)
- [Estructura del repositorio](#-estructura-del-repositorio)
- [Puesta en marcha local](#-puesta-en-marcha-local)
- [Despliegue](#-despliegue)
- [Configuración](#-configuración)
- [Seguridad de datos](#-seguridad-de-datos)
- [Logging y auditoría](#-logging-y-auditoría)
- [Integración con IA (roadmap)](#-integración-con-ia-roadmap)
- [Documentación](#-documentación)
- [Equipo](#-equipo)

---

## ✨ Funcionalidades

| Módulo | Descripción |
| ------ | ----------- |
| **1 · Simulador de Aumentos** | Proyección del impacto financiero ante cambios de tarifas por prestador, nomenclador o prestación. Tabla de negociación valor actual vs. ofrecido, y métricas de impacto sobre el período elegido. |
| **2 · Detección de Desvíos** | Identificación de anomalías de costo con métodos estadísticos: comparación **temporal** (vs. la propia historia, z-score / IQR con ventana móvil) y **estructural** (vs. pares comparables, percentil / z-score cruzado). |
| **3 · Predicción ML** | Pronóstico del costo médico futuro combinando **LightGBM** y una **red neuronal** (Keras/TensorFlow), con comparativa de modelos y métricas de performance. |

Transversal a los tres módulos: carga de datos unificada (carpeta local /
OneDrive / upload manual), cacheada y con autodetección de encabezados;
enriquecimiento con inflación oficial del **INDEC** (API de datos.gob.ar).

---

## 🏗️ Arquitectura

La aplicación sigue una **arquitectura en capas** que separa estrictamente la
lógica de negocio de la presentación:

```
            ┌──────────────────────────────┐
            │      streamlit_app.py        │  Entry point + router + auth
            └──────────────┬───────────────┘
                           │
              ┌────────────┴────────────┐
              │        modules/         │  Orquestadores de pantalla
              │  module1 · 2 · 3        │  (render por módulo)
              └─────┬──────────────┬────┘
                    │              │
        ┌───────────┴───┐   ┌──────┴────────────┐
        │     core/     │   │       ui/          │
        │ (sin Streamlit)│  │ (solo presentación)│
        │ datos · cálculo│  │ controles · tabs   │
        │ ML · logging   │  │ formatters         │
        └───────────────┘   └────────────────────┘
```

- **`core/`** — lógica **pura** y servicios: carga de datos, simulación,
  detección de anomalías, predicción ML, integración INDEC, logging y la capa
  (experimental) de IA. No importa Streamlit en la lógica de negocio, lo que
  permite testearla de forma aislada.
- **`ui/`** — componentes de presentación (controles de sidebar, tabs,
  formateo). No contiene reglas de negocio.
- **`modules/`** — orquestadores: cada uno expone `render()` y conecta `core`
  con `ui`.

El detalle completo (flujo de datos, decisiones de diseño, caché, modelo de
datos) está en **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**.

### Stack

| Capa | Tecnología |
| ---- | ---------- |
| Frontend / Backend | Streamlit |
| Procesamiento | pandas · NumPy |
| Visualización | Plotly |
| Machine Learning | scikit-learn · LightGBM · TensorFlow/Keras |
| Autenticación | streamlit-authenticator (bcrypt) |
| Origen de datos | OneDrive / SharePoint · carga manual · carpeta local |
| Empaquetado | Docker (Python 3.11-slim) |

---

## 📂 Estructura del repositorio

```
simulador_app/
├── README.md                    # este archivo
├── Dockerfile                   # imagen de producción
├── requirements.txt             # dependencias de runtime
├── .gitignore / .dockerignore   # exclusiones (incluye secrets y datos)
├── .gitattributes               # Git LFS para artefactos binarios
│
├── .streamlit/
│   ├── config.toml              # tema y configuración del servidor
│   └── secrets.toml.example     # plantilla de secrets (el real NO se versiona)
│
├── src/
│   ├── streamlit_app.py         # entry point: CSS, router, auth, logging
│   ├── auth.py                  # login/logout + auditoría de acceso
│   │
│   ├── core/                    # lógica de negocio (sin Streamlit)
│   │   ├── data_loader.py       #   carga/caché de consumo y valores
│   │   ├── simulator.py         #   normalización, merge, simulación
│   │   ├── anomaly.py           #   detección de desvíos (temporal/estructural)
│   │   ├── ml_predictor.py      #   carga de modelos y predicción
│   │   ├── indec.py             #   inflación oficial (API INDEC)
│   │   ├── logging_config.py    #   logging estructurado + auditoría
│   │   └── ai_assistant.py      #   capa de IA (experimental, off por defecto)
│   │
│   ├── ui/                      # presentación (Streamlit)
│   │   ├── formatters.py
│   │   ├── simulator_controls.py / simulator_tabs.py
│   │   ├── anomaly_controls.py  / anomaly_tabs.py
│   │   └── ml_controls.py       / ml_tabs.py
│   │
│   └── modules/                 # orquestadores de pantalla
│       ├── module1.py · module2.py · module3.py
│
├── models/                      # modelos pre-entrenados + métricas (Git LFS)
│   ├── lightgbm_{importe,precio,cantidad}.txt
│   ├── pablo_corregido_{importe,precio,cantidad}.keras
│   ├── scalers_pablo.pkl
│   └── metricas_*.json
│
└── docs/                        # documentación de ingeniería
    ├── ARCHITECTURE.md · SECURITY.md · LOGGING.md
    ├── AI_ROADMAP.md · DATA_MODEL.md · CONTRIBUTING.md
```

---

## 🚀 Puesta en marcha local

**Requisitos:** Python 3.11+.

```bash
# 1. Clonar y entrar al proyecto
git clone <repo-url> && cd simulador_app

# 2. Entorno virtual
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Dependencias
pip install -r requirements.txt

# 4. Configurar secrets (usuarios + orígenes de datos)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
#   editar .streamlit/secrets.toml con usuarios reales y URLs de OneDrive

# 5. Levantar la app
streamlit run src/streamlit_app.py
```

La app queda disponible en `http://localhost:8501`.

> **Datos:** podés dejar archivos `data/consumo.xlsx` y `data/valores.xlsx`
> para precarga automática (modo oficina), configurar URLs de OneDrive en
> `secrets.toml`, o simplemente subirlos desde la barra lateral. La carpeta
> `data/` está en `.gitignore` y nunca se versiona.

### Generar un usuario

```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'MI_PASSWORD', bcrypt.gensalt()).decode())"
```

Pegá el hash resultante en `.streamlit/secrets.toml`.

---

## 📦 Despliegue

El proyecto se empaqueta con **Docker** y está preparado para **Hugging Face
Spaces** (SDK `docker`, puerto `8501`):

```bash
docker build -t simulador-costo-medico .
docker run -p 8501:8501 \
  -v "$(pwd)/.streamlit/secrets.toml:/app/.streamlit/secrets.toml:ro" \
  simulador-costo-medico
```

En Hugging Face Spaces, cargá los secretos desde **Settings → Repository
secrets** (no como archivo). El `Dockerfile` incluye un `HEALTHCHECK` sobre el
endpoint de salud de Streamlit.

---

## ⚙️ Configuración

| Variable de entorno | Default | Descripción |
| ------------------- | ------- | ----------- |
| `LOG_LEVEL` | `INFO` | Nivel de logging (`DEBUG`/`INFO`/`WARNING`/`ERROR`). |
| `LOG_FORMAT` | `text` | `text` (desarrollo) o `json` (producción, para colectores). |
| `AI_ASSISTANT_ENABLED` | `false` | Habilita la capa experimental de IA. |
| `ANTHROPIC_API_KEY` | — | Credencial del asistente de IA (si está habilitado). |

La configuración de tema/servidor de Streamlit vive en `.streamlit/config.toml`
y las credenciales/orígenes de datos en `.streamlit/secrets.toml`.

---

## 🔐 Seguridad de datos

La seguridad es un requisito de primer orden (datos sensibles del negocio):

- **Autenticación obligatoria** con `streamlit-authenticator`; contraseñas
  almacenadas como **hash bcrypt**, nunca en texto plano.
- **Secrets fuera del repo:** `.streamlit/secrets.toml` está en `.gitignore`;
  solo se versiona la plantilla `*.example`.
- **Datos de negocio fuera del repo:** los Excel de consumo/valores están
  excluidos por `.gitignore` y se cargan en runtime.
- **Redacción automática** de campos sensibles en los logs (passwords, tokens,
  cookie keys nunca se escriben en claro).

Política completa, modelo de amenazas y checklist en
**[`docs/SECURITY.md`](docs/SECURITY.md)**.

---

## 📋 Logging y auditoría

Logging **estructurado y centralizado** (`core/logging_config.py`) con dos
canales: operación (`simulador.*`) y **auditoría** (`simulador.audit`) para
eventos relevantes a seguridad/compliance (login, carga de datos, exportación,
carga de modelos). Formato conmutables a JSON para ingestión por un colector.
Detalle en **[`docs/LOGGING.md`](docs/LOGGING.md)**.

---

## 🤖 Integración con IA (roadmap)

Más allá de los modelos predictivos actuales, el proyecto contempla un
**copiloto analítico** en lenguaje natural sobre los resultados de cada módulo.
La base ya está en el repo (`core/ai_assistant.py`), **desactivada por
defecto**, con lazy import del SDK, prompt caching y envío de datos agregados
(nunca el dataset crudo). El plan por hitos está en
**[`docs/AI_ROADMAP.md`](docs/AI_ROADMAP.md)**.

---

## 📚 Documentación

| Documento | Contenido |
| --------- | --------- |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Arquitectura, flujo de datos, caché, decisiones de diseño. |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Política de seguridad, modelo de amenazas, manejo de secretos. |
| [`docs/LOGGING.md`](docs/LOGGING.md) | Estrategia de logging y auditoría. |
| [`docs/AI_ROADMAP.md`](docs/AI_ROADMAP.md) | Roadmap de integración con IA. |
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | Esquema de datos de consumo y valores. |
| [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) | Convenciones de desarrollo y flujo de trabajo. |

---

## 👥 Equipo

Producto interno mantenido por el equipo de **Análisis y Administración
Operativa de Prestadores**. Para acceso, alta de usuarios o reporte de
incidencias, contactar al responsable del repositorio.
