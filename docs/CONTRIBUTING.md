# Guía de contribución

Convenciones de desarrollo para mantener el proyecto consistente y seguro.

## Flujo de trabajo

1. Crear una rama desde `main`: `feature/<descripcion>` o `fix/<descripcion>`.
2. Desarrollar con commits pequeños y descriptivos.
3. Verificar localmente (ver más abajo).
4. Abrir un Pull Request; al menos una revisión antes de mergear.

## Convenciones de código

- **Python 3.11+**, estilo PEP 8.
- `from __future__ import annotations` en módulos con type hints.
- **Separación de capas** (ver `ARCHITECTURE.md`):
  - `core/` no importa Streamlit.
  - `ui/` no contiene lógica de negocio.
  - `modules/` solo orquesta.
- Docstrings en español, claras y orientadas al "por qué".
- Logging vía `core.logging_config` (`get_logger` / `audit`), nunca `print`.

## Estructura de imports

La app se ejecuta con `streamlit run src/streamlit_app.py`, por lo que `src/`
es la raíz de imports:

```python
from core.simulator import merge_datasets
from ui.formatters import format_currency
from modules import module1
```

## Verificación local

```bash
# Compilar (detecta errores de sintaxis)
python -m compileall src

# Levantar la app
streamlit run src/streamlit_app.py
```

Herramientas recomendadas (opcionales):

```bash
pip install ruff pip-audit
ruff check src          # linting
pip-audit               # dependencias vulnerables
```

## Seguridad

- **Nunca** commitear `.streamlit/secrets.toml`, datasets (`*.xlsx`) ni la
  carpeta `data/`. Ya están en `.gitignore`; revisá el diff igual.
- No hardcodear credenciales ni URLs sensibles: usar secrets/variables de
  entorno.
- Nuevos logs no deben exponer PII ni credenciales (ver `LOGGING.md`).

## Modelos de ML

- El entrenamiento se hace fuera del repo (notebook en Colab).
- Solo se versionan los artefactos en `models/` (vía Git LFS).
- Si cambia el feature engineering del entrenamiento, actualizar en paralelo
  `core/ml_predictor.py` para mantener la paridad.

## Commits

Mensajes en imperativo y concisos, p. ej.:

```
Agrega detección de desvíos por z-score cruzado
Corrige autodetección de encabezado en exportes de Power BI
```
