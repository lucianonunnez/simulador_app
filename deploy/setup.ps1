# ============================================================================
# setup.ps1 — Setup a prueba de balas del Simulador CM en Windows.
# ============================================================================
# Hace en un solo comando:
#   1. Crea el venv FUERA de OneDrive (el antivirus corporativo corrompe los
#      .py del venv si está dentro de OneDrive).
#   2. Instala las dependencias (con --trusted-host por el proxy corporativo).
#   3. Prepara las carpetas de datos (data\raw\...) y el secrets.toml.
#   4. Si ya dejaste Excel en data\raw\, corre la ingesta a DuckDB.
#
# Uso (desde la raíz del repo, en PowerShell):
#     .\deploy\setup.ps1
#
# Si PowerShell bloquea el script ("execution of scripts is disabled"), corré
# primero (solo para esta ventana):
#     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#
# Parámetros opcionales:
#     -VenvPath  Ruta del venv (default: %USERPROFILE%\venvs\simulador_cm)
#     -Python    Python base a usar (default: python)
# ============================================================================

param(
    [string]$VenvPath = (Join-Path $env:USERPROFILE "venvs\simulador_cm"),
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# --- 0. Chequear que estamos en la raíz del repo ----------------------------
if (-not (Test-Path "requirements.txt")) {
    Write-Host "ERROR: corré este script desde la raíz del repo (donde está requirements.txt)." -ForegroundColor Red
    exit 1
}

# Avisar si la carpeta está dentro de OneDrive (el venv igual va afuera).
if ((Get-Location).Path -like "*OneDrive*") {
    Write-Host "Nota: el repo está dentro de OneDrive. El venv se crea AFUERA a propósito." -ForegroundColor Yellow
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
    Write-Host "   Creé secrets.toml desde la plantilla — FALTA completarlo (ver paso siguiente)." -ForegroundColor Yellow
}

# --- 4. Ingesta (si ya hay Excel) -------------------------------------------
$tieneExcel = (Get-ChildItem "data\raw" -Recurse -Filter *.xlsx -ErrorAction SilentlyContinue | Measure-Object).Count
if ($tieneExcel -gt 0) {
    Step "Encontré Excel en data\raw\ — corriendo la ingesta a DuckDB"
    & $VenvPython scripts\ingest.py
} else {
    Step "No hay Excel en data\raw\ todavía (ingesta salteada)"
    Write-Host "   Dejá los .xlsx en data\raw\consumo\ y data\raw\valores\ y corré:" -ForegroundColor Yellow
    Write-Host "   $VenvPython scripts\ingest.py" -ForegroundColor Yellow
}

# --- Resumen ----------------------------------------------------------------
Write-Host "`n============================================================" -ForegroundColor Green
Write-Host " SETUP LISTO" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Python del venv: $VenvPython"
Write-Host ""
Write-Host "Próximos pasos:" -ForegroundColor Cyan
Write-Host "  1. Completar credenciales:  $VenvPython scripts\gen_credentials.py"
Write-Host "     (pegar el bloque que imprime en .streamlit\secrets.toml)"
Write-Host "  2. Si faltó cargar datos:   $VenvPython scripts\ingest.py"
Write-Host "  3. Levantar la app:"
Write-Host "       Demo rapida:  $VenvPython -m streamlit run src\streamlit_app.py"
Write-Host "       Con TLS:      .\deploy\run_secure.ps1 -Python `"$VenvPython`""
Write-Host ""
