# Guía de despliegue — Simulador CM en Streamlit Community Cloud

Prerequisitos: tener acceso al proyecto **gestor-clientes** en Supabase y al repo
`lucianonunnez/simulador_app` en GitHub.

---

## Paso 1 — Obtener la contraseña de Supabase

1. Ir al dashboard de Supabase: https://supabase.com/dashboard
2. Abrir el proyecto **gestor-clientes**.
3. Clic en el botón **"Connect"** (arriba a la derecha).
4. Seleccionar la pestaña **"Session pooler"** (no "Direct connection").
5. Copiar la URL completa. Tiene esta forma:

   ```
   postgresql://postgres.rjpvmpjhuyhuhsuilnsg:[TU-PASSWORD]@aws-0-sa-east-1.pooler.supabase.com:5432/postgres
   ```

   Guardar esa URL — la vas a necesitar en el Paso 2 y en el Paso 3.

> **Por qué el pooler y no la conexión directa:** Streamlit Community Cloud solo
> tiene IPv4. La conexión directa de Supabase (`db.<ref>.supabase.co`) es solo
> IPv6 → timeout silencioso desde la nube. El Session Pooler tiene IPv4.

> **Si no tenés la password:** Supabase → Settings → Database → "Reset database
> password". Rotarla invalida conexiones existentes, así que coordiná con el equipo.

---

## Paso 2 — Configurar Streamlit Community Cloud

### 2.1 — Conectar el repo

1. Ir a https://share.streamlit.io → "New app".
2. Completar:
   - **Repository:** `lucianonunnez/simulador_app`
   - **Branch:** `main` (o la rama de producción que corresponda)
   - **Main file path:** `src/streamlit_app.py`
3. Clic en **"Advanced settings"** antes de deployar.

### 2.2 — Pegar los Secrets

En "Advanced settings → Secrets", pegar el bloque completo. Reemplazá
`[TU-PASSWORD]` con la contraseña del Paso 1 y verificá que el host tenga el
prefijo correcto (`aws-0` o `aws-1`, confirmalo en el dashboard).

```toml
cookie_key = "2b0b6ab7cc1d8b3ddfe3f14f70ed7649eb579f383c670a97937f272a4ae4b09f"
cookie_name = "simulador_cm_auth"
cookie_expiry_days = 1
supabase_db_url = "postgresql://postgres.rjpvmpjhuyhuhsuilnsg:[TU-PASSWORD]@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"

[credentials.usernames.luciano]
name = "Luciano Núñez"
email = "lucianonunnez@gmail.com"
password = "$2b$12$sKF8sN3oj1S3hKIXJL6BBOHKwVnB25uCIafXpx8.htuVrD/lzw.Jy"

[credentials.usernames.leo]
name = "Leo"
email = ""
password = "$2b$12$1VyU4p9YTDfIjXjD75FxieCHC8KPdS8JswI6bl2cnE/b7bSrS.g9y"

[credentials.usernames.lucas]
name = "Lucas"
email = ""
password = "$2b$12$jRMBZ6EQ4pG9OODmQfxtreQKpUxW11dX.wPxNUC7ulcIiuXvVISjq"
```

Contraseñas de los usuarios (para compartir de forma segura, NO por este canal):

| Usuario | Contraseña |
|---------|-----------|
| luciano | Medicina.Admin |
| leo | Medicina.Leo |
| lucas | Medicina.Lucas |

> Los hashes ya están generados con bcrypt cost 12. Si necesitás rotarlos:
> `python scripts/gen_credentials.py` (genera hash para un password dado).

### 2.3 — Deployar

Clic en **"Deploy"**. Streamlit instala las dependencias (`requirements.txt`) y
levanta la app. El primer build tarda ~3-5 minutos.

---

## Paso 3 — Cargar datos a Supabase (ingesta)

La ingesta se corre **desde tu máquina local**, una vez por cada actualización de
datos. La app en la nube lee esos datos de Supabase.

### 3.1 — Preparar los Excel

Dejar los archivos exportados de MicroStrategy en:

```
data/raw/consumo/     ← exports del reporte Consumo
data/raw/valores/     ← exports del reporte Valores
```

### 3.2 — Exportar la URL de conexión

En la terminal (Windows PowerShell):

```powershell
$env:DATABASE_URL = "postgresql://postgres.rjpvmpjhuyhuhsuilnsg:[TU-PASSWORD]@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
```

En Mac/Linux (bash):

```bash
export DATABASE_URL="postgresql://postgres.rjpvmpjhuyhuhsuilnsg:[TU-PASSWORD]@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
```

### 3.3 — Correr la ingesta

```bash
# Ver qué hay cargado actualmente:
python scripts/ingest.py --status

# Ingesta incremental (agrega/actualiza sin borrar lo existente):
python scripts/ingest.py

# Si necesitás reconstruir desde cero (borra y recarga todo):
python scripts/ingest.py --rebuild
```

La ingesta es **idempotente**: correrla dos veces con los mismos archivos no
duplica datos (hace upsert por clave `Prestador ID + Mes`).

---

## Paso 4 — Verificación

Una vez que la app esté deployada y los datos cargados:

1. Abrir la URL de la app (la que da Streamlit Cloud, del estilo
   `https://simulador-cm.streamlit.app` o similar).
2. Hacer login con cada usuario (`luciano`, `leo`, `lucas`) y verificar que entran.
3. Ir al módulo **"Base"** → confirmar que los prestadores aparecen en el panel.
4. Ir al módulo **"Simulador"** → cargar un prestador y verificar que los datos
   de consumo y valores se muestran correctamente.

Si la app carga pero no muestra datos:
- Verificar que la ingesta del Paso 3 completó sin errores.
- Verificar que `supabase_db_url` en los Secrets tiene la password correcta.
- En Supabase → Table Editor → schema `simulador`: las tablas `consumo` y
  `valores` deben tener filas.

---

## Rotación de credenciales

**Si se filtró la password de Supabase:**

1. Supabase → Settings → Database → "Reset database password".
2. Actualizar `supabase_db_url` en los Secrets de Streamlit Cloud.
3. Actualizar `DATABASE_URL` en todos los scripts locales.
4. Volver a correr `scripts/ingest.py` si la ingesta local quedó con la URL vieja.

**Si se filtró el `cookie_key`:**

1. Generar uno nuevo: `python -c "import secrets; print(secrets.token_hex(32))"`
2. Actualizar en los Secrets de Streamlit Cloud.
3. Todos los usuarios deberán hacer login de nuevo (las cookies existentes se invalidan).

**Para agregar o cambiar contraseñas de usuarios:**

```bash
python scripts/gen_credentials.py
```

Actualizar el hash correspondiente en los Secrets de Streamlit Cloud.

---

## Referencia rápida de archivos

| Archivo | Descripción |
|---------|-------------|
| `.streamlit/secrets.toml` | Secrets locales (gitignored, nunca versionar) |
| `.streamlit/secrets.toml.example` | Plantilla documentada |
| `scripts/ingest.py` | Ingesta Excel → Supabase |
| `scripts/gen_credentials.py` | Generador de hashes bcrypt |
| `docs/DESPLIEGUE_SEGURO.md` | Guía de seguridad completa |
| `ARQUITECTURA.md` | Arquitectura y decisiones técnicas |
