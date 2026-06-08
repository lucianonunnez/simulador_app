# 🏗️ Arquitectura y plan de evolución — Simulador CM

> Documento de referencia. Resume cómo está armado el proyecto hoy y el camino
> recomendado para llevarlo a "producto serio" sin reescribir todo de una.
>
> **Contexto al momento de escribir esto:** objetivo = producto serio/productivo,
> pero hoy se ejecuta local en la compu, en fase de pruebas. Tema compliance de
> datos médicos en cloud → pendiente de definir (lo salteamos por ahora).

---

## 1. Aclaración clave: Streamlit y Supabase NO compiten

Resuelven capas distintas. No hay que elegir entre uno y otro.

| Pieza | Rol | Capa |
|---|---|---|
| **Streamlit** | UI + lógica + servidor, todo junto en Python | Frontend **y** backend |
| **Excel + OneDrive** | Dónde viven los datos hoy | Datos |
| **models/** | Modelos ML pre-entrenados (LightGBM + red neuronal) | ML |
| **streamlit-authenticator + secrets.toml** | Login (usuarios con hash bcrypt hardcodeado) | Auth |
| **Docker** | Empaqueta la app para desplegarla | Deploy/infra |

- **Supabase** reemplazaría a **Excel/OneDrive** (la capa de datos), NO a Streamlit.
- **Docker** no es alternativa a nada: es *cómo* se despliega. Se queda igual.
- **Streamlit** eventualmente se reemplaza por un frontend real, pero recién en la última fase.

Hoy los datos se leen de **Excel** (local / OneDrive / upload manual, ver
`src/core/data_loader.py`) y se cargan **enteros a memoria con pandas** en cada sesión.

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

**Detalle a corregir:** los módulos importan de `ui.ml_controls` y `ui.ml_tabs`,
así que **`core/ml_controls.py` y `core/ml_tabs.py` son código muerto** (copias
viejas que no se usan) → hay que borrarlos.

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

### ⚠️ Freno a resolver antes de producción
Son **datos médicos sensibles**. Mandarlos a Supabase cloud (servidores en EE.UU.)
probablemente choque con compliance de Swiss Medical. Opciones:
- Confirmar aprobación con seguridad/legales, o
- Usar **Supabase self-hosted** (on-premise), o
- Trabajar con **datos anonimizados**.

(Para la fase de pruebas local esto se saltea, pero hay que definirlo antes de productivo.)

---

## 4. Camino recomendado (incremental, de mayor a menor impacto)

Como hoy se prueba en la compu, **no** tiene sentido el split completo todavía.

### 🟢 Fase 0 — Limpieza (rápido, sin dependencias externas)
- Borrar los 2 archivos muertos de `core/` (`ml_controls.py`, `ml_tabs.py`).
- **Desacoplar `core/` de Streamlit** (que la lógica no llame a `st.*`).
  Clave: una vez que `core/` es Python puro, se puede envolver en FastAPI
  *o* seguir usándolo desde Streamlit sin tocar nada.

### 🟡 Fase 1 — Datos a Supabase (alto impacto)
- Crear proyecto Supabase (free tier para pruebas), tablas `consumo` y `valores`.
- Script de ingesta: Excel → Postgres (una vez, o cuando llega un Excel nuevo).
- Reescribir **solo** `data_loader.py` para consultar Supabase en vez de leer Excel.
- Todo lo demás (módulos, ML, UI) **no se toca**. Streamlit sigue igual.

### 🟠 Fase 2 — Backend real
- Envolver `core/` en FastAPI. Streamlit pasa a consumir la API.
- Ahí ya tenés backend separado.

### 🔵 Fase 3 — Frontend productivo
- Reemplazar la UI de Streamlit por React/Next cuando necesites
  diseño / roles / performance reales.

---

## 5. Recomendación concreta

Arrancar por **Fase 0 + Fase 1**: es lo que más valor da con menos riesgo, y deja
la base lista para todo lo demás. Streamlit se queda de "frontend provisorio"
mientras se valida el modelo de datos en Supabase.

**Próximos pasos posibles:**
- **(A)** Fase 0 — limpiar código muerto y desacoplar `core/` de Streamlit.
- **(B)** Fase 1 — esquema de Supabase + script de ingesta + nuevo `data_loader`
  (requiere crear proyecto Supabase y definir cloud vs self-hosted).
- **(C)** Las dos, en orden.

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
