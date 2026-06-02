"""
Simulador de Costo Médico
Entry point de la aplicación Streamlit.
v0.5.2 — diseño Swiss Medical
"""

import streamlit as st

from auth import require_login, render_logout, get_current_user
from modules import module1, module2, module3

# ============================================================================
# CONFIGURACIÓN DE PÁGINA
# ============================================================================
st.set_page_config(
    page_title="Simulador Costo Médico",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================================
# CSS GLOBAL — estilo Swiss Medical
# ============================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Roboto', sans-serif !important;
}

/* ── Fondo general ── */
.stApp { background-color: #F8F9FA; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background-color: #FFFFFF;
    border-right: 1px solid #E9ECEF;
}
[data-testid="stSidebar"] * {
    font-family: 'Roboto', sans-serif !important;
}

/* ── Títulos ── */
h1 {
    font-family: 'Roboto', sans-serif !important;
    font-weight: 700 !important;
    color: #212529 !important;
    border-left: 4px solid #E4002B;
    padding-left: 12px;
}
h2, h3 {
    font-family: 'Roboto', sans-serif !important;
    font-weight: 600 !important;
    color: #212529 !important;
}

/* ── Botones primarios ── */
.stButton > button {
    background-color: #E4002B !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 24px !important;
    font-family: 'Roboto', sans-serif !important;
    font-weight: 500 !important;
    padding: 8px 24px !important;
    transition: background-color 0.2s ease;
}
.stButton > button:hover { background-color: #B8001F !important; }

/* ── Botón de descarga ── */
[data-testid="stDownloadButton"] > button {
    background-color: #FFFFFF !important;
    color: #E4002B !important;
    border: 1.5px solid #E4002B !important;
    border-radius: 24px !important;
    font-weight: 500 !important;
}
[data-testid="stDownloadButton"] > button:hover {
    background-color: #FFF0F3 !important;
}

/* ── Expanders ── */
[data-testid="stExpander"] {
    background-color: #FFFFFF;
    border: 1px solid #E9ECEF !important;
    border-radius: 10px !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}

/* ── TABS — sin emojis se definen en Python, aquí el estilo ── */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background-color: transparent;
    border-bottom: 2px solid #E9ECEF;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    font-family: 'Roboto', sans-serif !important;
    font-weight: 500;
    font-size: 14px;
    color: #797979;
    padding: 8px 16px;
    border-radius: 6px 6px 0 0;
    margin-right: 4px;
    background-color: transparent;
    border: none;
}
[data-testid="stTabs"] [data-baseweb="tab"]:hover {
    background-color: #FFF0F3;
    color: #E4002B;
}
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {
    background-color: #FFF0F3 !important;
    color: #E4002B !important;
    border-bottom: 2px solid #E4002B !important;
    font-weight: 700;
}

/* ── Tablas ── */
[data-testid="stDataFrame"] {
    border-radius: 8px !important;
    overflow: hidden;
    border: 1px solid #E9ECEF;
}

/* ── Métricas nativas (fallback) ── */
[data-testid="stMetric"] {
    background-color: #FFFFFF;
    border: 1px solid #E9ECEF;
    border-radius: 10px;
    padding: 16px !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
}
[data-testid="stMetricLabel"] {
    font-size: 13px !important;
    color: #797979 !important;
    font-weight: 500 !important;
}
[data-testid="stMetricValue"] {
    font-size: 26px !important;
    font-weight: 700 !important;
    color: #212529 !important;
}

/* ── Alertas ── */
[data-testid="stAlert"] {
    border-radius: 8px !important;
    border-left: 4px solid #E4002B !important;
}

