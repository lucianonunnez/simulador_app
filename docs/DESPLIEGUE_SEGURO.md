# 🔒 Despliegue seguro — Simulador CM

> Cómo correr la app de forma segura en la notebook, sirviéndola por IP en la LAN
> de Swiss Medical para una demo. Pensado **como un experto en ciberseguridad**.
>
> **Modelo de amenaza:** notebook en la red corporativa, varios ejecutivos se
> loguean por IP, datos de prestadores confidenciales, **todo local** (sin nube).
> Los datos NUNCA son a nivel paciente (siempre agregado por prestador), pero
> igual son sensibles y no deben salir de la máquina.

---

## Checklist rápido (antes de cada demo)

- [ ] BitLocker activo en el disco.
- [ ] `secrets.toml` con `cookie_key` fuerte y passwords únicos por persona.
- [ ] App bindeada a la IP de la LAN, no a `0.0.0.0` público.
- [ ] Regla de firewall que permite el puerto **solo** desde la subred corporativa.
- [ ] VPN conectada (si la red lo requiere).
- [ ] Cerrar el server (Ctrl+C) al terminar la reunión.

---

## 1. Red — exposición mínima

La app debe ser alcanzable **solo desde la LAN corporativa**, nunca desde Internet.

- Servir bindeando a la IP de la red, no exponer al mundo:
  ```bash
  streamlit run src/streamlit_app.py --server.address 10.11.45.103 --server.port 8501
  ```
- **Nada de túneles** (ngrok, Cloudflare Tunnel, etc.) ni port-forwarding en el router.
- Si la red lo exige, conectarse por **VPN** antes de levantar la app.

## 2. Firewall de Windows — regla acotada

Permitir el puerto 8501 **solo** desde la subred corporativa, no desde "cualquiera":

```powershell
New-NetFirewallRule -DisplayName "Simulador CM (LAN)" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8501 `
  -RemoteAddress 10.11.0.0/16 -Profile Domain,Private
```

- Ajustar `10.11.0.0/16` a la subred real de la oficina.
- **Bloquear** el perfil `Public`. Nunca `-RemoteAddress Any`.
- Borrar la regla cuando no se usa más:
  `Remove-NetFirewallRule -DisplayName "Simulador CM (LAN)"`.

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

- **BitLocker** (cifrado de disco completo) activo: es el control compensatorio de
  tener datos sensibles en una notebook. Cubre `data/` y `data/simulador.duckdb`.
- La base DuckDB y los Excel en `data/` están en `.gitignore`: no se versionan ni
  se suben jamás.

## 7. Auditoría de acceso

Para trazabilidad (valioso en datos médicos), registrar en un log local
(`logs/auth_audit.log`, gitignored):

- Login: timestamp, usuario, éxito/fallo, IP origen.
- Acceso a datos: qué prestador consultó cada usuario.

> Pendiente de implementar en `src/auth.py` (próximo paso del hardening).

## 8. Transporte (TLS)

HTTP en la LAN manda las contraseñas **en texto plano** (sniffeables por alguien en
la misma red). Lo correcto es ponerle **TLS con un reverse proxy local** (Caddy o
nginx con certificado self-signed) delante de Streamlit. Para una demo puntual es
opcional, pero es la mejora "bien hecha" antes de un uso recurrente.

## 9. Operación

- Correr la app como usuario **no-administrador**.
- **Cerrar el server** (Ctrl+C en la terminal) al terminar — cerrar la pestaña del
  navegador no lo frena.
- No dejar la notebook desatendida y desbloqueada mientras sirve datos.
