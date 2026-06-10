#!/bin/bash
# SessionStart hook — prepara el entorno en sesiones de Claude Code on the web:
# instala las dependencias de la app + herramientas de dev (lint y tests), para
# que se pueda correr la app, `ruff` y `pytest` sin pasos manuales.
#
# Idempotente: pip omite lo ya instalado, así que es seguro re-ejecutarlo.
set -euo pipefail

# Solo en el entorno remoto (web). En local no tocamos el entorno del usuario.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

echo "[session-start] Instalando dependencias de la app (requirements.txt)..."
pip install --quiet --no-cache-dir -r requirements.txt

echo "[session-start] Instalando herramientas de desarrollo (ruff, pytest)..."
pip install --quiet --no-cache-dir -r requirements-dev.txt

# El código importa como `from core...`, `from modules...`, `from ui...`,
# resolviendo contra src/. Persistimos PYTHONPATH para tests y linters.
echo 'export PYTHONPATH="src"' >> "$CLAUDE_ENV_FILE"

echo "[session-start] Listo."
