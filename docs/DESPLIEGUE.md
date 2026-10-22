# Despliegue

## Imagen

```bash
docker build -t simulador-cm:0.6.0 .
docker build --build-arg WITH_NN=true -t simulador-cm:0.6.0-nn .   # con TensorFlow
```

- Base `python:3.11-slim`, usuario no-root (uid 1000).
- Contiene código, scripts y modelos. **No** contiene datos ni credenciales
  (ver `.dockerignore`).
- Volúmenes: `/app/data` (base DuckDB, bandejas de ingesta) y `/app/logs`
  (auditoría de login).
- Healthcheck: `GET /_stcore/health` (respeta `PORT` y
  `STREAMLIT_SERVER_BASE_URL_PATH`).

### Arranque (`docker/entrypoint.sh`)

1. Si no hay `/app/.streamlit/secrets.toml` montado, lo genera desde
   `SIMULADOR_USER` / `SIMULADOR_PASSWORD` / `SIMULADOR_COOKIE_KEY`.
2. Si no hay base, `DEMO_DATA=true` y no hay fuente PostgreSQL configurada,
   genera y carga el dataset sintético.
3. Lanza Streamlit en `0.0.0.0:${PORT}`. Cualquier opción de Streamlit se puede
   pasar como variable `STREAMLIT_*` o como argumento extra del contenedor.

## Docker Compose

```bash
cp .env.example .env
docker compose up --build -d
docker compose logs -f
```

## Kubernetes

```
deploy/k8s/
├── kustomization.yaml       imagen y recursos base
├── deployment.yaml          1 réplica, probes, límites, securityContext
├── service.yaml             ClusterIP :80 → 8501
├── pvc.yaml                 2Gi RWO para /app/data
├── secret.example.yaml      formato del Secret de credenciales
└── ingress.example.yaml     ejemplo ingress-nginx (timeouts para WebSockets)
```

```bash
kubectl create namespace simulador
kubectl -n simulador create secret generic simulador-credentials \
  --from-literal=SIMULADOR_USER=admin \
  --from-literal=SIMULADOR_PASSWORD='...' \
  --from-literal=SIMULADOR_COOKIE_KEY="$(openssl rand -hex 32)"
kubectl -n simulador apply -k deploy/k8s/
kubectl -n simulador port-forward svc/simulador-cm 8501:80
```

Ajustar `images` en `kustomization.yaml` al registry del cluster.

### Recursos

| | Request | Límite | Notas |
|---|---|---|---|
| CPU | 250m | 2 | El costo está en el feature engineering del Módulo 3. |
| Memoria | 1 GiB | 3 GiB | DuckDB tiene un techo de 2 GB y derrama a disco. Con TensorFlow sumar ~500 MiB. |

No requiere GPU: la inferencia es LightGBM sobre CPU.

### Escalado

El deployment usa **una réplica** y estrategia `Recreate` por diseño:

- DuckDB admite un único proceso escritor por archivo, y el volumen es RWO.
- El estado de rate-limit del login vive en memoria del proceso.
- Streamlit mantiene la sesión en el servidor (WebSocket).

Para más de una réplica: usar la fuente PostgreSQL (`SUPABASE_DATABASE_URL`),
habilitar afinidad de sesión en el ingress
(`nginx.ingress.kubernetes.io/affinity: cookie`) y mover el rate-limit a un
store compartido.

### Subpath

Para servir en `https://host/simulador`:

- `STREAMLIT_SERVER_BASE_URL_PATH=simulador` en el contenedor.
- Probes en `/simulador/_stcore/health`.
- `path: /simulador` en el Ingress.

### Varios usuarios

Montar un `secrets.toml` completo como Secret (los bloques comentados en
`deployment.yaml`):

```bash
kubectl -n simulador create secret generic simulador-secrets-toml --from-file=secrets.toml
```

Los hashes se generan con `python scripts/gen_credentials.py`.

## On-premise en Windows (LAN)

`deploy/lan/` contiene el despliegue original para servir la app desde una
estación Windows dentro de la red corporativa:

- `setup.ps1`: crea el venv e instala dependencias detrás de proxy corporativo.
- `run_secure.ps1`: Streamlit en `127.0.0.1` + Caddy como reverse proxy TLS en
  `:8443` (`Caddyfile`, CA interna de Caddy). Ajustar la IP en `Caddyfile`.

Regla de firewall sugerida (solo la subred corporativa):

```powershell
New-NetFirewallRule -DisplayName "Simulador CM" -Direction Inbound -Action Allow `
  -Protocol TCP -LocalPort 8443 -RemoteAddress <SUBRED>/16 -Profile Domain,Private
```

## Seguridad

- **Datos:** agregados por prestador/prestación, sin datos de pacientes, pero
  comercialmente sensibles. No deben exponerse a Internet sin una capa de
  acceso adicional (VPN, SSO en el ingress, allowlist de red).
- **Transporte:** siempre TLS delante de Streamlit (ingress o Caddy). Sin TLS
  las contraseñas viajan en claro.
- **Autenticación:** bcrypt cost 12; `cookie_expiry_days = 1` por defecto;
  bloqueo ante fuerza bruta por usuario e IP.
- **Auditoría:** `logs/auth_audit.log` registra `login_success`,
  `login_failed` y `login_blocked` con IP de origen (requiere que el proxy
  envíe `X-Forwarded-For`).
- **XSRF / CORS:** habilitados en `.streamlit/config.toml`. Si un proxy rompe
  los tokens XSRF (síntoma: 403 al subir archivos), revisar que reenvíe
  cookies y el header `Origin` antes de deshabilitarlos.
- **Secretos:** `secrets.toml` y `.env` nunca se versionan ni entran a la
  imagen; en cluster van como Secret.
- **Datos en reposo:** el volumen de `/app/data` debe estar cifrado (en
  estaciones de trabajo, cifrado de disco completo).
- **PostgreSQL:** la conexión fuerza `sslmode=require`. Usar un rol de solo
  lectura para la app.
