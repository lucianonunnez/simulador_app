# 🟢 Fuente de datos: Supabase (PostgreSQL)

La app puede leer los datos desde **Supabase** (Postgres en la nube) en vez de
la base **DuckDB local**. Supabase es la **fuente de verdad** cuando la app la
usa un **equipo** o se publica en la **web**: una sola base central,
multiusuario, con backups y RLS.

> **Es opcional y no invasivo.** Si NO hay bloque `[supabase]` en los secrets,
> la app usa DuckDB local exactamente como antes. El conector remoto ni se
> importa. Podés alternar entre local y nube solo agregando/quitando ese bloque.

## Cómo está armado

- Las tablas viven en el schema **`simulador`** de Supabase: `consumo`,
  `valores`, `_ingest_log`. **Mismo contrato de columnas** que DuckDB.
- El conector (`src/core/db_remote.py`) usa **conexión directa a Postgres**
  (psycopg2) con un pool de conexiones, y **empuja los filtros** (prestador /
  mes) al `WHERE` igual que el push-down de DuckDB: trae solo lo necesario.
- `src/core/data_loader.py` decide la fuente en runtime: si Supabase está
  configurado, va a la nube; si no, a DuckDB.

## Configuración

1. **Instalar dependencias** (ya incluye el driver):

   ```bash
   pip install -r requirements.txt
   ```

2. **Connection string** desde el Dashboard de Supabase:
   *Project Settings → Database → Connection string*. Recomendado: el
   **Connection pooler** (Supavisor) en modo *session* (host
   `...pooler.supabase.com`, usuario `postgres.<project-ref>`).

3. **Pegar en `.streamlit/secrets.toml`**:

   ```toml
   [supabase]
   database_url = "postgresql://postgres.<project-ref>:TU_PASSWORD@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
   schema = "simulador"
   ```

   En deploy (sin archivo de secrets) se puede usar la variable de entorno
   `SUPABASE_DATABASE_URL` (y opcional `SUPABASE_SCHEMA`).

4. Listo: la app levanta leyendo de Supabase. El botón **"Recargar datos"** del
   sidebar limpia el caché tras una nueva carga.

## Notas de seguridad

- La conexión usa el rol **`postgres`**, que **bypassa RLS** — correcto para un
  backend server-side que debe leer todo el universo. La RLS de las tablas
  protege el acceso *client-side* (anon key), no esta conexión.
- El `database_url` lleva la contraseña: vive solo en `secrets.toml` (gitignored)
  o en variables de entorno del deploy. **Nunca** se versiona.
- Para endurecer más adelante: crear un rol dedicado de **solo lectura** sobre
  el schema `simulador` y usar esa credencial en la app.

## Pendiente (siguiente paso)

- **Ingesta hacia Supabase.** Hoy el conector resuelve la **lectura**. El script
  `scripts/ingest.py` todavía escribe a DuckDB; falta el camino de ingesta
  (Excel de MicroStrategy → Supabase) para cerrar el ciclo en la nube.
