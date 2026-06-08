# ============================================================================
# setup.ps1 - Setup automatizado del Simulador CM en Windows.
# ============================================================================
# Hace en un solo comando:
#   1. Crea el venv FUERA de OneDrive (el antivirus corporativo corrompe los
#      .py del venv si esta dentro de OneDrive).
#   2. Instala las dependencias (con --trusted-host por el proxy corporativo).
#   3. Prepara las carpetas de datos (data\raw\...) y el secrets.toml.
#   4. Si ya dejaste Excel en data\raw\, corre la ingesta a DuckDB.
#
# Uso (desde la raiz del repo, en PowerShell):
#     .\deploy\setup.ps1
#
# Si PowerShell bloquea el script ("execution of scripts is disabled"), corre
# primero (solo para esta ventana):
#     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#
# Parametros opcionales:
#     -VenvPath  Ruta del venv (default: %USERPROFILE%\venvs\simulador_cm)
#     -Python    Python base a usar (default: python)
# ============================================================================

param(
    [string]$VenvPath = (Join-Path $env:USERPROFILE "venvs\simulador_cm"),
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# --- 0. Chequear que estamos en la raiz del repo ----------------------------
if (-not (Test-Path "requirements.txt")) {
    Write-Host "ERROR: corre este script desde la raiz del repo (donde esta requirements.txt)." -ForegroundColor Red
    exit 1
}

# Avisar si la carpeta esta dentro de OneDrive (el venv igual va afuera).
if ((Get-Location).Path -like "*OneDrive*") {
    Write-Host "Nota: el repo esta dentro de OneDrive. El venv se crea AFUERA a proposito." -ForegroundColor Yellow
}

# --- 1. Crear el venv (fuera de OneDrive) -----------------------------------
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
if (Test-Path $VenvPython) {
    Step "venv ya existe en $VenvPath (lo reuso)"
} else {
    Step "Creando venv en $VenvPath"
    & $Python -m venv $VenvPath
}

# --- 2. Instalar dependencias -----------------------------------------------
Step "Actualizando pip e instalando dependencias (puede tardar por tensorflow)"
& $VenvPython -m pip install --upgrade pip `
    --trusted-host pypi.org --trusted-host files.pythonhosted.org
& $VenvPython -m pip install -r requirements.txt `
    --trusted-host pypi.org --trusted-host files.pythonhosted.org

# --- 3. Carpetas de datos + secrets -----------------------------------------
Step "Preparando carpetas de datos"
New-Item -ItemType Directory -Force -Path "data\raw\consumo" | Out-Null
New-Item -ItemType Directory -Force -Path "data\raw\valores" | Out-Null
Write-Host "   data\raw\consumo\  y  data\raw\valores\  listas." -ForegroundColor Green

$secrets = ".streamlit\secrets.toml"
if (Test-Path $secrets) {
    Write-Host "   secrets.toml ya existe (no lo toco)." -ForegroundColor Green
} else {
    Copy-Item ".streamlit\secrets.toml.example" $secrets
    Write-Host "   Cree secrets.toml desde la plantilla. FALTA completarlo (ver resumen)." -ForegroundColor Yellow
}

# --- 4. Ingesta (si ya hay Excel) -------------------------------------------
$tieneExcel = (Get-ChildItem "data\raw" -Recurse -Filter *.xlsx -ErrorAction SilentlyContinue | Measure-Object).Count
if ($tieneExcel -gt 0) {
    Step "Encontre Excel en data\raw\ - corriendo la ingesta a DuckDB"
    & $VenvPython scripts\ingest.py
} else {
    Step "No hay Excel en data\raw\ todavia (ingesta salteada)"
    Write-Host "   Deja los .xlsx en data\raw\consumo\ y data\raw\valores\ y corre:" -ForegroundColor Yellow
    Write-Host "   $VenvPython scripts\ingest.py" -ForegroundColor Yellow
}

# --- Resumen ----------------------------------------------------------------
Write-Host "`n============================================================" -ForegroundColor Green
Write-Host " SETUP LISTO" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Python del venv: $VenvPython"
Write-Host ""
Write-Host "Proximos pasos:" -ForegroundColor Cyan
Write-Host "  1. Completar credenciales:  $VenvPython scripts\gen_credentials.py"
Write-Host "     (pegar el bloque que imprime en .streamlit\secrets.toml)"
Write-Host "  2. Si falto cargar datos:   $VenvPython scripts\ingest.py"
Write-Host "  3. Levantar la app:"
Write-Host "       Demo rapida:  $VenvPython -m streamlit run src\streamlit_app.py"
Write-Host "       Con TLS:      .\deploy\run_secure.ps1 -Python `"$VenvPython`""
Write-Host ""
