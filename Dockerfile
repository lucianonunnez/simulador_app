FROM python:3.11-slim

WORKDIR /app

# Dependencias del sistema (openpyxl/lightgbm pueden requerirlas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements primero para cachear la capa.
# NOTA: tensorflow-cpu NO se instala por default (es opcional, ver
# requirements-nn.txt): la imagen queda ~950MB más liviana y usar el Módulo 3
# cuesta ~500MB menos de RAM. El módulo funciona en modo LightGBM; para
# habilitar la comparativa con la red neuronal, descomentá la línea.
COPY requirements.txt requirements-nn.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# RUN pip install --no-cache-dir -r requirements-nn.txt

# Copiar archivos de la app.
# OJO: de .streamlit/ solo va config.toml — el secrets.toml JAMÁS entra a la
# imagen (las credenciales se inyectan en runtime: volumen montado o Secrets
# del host/Space). .dockerignore refuerza esto por si el COPY se generaliza.
COPY src/ ./src/
COPY .streamlit/config.toml ./.streamlit/config.toml
COPY models/ ./models/

# HF Spaces usa el puerto 8501 por default para Streamlit
EXPOSE 8501

# Salud + arranque
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "src/streamlit_app.py", \
    "--server.port=8501", \
    "--server.address=0.0.0.0"]