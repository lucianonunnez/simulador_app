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
La app **detecta automáticamente** los archivos de la carpeta `data/`, así que
no hay que subir nada: arranca con los datos ya cargados.

---

## Opción B — Docker (igual a producción)

Requiere **Docker** instalado.

```bash
docker build -t simulador-cm .
docker run -p 8501:8501 simulador-cm
```

Luego abrir `http://localhost:8501`.

> ⚠️ Nota: la imagen Docker **no** incluye la carpeta `data/` (por diseño, para no
> meter datos sensibles en la imagen). Con Docker, los datos se cargan desde OneDrive
> o subiéndolos a mano desde el panel lateral. Para una demo rápida con datos ya
> cargados, usá la **Opción A**.

---

## 🔑 Acceso (login)

La app pide usuario y contraseña. Los usuarios están definidos en
`.streamlit/secrets.toml`. Usá las credenciales que ya tenés configuradas.

---

## 📂 Qué hay en el paquete

```
├── src/                 Código de la app (Streamlit)
├── models/              Modelos ML pre-entrenados (LightGBM + red neuronal)
├── data/                Datos de ejemplo (consumo.xlsx, valores.xlsx)
├── .streamlit/          Configuración visual + credenciales (secrets.toml)
├── Dockerfile           Para correr en contenedor / desplegar
├── requirements.txt     Dependencias de Python
└── CÓMO_CORRERLO.md     Este archivo
```

> 🔒 **Seguridad:** este paquete contiene credenciales reales y datos médicos en
> `.streamlit/secrets.toml` y `data/`. No lo subas a repositorios públicos ni lo
> compartas por canales abiertos.
