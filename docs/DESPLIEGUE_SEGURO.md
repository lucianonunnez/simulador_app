# 🔒 Despliegue seguro — Simulador CM

> Seguridad para los dos modos de despliegue: **(A) Streamlit Community Cloud +
> Supabase** (el modo actual) y **(B) local en la LAN** (alternativa offline).
> Pensado **como un experto en ciberseguridad**.
>
> **Modelo de amenaza (modo nube):** app pública en Streamlit Cloud detrás de
> login, datos en Supabase (PostgreSQL, región `sa-east-1`). Los datos NUNCA son
> a nivel paciente (siempre agregado por prestador), pero son sensibles: el
> control de acceso (login + connection string secreta + aislamiento de schema)
> es lo que los protege.

---

## A. Modo nube — Streamlit Community Cloud + Supabase (actual)

Checklist de seguridad para el deploy en la nube:

- [ ] **Secrets en el panel de Streamlit Cloud** (Settings → Secrets), nunca en el
      repo: `cookie_key` fuerte, hashes bcrypt por usuario, `supabase_db_url`.
- [ ] **Connection string = Session Pooler** con la password de la base. Tratarla
      como secreto; rotarla si se filtró (Supabase → Settings → Database → Reset
      database password).
- [ ] **Schema `simulador` aislado**: no exponerlo por la API REST (PostgREST
      publica solo `public`). Verificado con los advisors de seguridad de Supabase.
- [ ] **Login bcrypt** (cost ≥ 12), password único por persona, `cookie_expiry_days = 1`.
- [ ] **Rate-limit / lockout** de login activo (`src/core/` ya lo implementa).
- [ ] Correr `get_advisors` de Supabase (security) tras cada cambio de schema.
- [ ] El repo es **privado** o, si es público, **sin** secrets ni datos versionados.

> ⚠️ En modo nube **no** aplican Caddy, el firewall de Windows ni el binding por IP
> (eso es del modo local, sección B). Streamlit Cloud ya sirve por HTTPS.

---

## B. Modo local (LAN) — alternativa offline

### Checklist rápido (antes de cada demo local)

- [ ] BitLocker activo en el disco.
- [ ] `secrets.toml` con `cookie_key` fuerte y passwords únicos por persona.
- [ ] Levantar con `.\deploy\run_secure.ps1` (Streamlit en localhost + Caddy/TLS).
- [ ] IP correcta en `deploy/Caddyfile` (la de tu notebook, `ipconfig`).
- [ ] Regla de firewall que permite el **8443** solo desde la subred corporativa.
- [ ] VPN conectada (si la red lo requiere).
- [ ] Cerrar el server (Ctrl+C) al terminar la reunión.

---

## 1. Red — exposición mínima

La app debe ser alcanzable **solo desde la LAN corporativa**, nunca desde Internet.

- **Recomendado (con TLS):** Streamlit escucha solo en `127.0.0.1` y se expone a
  la LAN a través del reverse proxy Caddy en HTTPS (ver sección 8). Lo más simple
  es usar el script:
  ```powershell
  .\deploy\run_secure.ps1
  ```
- Alternativa sin TLS (solo si no podés usar Caddy): bindear directo a la IP de la
  red. Las contraseñas viajan en texto plano → evitalo si podés.
  ```bash
  streamlit run src/streamlit_app.py --server.address 10.11.45.103 --server.port 8501
  ```
- **Nada de túneles** (ngrok, Cloudflare Tunnel, etc.) ni port-forwarding en el router.
- Si la red lo exige, conectarse por **VPN** antes de levantar la app.

## 2. Firewall de Windows — regla acotada

Con el reverse proxy, lo que se expone es el **8443 de Caddy** (HTTPS). El 8501 de
Streamlit queda solo en localhost y **no** necesita regla de firewall.

Permitir el puerto 8443 **solo** desde la subred corporativa, no desde "cualquiera":

```powershell
New-NetFirewallRule -DisplayName "Simulador CM (LAN)" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8443 `
  -RemoteAddress 10.11.0.0/16 -Profile Domain,Private
