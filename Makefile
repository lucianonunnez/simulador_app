PYTHON ?= python3.11
VENV   ?= .venv
PY     := $(VENV)/bin/python
IMAGE  ?= simulador-cm:latest

export PYTHONPATH := src

.PHONY: help install dev demo-data run test lint docker-build docker-run clean

help:  ## Lista los comandos disponibles
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

$(VENV):
	$(PYTHON) -m venv $(VENV)

install: $(VENV)  ## Instala dependencias de la app
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements.txt

dev: install  ## Instala además herramientas de lint y tests
	$(PY) -m pip install -q -r requirements-dev.txt

demo-data:  ## Genera el dataset sintético y lo carga en DuckDB
	$(PY) scripts/generate_demo_data.py --ingest

run:  ## Levanta la app en http://localhost:8501
	$(PY) -m streamlit run src/streamlit_app.py

test:  ## Corre los tests
	$(PY) -m pytest tests -q

lint:  ## Lint con ruff
	$(PY) -m ruff check src tests scripts

docker-build:  ## Construye la imagen
	docker build -t $(IMAGE) .

docker-run:  ## Corre la imagen con datos de demo (requiere .env)
	docker run --rm -p 8501:8501 --env-file .env -e DEMO_DATA=true $(IMAGE)

clean:  ## Borra base local, logs y caches
	rm -rf data/simulador.duckdb data/raw/*/demo_*.csv logs .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
