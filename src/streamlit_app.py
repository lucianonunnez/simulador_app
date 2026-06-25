"""
Simulador de Costo Médico
Entry point de la aplicación Streamlit.
v0.6.1 — diseño Swiss Medical
"""

import html
import logging
import os
from pathlib import Path

# Silenciar el ruido informativo de TensorFlow en la terminal (banners de
# oneDNN/AVX2 y deprecations de Keras). Debe setearse ANTES de que cualquier
# módulo importe TF (el Módulo 3 lo hace lazy).
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
logging.getLogger("tensorflow").setLevel(logging.ERROR)

import streamlit as st

from auth import require_login, render_logout, get_current_user
from modules import module1, module2, module3, upload
from ui.formatters import format_int
from ui.styles import brand_header_sidebar, inject_css

# ============================================================================
# LOGGING — antes no había NINGÚN logging en la app: un fallo en vivo no
# dejaba rastro. basicConfig es no-op si ya hay handlers (reruns de Streamlit).
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# ============================================================================
# CONFIGURACIÓN DE PÁGINA
# ============================================================================
st.set_page_config(
    page_title="Simulador Costo Médico",
    page_icon=str(Path(__file__).parent / "ui" / "assets" / "favicon.png"),  # isotipo Swiss
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()

# ============================================================================
# AUTENTICACIÓN
# ============================================================================
require_login()

# ============================================================================
# NAVEGACIÓN — filtrada por rol
# ============================================================================
_MODULOS_ADMIN = [
    "Inicio",
    "Carga de Datos",
    "Módulo 1 — Simulador",
    "Módulo 2 — Desvíos",
    "Módulo 3 — Predicción ML",
]
_MODULOS_MANAGER = [
    "Inicio",
    "Módulo 1 — Simulador",
    "Módulo 2 — Desvíos",
    "Módulo 3 — Predicción ML",
]
_MODULOS_VIEWER = [
    "Inicio",
    "Módulo 1 — Simulador",
]

user = get_current_user()
MODULOS = {
    "admin": _MODULOS_ADMIN,
    "manager": _MODULOS_MANAGER,
    "viewer": _MODULOS_VIEWER,
}.get(user["role"], _MODULOS_VIEWER)
# Los datos de usuario se interpolan en HTML (unsafe_allow_html): escapar
# siempre, aunque hoy vengan de secrets.toml controlado por el admin.
_nombre = html.escape(user["name"])
_usuario = html.escape(user["username"])

with st.sidebar:
    st.markdown(brand_header_sidebar(), unsafe_allow_html=True)

    st.markdown("""
    <div style="font-size:11px; font-weight:700; color:#5A5A5A;
                letter-spacing:1px; text-transform:uppercase;
                padding: 0 0 6px 0;">
        Navegación
    </div>
    """, unsafe_allow_html=True)

    modulo = st.radio(
        label="Módulo",
        options=MODULOS,
        label_visibility="collapsed",
        key="nav_modulo",
    )

    st.divider()

    st.markdown(f"""
    <div style="padding: 0 0 8px 0;">
        <div style="font-size:13px; font-weight:600; color:#212529;">{_nombre}</div>
        <div style="font-size:11px; color:#5A5A5A;">Conectado como <code>{_usuario}</code></div>
    </div>
    """, unsafe_allow_html=True)
    render_logout()

    st.divider()
    st.caption("v0.6.0")

# ============================================================================
# INICIO
# ============================================================================
def _render_inicio() -> None:
    from core.data_loader import resumen_base

    st.title("Simulador de Costo Médico")
    st.caption(
        f"Bienvenido, **{_nombre}** — elegí un módulo desde el menú de la izquierda."
    )
    st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)

    # ── Estado de los datos ──
    resumen = resumen_base()
    if resumen:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Registros de consumo", format_int(resumen["filas"]))
        c2.metric("Prestadores", format_int(resumen["prestadores"]))
        c3.metric("Meses cargados", format_int(resumen["meses"]))
        c4.metric("Tarifas (valores)", format_int(resumen["tarifas"]))
    else:
        st.info(
            "**Todavía no hay datos cargados.** Abrí la sección "
            "**«Carga de datos»** del menú izquierdo: podés subir archivos o "
            "ingerir lo que dejes en `data/raw/` con un click."
        )

    st.markdown("<div style='margin-bottom:24px'></div>", unsafe_allow_html=True)

    # ── Cards de módulos (accionables) ──
    card_style = """
        background: #FFFFFF;
        border: 1px solid #E9ECEF;
        border-top: 3px solid #E4002B;
        border-radius: 12px;
        padding: 24px 22px 16px 22px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        min-height: 130px;
    """
    cards = [
        ("Módulo 1 — Simulador",
         "Proyección de impacto financiero por cambios de tarifas: escenarios "
         "Solicitado vs Propuesto, Extrapauta y exclusiones No pauta."),
        ("Módulo 2 — Desvíos",
         "Detección de anomalías en costos por prestador, prestación o grupo, "
         "con análisis temporal y estructural."),
        ("Módulo 3 — Predicción ML",
         "Pronóstico con LightGBM y red neuronal. Comparativa de modelos con "
         "métricas de performance."),
    ]

    cols = st.columns(3)
    for col, (titulo, desc) in zip(cols, cards):
        with col:
            st.markdown(f"""
            <div style="{card_style}">
                <div style="font-size:16px; font-weight:700; color:#212529; margin-bottom:8px;">
                    {titulo}
                </div>
                <div style="font-size:13px; color:#5A5A5A; line-height:1.5;">
                    {desc}
                </div>
            </div>
            """, unsafe_allow_html=True)


# ============================================================================
# ROUTER
# ============================================================================
if modulo == "Inicio":
    _render_inicio()
elif modulo == "Carga de Datos":
    upload.render()
elif modulo == "Módulo 1 — Simulador":
    module1.render()
elif modulo == "Módulo 2 — Desvíos":
    module2.render()
elif modulo == "Módulo 3 — Predicción ML":
    module3.render()
