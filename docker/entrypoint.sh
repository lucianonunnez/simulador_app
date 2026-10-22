#!/bin/sh
# Arranque del contenedor:
#   1. Credenciales: usa .streamlit/secrets.toml si está montado; si no, lo
#      genera desde SIMULADOR_USER / SIMULADOR_PASSWORD.
#   2. Datos: si no hay base DuckDB ni Supabase configurado y DEMO_DATA=true,
#      genera el dataset sintético de demo.
#   3. Levanta Streamlit (la config fina va por variables STREAMLIT_*).
set -eu

python scripts/gen_credentials.py --from-env

if [ ! -f data/simulador.duckdb ] && [ "${DEMO_DATA:-false}" = "true" ] \
   && [ -z "${SUPABASE_DATABASE_URL:-}" ]; then
    echo "Sin base de datos: generando dataset sintético de demo..."
    python scripts/generate_demo_data.py --ingest
fi

exec streamlit run src/streamlit_app.py \
    --server.port="${PORT:-8501}" \
    --server.address=0.0.0.0 \
    --server.headless=true \
    "$@"
