# 🏗️ Arquitectura y plan de evolución — Simulador CM

> Documento de referencia. Resume cómo está armado el proyecto hoy y el camino
> recomendado para llevarlo a "producto serio" sin reescribir todo de una.
>
> **Contexto:** objetivo = producto serio/productivo. La app se despliega en
> **Streamlit Community Cloud** y los datos viven en **Supabase** (PostgreSQL).
>
> **🔒 Decisión tomada:** la capa de datos es **Supabase/PostgreSQL** (proyecto
> `gestor-clientes`, región AWS `sa-east-1`), en un **schema `simulador`
> dedicado** aislado del resto de tablas del proyecto. El hosting cloud de los
> datos (agregados por prestador, **nunca** a nivel paciente) está **aprobado**.
> Reemplaza el approach anterior de DuckDB local. Para conectar desde la nube se
> usa el **Session Pooler** (IPv4); la conexión directa (IPv6) no funciona desde
> Streamlit Cloud.

---

## 1. Aclaración clave: Streamlit y Supabase NO compiten

Resuelven capas distintas. No hay que elegir entre uno y otro.

| Pieza | Rol | Capa |
|---|---|---|
| **Streamlit** | UI + lógica + servidor, todo junto en Python | Frontend **y** backend |
| **Supabase (PostgreSQL)** | Dónde viven los datos (Excel bajado a mano → schema `simulador`) | Datos |
| **models/** | Modelos ML pre-entrenados (LightGBM + red neuronal) | ML |
| **streamlit-authenticator + secrets.toml** | Login (usuarios con hash bcrypt hardcodeado) | Auth |
| **Docker** | Empaqueta la app para desplegarla | Deploy/infra |

- **Supabase (PostgreSQL)** reemplaza la capa de datos (antes DuckDB local), NO a Streamlit.
- **Docker** no es alternativa a nada: es *cómo* se despliega. Se queda igual.
- **Streamlit** eventualmente se reemplaza por un frontend real, pero recién en la última fase.

Los datos se descargan a mano de MicroStrategy, se cargan a **Supabase
(PostgreSQL)** con `scripts/ingest.py`, y `src/core/data_loader.py` los
**consulta con filtros** (no carga todo a RAM como hacía antes con Excel + pandas).

---

## 2. Estructura actual del código

La separación en capas **ya está bien hecha**:

```
src/
├── core/      → LÓGICA pura (datos, ML, simulación, anomalías)   ← el "backend" embrionario
├── ui/        → PRESENTACIÓN (controles, tabs, formatters)        ← la "vista"
├── modules/   → ORQUESTA (cada módulo = una página)               ← el "router"
└── streamlit_app.py → entry point
```

**Hecho:** se borraron `core/ml_controls.py` y `core/ml_tabs.py` (eran código
muerto: los módulos importan de `ui.ml_controls` / `ui.ml_tabs`, no de `core`).
También se extrajo el parseo de Excel a `core/excel_utils.py` (Python puro, sin
Streamlit) para reutilizarlo desde el script de ingesta — primer paso del
desacople de `core/`.

Esa separación es la que facilita evolucionar: **`core/` ya es casi un backend**,
solo está acoplado a Streamlit por dentro (usa `st.cache_data`, `st.error`, etc.).

---

## 3. Arquitectura objetivo (producto serio)

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Frontend   │────▶│   Backend    │────▶│  Supabase   │
│ React/Next  │ API │   FastAPI    │ SQL │  Postgres   │
│ (o Streamlit│     │ (= tu core/) │     │  + Auth     │
│  por ahora) │     │  + modelos ML│     │  + Storage  │
└─────────────┘     └──────────────┘     └─────────────┘
        Todo empaquetado y desplegado con Docker
```

- Streamlit **eventualmente** se reemplaza por React/Next, pero **no ahora**.
- Supabase reemplaza Excel/OneDrive.
- Docker empaqueta todo.

### Qué aporta Supabase
- Consultas SQL con filtros (no cargar el 100% a memoria en cada sesión).
- Auth de verdad (reemplaza el `secrets.toml` con contraseñas hardcodeadas).
- Storage para archivos + Row Level Security + API accesible desde cualquier lado.
- Un solo origen de datos en vez de "tirame el Excel de Power BI".

### ✅ Compliance de datos en la nube — resuelto
Son **datos sensibles** (agregados por prestador, **nunca** a nivel paciente).
El hosting en Supabase cloud está **aprobado**. Mitigaciones aplicadas:
- Los datos viven en un **schema `simulador` dedicado**, aislado del resto del
  proyecto y **no expuesto** por la API REST pública (PostgREST solo publica
  `public`); el acceso es por conexión directa autenticada (psycopg2).
- Región **`sa-east-1`** (São Paulo), no EE.UU.
- Acceso a la app por login con **bcrypt** (cost 12) y cookie firmada.
- La connection string es un **secreto** (Streamlit Secrets / `DATABASE_URL`),
  nunca versionado. Se revisan los `get_advisors` de Supabase tras cambios de schema.

---

## 4. Camino recomendado (incremental, de mayor a menor impacto)

Como hoy se prueba en la compu, **no** tiene sentido el split completo todavía.

### 🟢 Fase 0 — Limpieza (rápido, sin dependencias externas)
- Borrar los 2 archivos muertos de `core/` (`ml_controls.py`, `ml_tabs.py`).
- **Desacoplar `core/` de Streamlit** (que la lógica no llame a `st.*`).
  Clave: una vez que `core/` es Python puro, se puede envolver en FastAPI
  *o* seguir usándolo desde Streamlit sin tocar nada.

### 🟡 Fase 1 — Datos a Supabase (PostgreSQL) ✅ hecho
- Base **Supabase/PostgreSQL**, schema `simulador`, tablas `consumo` y `valores`.
- Script de ingesta idempotente: Excel (bajado a mano) → Supabase, con upsert por
  `(Prestador ID, Mes)` (`scripts/ingest.py`, usando `DATABASE_URL`).
- Reescrito **solo** `data_loader.py` (y `core/db.py`) para consultar Supabase vía
  psycopg2 en vez de leer Excel. Todo lo demás (módulos, ML, UI) **no se tocó**.
- **Historial:** una etapa intermedia usó DuckDB local (cuando la nube no estaba
  aprobada). Con el hosting aprobado se migró a Supabase para poder desplegar en
  Streamlit Community Cloud y que varios usuarios compartan el mismo origen de datos.

### 🟣 Fase futura — Modelado dimensional
- **✅ Hecho:** migración a PostgreSQL (Supabase).
- Pendiente: esquema en estrella con `dim_prestador` (coordinación) para la
  comparativa por coordinación. El SQL del `data_loader` cambia poco (mismo
  modelo relacional).

### 🟠 Fase 2 — Backend real
- Envolver `core/` en FastAPI. Streamlit pasa a consumir la API.
- Ahí ya tenés backend separado.

### 🔵 Fase 3 — Frontend productivo
- Reemplazar la UI de Streamlit por React/Next cuando necesites
  diseño / roles / performance reales.

---

## 5. Recomendación concreta

Se arrancó por **Fase 0 + Fase 1**: es lo que más valor da con menos riesgo, y
deja la base lista para todo lo demás. Streamlit se queda de "frontend
provisorio" mientras se valida el modelo de datos.

**Estado / próximos pasos:**
- **✅ Fase 0** — borrado código muerto; parseo de Excel extraído a `excel_utils.py`.
- **✅ Fase 1** — datos en Supabase (PostgreSQL) + `scripts/ingest.py` + `data_loader` que consulta SQL.
- **⏭️ Deploy** — Streamlit Community Cloud (ver `docs/DESPLIEGUE_SEGURO.md`).
- **⏭️ Fase futura** — modelado dimensional (`dim_prestador`) y, eventualmente, backend FastAPI.

---

## Apéndice — Notas de entorno (importantes para correr el proyecto)

- El **venv vive FUERA de OneDrive**: `C:\Users\lununez\venvs\simulador_cm`.
  Motivo: el antivirus corporativo (Trend Micro "Web Reputation") corrompe los
  `.py` del venv cuando está dentro de OneDrive (les borra el contenido y los
  renombra a `.py.txt`). **No recrear el venv dentro de la carpeta de OneDrive.**
- Instalar dependencias siempre con `--trusted-host` (el proxy corporativo bloquea
  el SSL de PyPI):
  ```bash
  pip install -r requirements.txt --trusted-host pypi.org --trusted-host files.pythonhosted.org
  ```
- Levantar la app:
  ```bash
  cd "C:\Users\lununez\OneDrive - Swiss Medical S.A\Escritorio\Simulador CM"
  C:\Users\lununez\venvs\simulador_cm\Scripts\python.exe -m streamlit run src\streamlit_app.py
  ```
- URLs: `http://localhost:8501` (local) o `http://10.11.45.103:8501` (por IP en la red).
- Para cerrar el server de verdad: Ctrl+C en la terminal (cerrar la pestaña del
  navegador no lo frena).
