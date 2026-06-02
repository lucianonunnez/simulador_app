FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema (openpyxl/lightgbm pueden requerirlas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements primero para cachear la capa
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar archivos de la app
COPY src/ ./src/
COPY .streamlit/ ./.streamlit/
COPY models/ ./models/

# HF Spaces usa el puerto 8501 por default para Streamlit
EXPOSE 8501

# Salud + arranque
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "src/streamlit_app.py", \
    "--server.port=8501", \
    "--server.address=0.0.0.0"]