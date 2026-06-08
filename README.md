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

Aplicación interna para análisis y simulación de costos médicos.

## Módulos

1. **Simulador de Aumentos** — Proyección de impacto financiero ante cambios de tarifas por prestador, nomenclador o prestación.
2. **Detección de Desvíos** — Identificación de anomalías en costos por prestador, prestación o grupo.
3. **Predicción ML** — Pronóstico de costo médico futuro mediante modelos de machine learning.

## Stack

- **Frontend/Backend:** Streamlit
- **Procesamiento:** Pandas / NumPy
- **Visualización:** Plotly
- **ML:** scikit-learn + LightGBM
- **Auth:** streamlit-authenticator
- **Almacenamiento de datos:** DuckDB local (`data/simulador.duckdb`)

## Datos

Los datos se descargan **manualmente** de MicroStrategy (política de IT: sin
sincronización automática) y se dejan en `data/raw/`. Luego se cargan a la base
DuckDB local con el script de ingesta:

```bash
# Dejar los Excel en data/raw/consumo/ y data/raw/valores/, después:
python scripts/ingest.py            # ingesta incremental e idempotente
python scripts/ingest.py --rebuild  # reconstruye la base desde cero
python scripts/ingest.py --status   # ver qué hay cargado
```

Los datos médicos/de prestadores **nunca salen de la máquina** (todo local).
Ver `FUENTE_DATOS.md` (extracción) y `docs/DESPLIEGUE_SEGURO.md` (seguridad).

## Estado

🚧 En construcción — Fase 1 (datos a DuckDB local) en curso.

