# Logging y auditoría

El proyecto usa un logging **estructurado y centralizado** definido en
`src/core/logging_config.py`. Hay dos canales con propósitos distintos:

| Canal | Logger | Propósito |
| ----- | ------ | --------- |
| Operación | `simulador.*` | Diagnóstico y observabilidad de la app. |
| Auditoría | `simulador.audit` | Eventos relevantes a seguridad/compliance. |

## 1. Inicialización

`setup_logging()` se llama una vez al arrancar la app (en `streamlit_app.py`).
Es **idempotente**: aunque Streamlit re-ejecute el script en cada interacción,
no se duplican handlers.

```python
from core.logging_config import setup_logging, get_logger, audit

setup_logging()
log = get_logger(__name__)         # -> "simulador.<modulo>"
log.info("Procesando %s filas", n)
```

## 2. Configuración por entorno

| Variable | Valores | Default | Efecto |
| -------- | ------- | ------- | ------ |
| `LOG_LEVEL` | `DEBUG`/`INFO`/`WARNING`/`ERROR` | `INFO` | Nivel mínimo. |
| `LOG_FORMAT` | `text` / `json` | `text` | Formato de salida. |

- **`text`** (desarrollo): legible, con campos extra al final de la línea.
- **`json`** (producción): una línea JSON por evento, lista para ingestión por
  un colector (ELK / Loki / CloudWatch).

Ejemplo `text`:

```
2026-06-02 15:02:57 | INFO    | simulador.audit | login_success | event=login_success username=demo role=admin
```

Ejemplo `json`:

```json
{"ts":"2026-06-02T15:02:57+00:00","level":"INFO","logger":"simulador.audit","msg":"login_success","event":"login_success","username":"demo","role":"admin"}
```

## 3. Campos estructurados

Para adjuntar metadatos a un log, se pasan vía `extra={"fields": {...}}`:

```python
log.info("Merge completo", extra={"fields": {"rows": len(df_merged)}})
```

Ambos formatters (`text` y `json`) muestran esos campos. El canal de auditoría
lo abstrae con la función `audit()`:

```python
audit("data_loaded", source="onedrive", rows=12345)
```

## 4. Redacción de datos sensibles

Cualquier campo cuya **clave** sea sensible se reemplaza por `***` antes de
escribirse, en ambos canales y formatos:

```
_SENSITIVE_KEYS = {"password", "passwd", "pwd", "hash", "cookie_key", "token", "secret"}
```

```python
audit("login_failure", username="demo", password="loquesea")
# -> ... username=demo password=***
```

> Regla de oro: **nunca** pasar contenido de datasets ni credenciales en claro a
> los logs. Solo identificadores y metadatos del evento.

## 5. Eventos de auditoría actuales

| Evento | Origen | Campos |
| ------ | ------ | ------ |
| `login_success` | `auth.require_login` | `username`, `role` |
| `login_failure` | `auth.require_login` | `username` |
| `model_loaded` | `ml_predictor.load_lightgbm` | `model`, `metric` |
| `ai_query` | `ai_assistant.ask` | `model`, `chars_context` |

El login exitoso se audita **una sola vez por sesión** (flag en
`session_state`) para no generar ruido en cada rerun de Streamlit.

## 6. Buenas prácticas para nuevos logs

- Usá `get_logger(__name__)`, no `print` ni el `logging` global.
- Elegí el nivel correcto: `DEBUG` para detalle de desarrollo, `INFO` para hitos
  normales, `WARNING`/`ERROR` para anomalías.
- Para eventos de seguridad/compliance usá `audit(...)`, no el logger normal.
- Logueá **conteos y metadatos**, no filas de datos.
