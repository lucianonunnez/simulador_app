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
- **Almacenamiento de datos:** Supabase (PostgreSQL, schema `simulador`)
- **Deploy:** Streamlit Community Cloud

## Datos

Los datos se descargan **manualmente** de MicroStrategy (política de IT: sin
sincronización automática) y se dejan en `data/raw/`. Luego se cargan a **Supabase**
(schema `simulador`) con el script de ingesta, apuntando `DATABASE_URL` al
**Session Pooler** del proyecto:

```bash
# Dejar los Excel en data/raw/consumo/ y data/raw/valores/, después:
export DATABASE_URL="postgresql://postgres.<ref>:<password>@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
python scripts/ingest.py            # ingesta incremental e idempotente
python scripts/ingest.py --rebuild  # reconstruye la base desde cero
python scripts/ingest.py --status   # ver qué hay cargado
```

Los datos viven en Supabase (PostgreSQL, AWS `sa-east-1`), en un schema
`simulador` **aislado** del resto del proyecto y no expuesto por la API REST
pública. Son siempre **agregados por prestador** (nunca a nivel paciente). Ver
`FUENTE_DATOS.md` (extracción) y `docs/DESPLIEGUE_SEGURO.md` (seguridad).

## Estado

🚧 En construcción — datos migrados a Supabase (PostgreSQL); deploy en Streamlit
Community Cloud.