/* ── Divider ── */
hr { border-color: #E9ECEF !important; }

/* ── Caption ── */
[data-testid="stCaptionContainer"] {
    color: #797979 !important;
    font-size: 13px !important;
}

/* ── Encabezados de tablas — fondo rosado Swiss ── */
[data-testid="stDataFrame"] thead tr th,
[data-testid="stDataFrame"] [data-testid="glideDataEditor"] .header-cell,
.dvn-header,
[role="columnheader"] {
    background-color: #FFF0F3 !important;
    color: #212529 !important;
    font-weight: 600 !important;
    font-family: 'Roboto', sans-serif !important;
    border-bottom: 2px solid #E4002B !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #F8F9FA; }
::-webkit-scrollbar-thumb { background: #CED4DA; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #797979; }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# AUTENTICACIÓN
# ============================================================================
require_login()

# ============================================================================
# APP PRINCIPAL
# ============================================================================
user = get_current_user()

with st.sidebar:
    st.markdown(f"""
    <div style="padding: 8px 0 16px 0;">
        <div style="font-size:15px; font-weight:700; color:#212529;">👤 {user['name']}</div>
        <div style="font-size:12px; color:#797979;">Conectado como <code>{user['username']}</code></div>
    </div>
    """, unsafe_allow_html=True)

    render_logout()
    st.divider()

    st.markdown("""
    <div style="font-size:11px; font-weight:700; color:#797979;
                letter-spacing:1px; text-transform:uppercase;
                padding: 4px 0 8px 0;">
        Navegación
    </div>
    """, unsafe_allow_html=True)

    modulo = st.radio(
        label="Módulo",
        options=[
            "Inicio",
            "Módulo 1 — Simulador",
            "Módulo 2 — Desvíos",
            "Módulo 3 — Predicción ML",
        ],
        label_visibility="collapsed",
        key="nav_modulo",
    )

    st.divider()
    st.caption("v0.5.2")

# ============================================================================
# ROUTER
# ============================================================================
if modulo == "Inicio":
    st.title("Simulador de Costo Médico")
    st.markdown("<div style='margin-bottom:32px'></div>", unsafe_allow_html=True)

    # Cards de módulos
    c1, c2, c3 = st.columns(3)

    card_style = """
        background: #FFFFFF;
        border: 1px solid #E9ECEF;
        border-radius: 12px;
        padding: 28px 24px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.06);
        height: 100%;
    """
    accent = "border-top: 3px solid #E4002B;"

    with c1:
        st.markdown(f"""
        <div style="{card_style}{accent}">
            <div style="font-size:28px; margin-bottom:12px;">📊</div>
            <div style="font-size:16px; font-weight:700; color:#212529; margin-bottom:8px;">
                Módulo 1 — Simulador
            </div>
            <div style="font-size:13px; color:#797979; line-height:1.5;">
                Proyección de impacto financiero por cambios de tarifas.
                Filtrá por prestador, mes y tipo de aumento.
            </div>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown(f"""
        <div style="{card_style}{accent}">
            <div style="font-size:28px; margin-bottom:12px;">🔍</div>
            <div style="font-size:16px; font-weight:700; color:#212529; margin-bottom:8px;">
                Módulo 2 — Desvíos
            </div>
            <div style="font-size:13px; color:#797979; line-height:1.5;">
                Detección de anomalías en costos por prestador,
                prestación o grupo con análisis temporal y estructural.
            </div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        st.markdown(f"""
        <div style="{card_style}{accent}">
            <div style="font-size:28px; margin-bottom:12px;">🤖</div>
            <div style="font-size:16px; font-weight:700; color:#212529; margin-bottom:8px;">
                Módulo 3 — Predicción ML
            </div>
            <div style="font-size:13px; color:#797979; line-height:1.5;">
                Pronóstico con LightGBM y red neuronal.
                Comparativa de modelos con métricas de performance.
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="margin-top:32px; padding:16px 20px;
                background:#FFF0F3; border-radius:8px;
                border-left: 3px solid #E4002B;
                font-size:13px; color:#212529;">
        Bienvenido, <strong>{user['name']}</strong> — 
        seleccioná un módulo en el menú de la izquierda para comenzar.
    </div>
    """, unsafe_allow_html=True)

elif modulo == "Módulo 1 — Simulador":
    module1.render()

elif modulo == "Módulo 2 — Desvíos":
    module2.render()

elif modulo == "Módulo 3 — Predicción ML":
    module3.render()