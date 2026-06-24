# ▶️ Cómo correr el Simulador de Costo Médico

Versión **v0.5.2**. Este paquete viene **listo para correr** (incluye código, modelos
y datos de ejemplo). Hay dos formas: local (la más rápida para mostrar) o con Docker.

---

## Opción A — Local (recomendada para mostrar) ⏱️ ~5 min

Requiere **Python 3.11** instalado.

```bash
# 1. Pararse en la carpeta del proyecto (donde está este archivo)

# 2. Crear un entorno virtual
python -m venv venv

# 3. Activarlo
#    Windows (PowerShell/CMD):
venv\Scripts\activate
#    Mac/Linux:
source venv/bin/activate

# 4. Instalar dependencias (tarda unos minutos la primera vez)
pip install -r requirements.txt

# 5. Levantar la app
streamlit run src/streamlit_app.py
```

Se abre solo en el navegador en `http://localhost:8501`.

La app consulta **Supabase** (PostgreSQL, schema `simulador`). Configurá la
connection string en `.streamlit/secrets.toml` (clave `supabase_db_url`, copiala
del **Session Pooler** del proyecto — ver `.streamlit/secrets.toml.example`).

Para cargar datos, dejá los Excel en `data/raw/consumo/` y `data/raw/valores/` y
corré la ingesta una vez (apuntando `DATABASE_URL` al mismo pooler):

```bash
export DATABASE_URL="postgresql://postgres.<ref>:<password>@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
python scripts/ingest.py
```

(Si no hay datos en la base, la app igual te deja subir los Excel a mano desde el
panel lateral para simular en el momento.)

---

## Opción B — Docker (igual a producción)

Requiere **Docker** instalado.

```bash
docker build -t simulador-cm .
docker run -p 8501:8501 simulador-cm
```

Luego abrir `http://localhost:8501`.

> ⚠️ Nota: la imagen Docker lee los datos desde **Supabase** (configurá
> `supabase_db_url` vía variable de entorno o secrets montados). No incluye datos
> en la imagen. Para una demo rápida, usá la **Opción A**.

---

## 🔑 Acceso (login)

La app pide usuario y contraseña. Los usuarios están definidos en
`.streamlit/secrets.toml`. Usá las credenciales que ya tenés configuradas.

---

## 📂 Qué hay en el paquete

```
├── src/                 Código de la app (Streamlit)
├── models/              Modelos ML pre-entrenados (LightGBM + red neuronal)
├── data/                Excel crudos en data/raw/ para la ingesta (NO versionado)
├── .streamlit/          Configuración visual + credenciales (secrets.toml)
├── Dockerfile           Para correr en contenedor / desplegar
├── requirements.txt     Dependencias de Python
└── CÓMO_CORRERLO.md     Este archivo
```

> 🔒 **Seguridad:** `.streamlit/secrets.toml` contiene credenciales reales (login
> + connection string de Supabase) y `data/raw/` puede contener Excel sensibles.
> Ambos están gitignored. No los subas a repos públicos ni los compartas por
> canales abiertos.
