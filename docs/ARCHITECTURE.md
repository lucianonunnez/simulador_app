# Arquitectura

Este documento describe la arquitectura del **Simulador de Costo Médico**: sus
capas, el flujo de datos, la estrategia de caché y las principales decisiones de
diseño.

## 1. Principios

1. **Separación de responsabilidades.** La lógica de negocio (`core/`) no
   conoce Streamlit; la presentación (`ui/`) no contiene reglas de negocio; los
   orquestadores (`modules/`) conectan ambas.
2. **Funciones puras donde se pueda.** Normalización, merge, simulación y
   detección de anomalías reciben DataFrames y devuelven DataFrames, lo que las
   hace testeables sin levantar la UI.
3. **Degradación elegante.** Si falta un origen de datos, un modelo o la capa de
   IA, la app sigue funcionando y guía al usuario en lugar de romperse.
4. **Caché agresiva pero acotada.** Cargas costosas (Excel, modelos, API
   externas) se cachean con TTL para no repetir trabajo entre interacciones.

## 2. Capas

```
streamlit_app.py          Entry point: CSS global, autenticación, router, logging
        │
        ▼
modules/                  Orquestadores por pantalla (render())
  module1  Simulador
  module2  Desvíos
  module3  Predicción ML
        │
   ┌────┴─────┐
   ▼          ▼
core/        ui/
 datos,       controles de sidebar,
 cálculo,     tabs, formatters
 ML, INDEC,   (solo presentación)
 logging, IA
```

### `core/` — lógica y servicios

| Archivo | Responsabilidad |
| ------- | --------------- |
| `data_loader.py` | Carga de consumo/valores con prioridad local → OneDrive → upload. Autodetección de fila de encabezado. Caché con TTL. |
| `simulator.py` | `normalize_dataframes`, `merge_datasets`, `apply_simulation`, `aggregate_top_n`. Núcleo del Módulo 1, reutilizado por 2 y 3. |
| `anomaly.py` | Detección temporal (z-score / IQR con ventana móvil) y estructural (percentil / z-score cruzado), combinación y ranking de alertas. |
| `ml_predictor.py` | Carga de modelos (LightGBM `.txt`, Keras `.keras` + scalers), feature engineering que replica el de entrenamiento, predicción e importancia de features. |
| `indec.py` | Inflación mensual oficial del INDEC vía API de datos.gob.ar. |
| `logging_config.py` | Logging estructurado + canal de auditoría (ver `LOGGING.md`). |
| `ai_assistant.py` | Capa experimental de copiloto IA (ver `AI_ROADMAP.md`). |

### `ui/` — presentación

Componentes Streamlit sin lógica de negocio: controles de sidebar
(`*_controls.py`), pestañas de cada módulo (`*_tabs.py`) y `formatters.py`
(moneda, cantidades). Reciben DataFrames ya procesados y configuración.

### `modules/` — orquestadores

Cada módulo expone `render()`. Patrón común:

1. Cargar datos (reusando el caché compartido de `data_loader`).
2. Normalizar tipos.
3. Renderizar controles y leer la configuración del usuario.
4. Invocar la lógica de `core` con esa configuración.
5. Renderizar resultados en tabs de `ui`.

## 3. Flujo de datos

```
Origen de datos                 Procesamiento                Presentación
────────────────                ─────────────                ────────────
data/*.xlsx          ┐
OneDrive / SharePoint├─► data_loader ─► normalize ─► merge ─► simulación / anomalías / ML ─► tabs
upload manual        ┘     (caché)        (core.simulator)         (core.*)                  (ui.*)
INDEC API ───────────────► indec.fetch_inflation (caché 1h) ──────────────────────────────► tab inflación
```

**Resolución de origen (en orden):**

1. **Carpeta local `data/`** — modo oficina con archivos precargados.
2. **OneDrive / SharePoint** — URLs configuradas en `secrets.toml`, convertidas
   a descarga directa y cacheadas 10 min.
3. **Upload manual** — fallback universal desde la barra lateral.

La **autodetección de encabezado** (`_detect_header_row`) busca la fila que
mejor matchea las columnas esperadas, resolviendo el problema de exportes de
Power BI que anteponen filas de título.

## 4. Estrategia de caché

| Qué | Mecanismo | TTL |
| --- | --------- | --- |
| Excel local | `st.cache_data` | 1 h |
| Excel OneDrive | `st.cache_data` | 10 min |
| Inflación INDEC | `st.cache_data` | 1 h |
| Modelos ML | `st.cache_resource` | mientras viva el proceso |

Los modelos usan `cache_resource` (objeto vivo, no serializable) y por eso su
carga se loguea **una sola vez** por proceso (útil para auditoría).

## 5. Modelos de ML

Tres métricas (`importe`, `precio`, `cantidad`) × dos familias de modelos:

- **LightGBM** (`lightgbm_<metric>.txt`): gradient boosting, expone
  feature importance.
- **Red neuronal "Pablo corregido"** (`pablo_corregido_<metric>.keras` +
  `scalers_pablo.pkl`): requiere escalado de entradas/salidas.

El feature engineering (`construir_panel`, `agregar_features`,
`enriquecer_con_categoricas`) **replica exactamente** el del entrenamiento
(lags 1/2/3, medias y desvíos móviles 3/6, estacionalidad, categóricas por
moda). Cualquier divergencia degradaría la calidad de la predicción, por eso se
mantiene centralizado en `ml_predictor.py`. El entrenamiento se realiza fuera
del repo (notebook en Colab); aquí solo viven los artefactos versionados con Git
LFS.

## 6. Decisiones de diseño

- **Streamlit como front+back**: minimiza el costo de mantenimiento para una
  herramienta interna y permite iterar rápido con el equipo de negocio.
- **`core` sin Streamlit**: habilita tests unitarios y futura reutilización
  (p. ej. un job batch o una API) sin arrastrar la UI.
- **Caché compartido entre módulos**: los tres módulos comparten la misma carga
  de datos, evitando recargas al navegar.
- **XSRF desactivado en producción**: requerido por el proxy de Hugging Face
  Spaces para que funcione `st.file_uploader`; el Space es privado y está detrás
  del login, por lo que el riesgo residual es bajo (documentado en
  `config.toml`).

## 7. Extensibilidad

- **Nuevos métodos de anomalías** (p. ej. LightGBM como detector): se agregan en
  `core/anomaly.py` y se exponen en `ui/anomaly_controls.py`.
- **Nuevos modelos**: agregar artefacto en `models/` y registrarlo en
  `ml_predictor.MODELS`.
- **Copiloto IA**: ya esbozado en `core/ai_assistant.py` (ver `AI_ROADMAP.md`).