```

- Ajustar `10.11.0.0/16` a la subred real de la oficina.
- **Bloquear** el perfil `Public`. Nunca `-RemoteAddress Any`.
- Borrar la regla cuando no se usa más:
  `Remove-NetFirewallRule -DisplayName "Simulador CM (LAN)"`.
- (Si corrés sin TLS, cambiá `8443` por `8501`.)

## 3. Streamlit — config endurecida

En `.streamlit/config.toml`, para correr local en la LAN:

```toml
[server]
enableCORS = true
enableXsrfProtection = true
```

> Estas DEBEN estar en `true` al servir por IP (defensa contra CSRF / cross-origin).
> Solo se ponen en `false` si se despliega en Hugging Face Spaces (el proxy de HF
> rompe los tokens XSRF). Hoy el objetivo es local → van en `true`.

## 4. Autenticación

- **bcrypt** con cost ≥ 12 para los hashes (nunca passwords en texto plano).
- Password **fuerte y único por persona** (cada ejecutivo su cuenta).
- `cookie_key` aleatorio de ≥ 32 bytes:
  ```python
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
- `cookie_expiry_days = 1` para una demo (no 7): la sesión caduca rápido.
- Considerar **lockout / rate-limit** tras varios intentos fallidos.
- **Rotar** cualquier credencial o `cookie_key` que haya viajado en el paquete
  (el .zip del proyecto contenía credenciales reales → asumirlas comprometidas).

## 5. Secretos

- `secrets.toml` vive **solo local** y está en `.gitignore`. **Nunca** se commitea.
- Usar `.streamlit/secrets.toml.example` como plantilla.
- Si se necesita rotar/generar hashes, mantener un helper local de hashing bcrypt
  (no versionar el resultado).

## 6. Datos en reposo

- **Modo nube:** los datos viven en **Supabase** (cifrado en reposo gestionado por
  Supabase/AWS). El control de acceso es la connection string secreta + el login
  de la app. El schema `simulador` está aislado y no expuesto por la API pública.
- **Modo local:** **BitLocker** (cifrado de disco completo) como control
  compensatorio si hay Excel sensibles en la notebook durante la ingesta.
- Los Excel en `data/raw/` están en `.gitignore`: no se versionan ni se suben jamás.

## 7. Auditoría de acceso

✅ **Implementado** en `src/core/audit.py` + `src/auth.py`. Cada evento de login
se registra como JSON Lines en `logs/auth_audit.log` (gitignored):

- `login_success` / `login_failed`: timestamp, usuario, IP origen, resultado.

> La IP solo se captura bien si la app corre **detrás del reverse proxy** (sección
> 8), que inyecta `X-Forwarded-For`. Sirviendo HTTP plano queda `"unknown"`.
>
> Pendiente (opcional): registrar también `data_access` (qué prestador consultó
> cada usuario) — `audit.log_event("data_access", username, detail=prestador)`.

## 8. Transporte (TLS) con Caddy — ✅ configurado

HTTP en la LAN manda las contraseñas **en texto plano** (sniffeables por alguien en
la misma red). La solución es un **reverse proxy con TLS** delante de Streamlit.
Ya está configurado con **Caddy** (un solo binario, TLS automático).

Arquitectura: `browser → https://IP:8443 (Caddy, TLS) → 127.0.0.1:8501 (Streamlit)`.
Caddy además inyecta `X-Forwarded-For`, lo que habilita la IP real en la auditoría.

### Pasos

1. **Conseguir Caddy** (un solo `.exe`): descargar de
   https://caddyserver.com/download y dejar `caddy.exe` en el PATH (o pasar la
   ruta con `-Caddy` al script).
2. **Ajustar la IP** en `deploy/Caddyfile` (línea `https://10.11.45.103:8443`) a
   la IP real de tu notebook (`ipconfig`).
3. **Levantar todo** con el script (Streamlit en localhost + Caddy en TLS):
   ```powershell
   .\deploy\run_secure.ps1
   ```
4. Los ejecutivos entran a `https://10.11.45.103:8443`.

### Certificado y la advertencia del navegador

Caddy usa su **CA interna** (`tls internal`): el certificado es válido pero no está
firmado por una CA pública, así que el navegador muestra "no es seguro" la primera
vez. Opciones:

- **Demo puntual:** clic en "Avanzado → continuar". El tráfico va igual cifrado.
- **Sin advertencia:** instalar la **CA raíz de Caddy** como confiable. En la
  notebook que corre Caddy: `caddy trust`. En las máquinas de los ejecutivos, que
  IT distribuya/instale ese root, o pedir a IT un certificado del CA corporativo.

### Si algo falla

- **No carga / WebSocket cortado:** confirmá que Streamlit quedó en `127.0.0.1:8501`
  y que Caddy está corriendo (Caddy reenvía los WebSockets automáticamente).
- **403 al subir un archivo:** es XSRF detrás del proxy. Como último recurso, en
  `.streamlit/config.toml` poné `enableXsrfProtection = false` (el túnel TLS y el
  login siguen protegiendo).

## 9. Operación

- Correr la app como usuario **no-administrador**.
- **Cerrar el server** (Ctrl+C en la terminal) al terminar — cerrar la pestaña del
  navegador no lo frena.
- No dejar la notebook desatendida y desbloqueada mientras sirve datos.
