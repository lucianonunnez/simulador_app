"""Healthcheck del contenedor: respeta PORT y STREAMLIT_SERVER_BASE_URL_PATH."""

import os
import sys
import urllib.request

port = os.environ.get("PORT", "8501")
base = os.environ.get("STREAMLIT_SERVER_BASE_URL_PATH", "").strip("/")
url = f"http://127.0.0.1:{port}/{base + '/' if base else ''}_stcore/health"

try:
    with urllib.request.urlopen(url, timeout=4) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
