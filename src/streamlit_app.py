"""
Simulador de Costo Médico
Entry point de la aplicación Streamlit.
v0.6.0 — diseño Swiss Medical
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
from modules import module1, module2, module3
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
# NAVEGACIÓN
# ============================================================================
MODULOS = [
    "Inicio",
    "Módulo 1 — Simulador",
    "Módulo 2 — Desvíos",
    "Módulo 3 — Predicción ML",
]

# Handoff de navegación: los botones de las cards de Inicio no pueden tocar
# el estado del radio una vez instanciado, así que dejan el destino acá y se
# aplica ANTES de renderizar el radio en el próximo run.
if "_nav_destino" in st.session_state:
    st.session_state["nav_modulo"] = st.session_state.pop("_nav_destino")

user = get_current_user()
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

    # ── Hero compacto con marca ──
    st.markdown(f"""
    <div style="padding: 4px 0 0 0;">
        <div style="font-size:13px; font-weight:700; color:#E4002B;
                    letter-spacing:1.5px; text-transform:uppercase;">
            Swiss Medical
        </div>
        <div style="font-size:28px; font-weight:700; color:#212529;
                    line-height:1.2; margin-top:2px;">
            Simulador de Costo Médico
        </div>
        <div style="font-size:14px; color:#5A5A5A; margin-top:6px;">
            Hola, {_nombre}. Elegí un módulo para empezar.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='margin-bottom:32px'></div>", unsafe_allow_html=True)

    # ── Estado de los datos ──
    st.markdown("""
    <div style="font-size:11px; font-weight:700; color:#5A5A5A;
                letter-spacing:1px; text-transform:uppercase; margin-bottom:8px;">
        Estado de los datos
    </div>
    """, unsafe_allow_html=True)

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

    st.markdown("<div style='margin-bottom:32px'></div>", unsafe_allow_html=True)

    # ── Cards de módulos (accionables) ──
    st.markdown("""
    <div style="font-size:11px; font-weight:700; color:#5A5A5A;
                letter-spacing:1px; text-transform:uppercase; margin-bottom:8px;">
        Módulos
    </div>
    """, unsafe_allow_html=True)

    card_style = """
        background: #FFFFFF;
        border: 1px solid #E9ECEF;
        border-radius: 12px;
        padding: 20px 20px 14px 20px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        min-height: 132px;
    """
    badge_style = """
        display:inline-flex; align-items:center; justify-content:center;
        width:32px; height:32px; border-radius:50%;
        background:#FFF0F3; color:#E4002B;
        font-size:15px; font-weight:700;
        margin-bottom:12px;
    """
    cards = [
        ("1", "Módulo 1 — Simulador", "Simulador",
         "Cuánto impacta un aumento de tarifas, antes de negociarlo."),
        ("2", "Módulo 2 — Desvíos", "Desvíos",
         "Detectá costos fuera de lo esperado por prestador o prestación."),
        ("3", "Módulo 3 — Predicción ML", "Predicción",
         "Proyectá el costo de los próximos meses con modelos de ML."),
    ]

    cols = st.columns(3)
    for col, (num, destino, nombre_corto, valor) in zip(cols, cards):
        with col:
            st.markdown(f"""
            <div style="{card_style}">
                <div style="{badge_style}">{num}</div>
                <div style="font-size:16px; font-weight:700; color:#212529; margin-bottom:6px;">
                    {nombre_corto}
                </div>
                <div style="font-size:13px; color:#5A5A5A; line-height:1.5;">
                    {valor}
                </div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(
                "Abrir módulo →", key=f"abrir_{destino}", use_container_width=True
            ):
                st.session_state["_nav_destino"] = destino
                st.rerun()


# ============================================================================
# ROUTER
# ============================================================================
if modulo == "Inicio":
    _render_inicio()
elif modulo == "Módulo 1 — Simulador":
    module1.render()
elif modulo == "Módulo 2 — Desvíos":
    module2.render()
elif modulo == "Módulo 3 — Predicción ML":
    module3.render()
