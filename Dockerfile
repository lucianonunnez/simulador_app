FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# libgomp1: runtime de OpenMP que necesita LightGBM.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# tensorflow-cpu NO se instala por default (requirements-nn.txt): suma ~950 MB
# a la imagen y ~500 MB de RAM. Sin él el Módulo 3 corre en modo LightGBM.
# Para habilitarlo: docker build --build-arg WITH_NN=true .
ARG WITH_NN=false
COPY requirements.txt requirements-nn.txt ./
RUN pip install -r requirements.txt \
    && if [ "$WITH_NN" = "true" ]; then pip install -r requirements-nn.txt; fi

# De .streamlit/ solo entra config.toml: las credenciales se inyectan en
# runtime (Secret montado o variables de entorno), nunca en la imagen.
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY models/ ./models/
COPY .streamlit/config.toml ./.streamlit/config.toml
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN useradd --create-home --uid 1000 app \
    && mkdir -p data logs \
    && chown -R app:app /app \
    && chmod +x /usr/local/bin/entrypoint.sh
USER app

VOLUME ["/app/data", "/app/logs"]
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python scripts/healthcheck.py || exit 1

ENTRYPOINT ["entrypoint.sh"]
