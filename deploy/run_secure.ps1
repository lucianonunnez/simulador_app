# ============================================================================
# run_secure.ps1 - Levanta el Simulador CM de forma segura (Streamlit + Caddy/TLS).
# ============================================================================
# - Streamlit escucha SOLO en 127.0.0.1:8501 (no accesible desde la red).
# - Caddy termina TLS y expone la app en https://<IP>:8443 para la LAN.
#
# Uso (desde la raiz del repo, en PowerShell):
#     .\deploy\run_secure.ps1
#
# Requisitos:
#   - El venv del proyecto (ver -Python abajo).
#   - caddy.exe en el PATH (o pasar -Caddy "C:\ruta\caddy.exe").
#     Descargar de https://caddyserver.com/download (un solo binario).
# ============================================================================

param(
    [string]$Python = "C:\Users\lununez\venvs\simulador_cm\Scripts\python.exe",
    [string]$Caddy = "caddy"
)

$ErrorActionPreference = "Stop"

Write-Host "==> Iniciando Streamlit en 127.0.0.1:8501 (solo local)..." -ForegroundColor Cyan
$st = Start-Process -FilePath $Python -ArgumentList @(
    "-m", "streamlit", "run", "src/streamlit_app.py",
    "--server.address", "127.0.0.1",
    "--server.port", "8501",
    "--server.headless", "true"
) -PassThru -NoNewWindow

Start-Sleep -Seconds 4

Write-Host "==> Iniciando Caddy (TLS) con deploy/Caddyfile..." -ForegroundColor Cyan
$cy = Start-Process -FilePath $Caddy -ArgumentList @(
    "run", "--config", "deploy/Caddyfile", "--adapter", "caddyfile"
) -PassThru -NoNewWindow

Write-Host ""
Write-Host "App disponible en https://10.11.45.103:8443 (cambiar IP segun tu red)." -ForegroundColor Green
Write-Host "Ctrl+C para frenar. Se cierran ambos procesos." -ForegroundColor Yellow

try {
    Wait-Process -Id $cy.Id
}
finally {
    Stop-Process -Id $st.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $cy.Id -ErrorAction SilentlyContinue
    Write-Host "Procesos detenidos." -ForegroundColor Yellow
}
