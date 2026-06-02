# Seguridad de datos

El simulador maneja información sensible del negocio (consumo y valores por
prestador). Este documento define la política de seguridad, el modelo de
amenazas y los controles implementados.

## 1. Clasificación de la información

| Dato | Sensibilidad | Tratamiento |
| ---- | ------------ | ----------- |
| Credenciales de usuario | Alta | Hash bcrypt en `secrets.toml` (fuera del repo). |
| Cookie key de sesión | Alta | Secret, fuera del repo, rotable. |
| URLs de OneDrive/SharePoint | Media | Secret, fuera del repo. |
| Datasets de consumo/valores | Alta | Nunca versionados; cargados en runtime. |
| Modelos entrenados | Baja/Media | Versionados con Git LFS. |

## 2. Controles implementados

### Autenticación y sesión
- Login obligatorio (`streamlit-authenticator`) antes de renderizar cualquier
  contenido (`require_login()` corta la ejecución si no hay sesión válida).
- Contraseñas almacenadas **solo como hash bcrypt** (cost factor 12). El texto
  plano nunca toca el repositorio ni los logs.
- Cookie de sesión firmada con `cookie_key`, expiración configurable
  (`cookie_expiry_days`, default 7 días).
- Roles básicos (`admin` / `user`) disponibles vía `get_current_user()`.

### Gestión de secretos
- `.streamlit/secrets.toml` está en `.gitignore`. Solo se versiona la plantilla
  `.streamlit/secrets.toml.example`.
- `.dockerignore` excluye los secrets del build context de la imagen.
- En despliegue (Hugging Face Spaces), los secretos se cargan como *Repository
  secrets*, no como archivo.

### Datos de negocio
- Los Excel de consumo/valores y la carpeta `data/` están en `.gitignore`.
- Se cargan en runtime desde carpeta local, OneDrive o upload manual; no
  persisten en el repositorio.
- La caché de Streamlit es en memoria del proceso; se evita escribir datasets a
  disco.

### Logging
- Los logs **redactan automáticamente** campos sensibles (`password`, `token`,
  `cookie_key`, `secret`, `hash`) — ver `LOGGING.md`.
- La auditoría registra el *username* en intentos de login (éxito/fallo) pero
  **nunca** la contraseña tipeada.

### Capa de IA (cuando se habilite)
- Apagada por defecto; requiere flag explícito + API key.
- Solo se envían **datos agregados/anonimizados** (los que el usuario ya ve en
  pantalla), nunca el dataset completo ni columnas con PII.

## 3. Modelo de amenazas (resumen)

| Amenaza | Mitigación |
| ------- | ---------- |
| Fuga de credenciales por commit accidental | `.gitignore` + plantilla `*.example` + revisión de PR. |
| Acceso no autorizado a la app | Autenticación obligatoria + Space privado. |
| Exposición de datasets | Datos fuera del repo, cargados en runtime, caché en memoria. |
| Secretos en logs | Redacción automática por clave sensible. |
| Robo de sesión | Cookie firmada + expiración + HTTPS en el proxy de despliegue. |

## 4. Rotación y respuesta a incidentes

> **Importante (deuda histórica):** versiones anteriores del repositorio
> incluyeron `secrets.toml` con credenciales reales. Aunque el archivo ya **no
> se versiona**, sigue presente en el historial de git. Se recomienda:
>
> 1. **Rotar** la `cookie_key` y **resetear** las contraseñas de todos los
>    usuarios afectados.
> 2. Regenerar/limitar los links de OneDrive/SharePoint expuestos.
> 3. Opcionalmente, purgar el historial (`git filter-repo`) si la política de la
>    organización lo exige.

Procedimiento de rotación de `cookie_key`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# pegar el valor en .streamlit/secrets.toml (o en los secrets del despliegue)
```

## 5. Checklist antes de cada release

- [ ] No hay secrets ni datasets en el diff (`git status`, `git diff --staged`).
- [ ] `.streamlit/secrets.toml` sigue ignorado.
- [ ] Dependencias sin vulnerabilidades conocidas (`pip-audit`).
- [ ] Variables sensibles solo vía entorno/secrets, nunca hardcodeadas.
- [ ] Logs nuevos no exponen PII ni credenciales.
