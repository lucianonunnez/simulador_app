"""
CSS global de la app — identidad Swiss Medical.

Vivía inline en streamlit_app.py (150 líneas en el entry point); acá queda
mantenible y versionado junto al resto del tema (ui/theme.py para Plotly).
"""

from __future__ import annotations

import streamlit as st

_CSS = """
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

/* ── Navegación como menú (radio del sidebar) ── */
[data-testid="stSidebar"] .stRadio > div[role="radiogroup"] > label {
    display: flex;
    align-items: center;
    padding: 9px 12px;
    margin: 2px 0;
    border-radius: 8px;
    border-left: 3px solid transparent;
    transition: background 0.15s ease;
    cursor: pointer;
}
[data-testid="stSidebar"] .stRadio > div[role="radiogroup"] > label:hover {
    background-color: #FFF0F3;
}
/* Ítem seleccionado: pill rosada + borde rojo (requiere :has, fallback: punto nativo) */
[data-testid="stSidebar"] .stRadio > div[role="radiogroup"] > label:has(input:checked) {
    background-color: #FFF0F3;
    border-left: 3px solid #E4002B;
    font-weight: 600;
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

/* ── Tabs ── */
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

/* ── Métricas nativas ── */
[data-testid="stMetric"] {
    background-color: #FFFFFF;
    border: 1px solid #E9ECEF;
    border-radius: 10px;
    padding: 16px !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
}
[data-testid="stMetricLabel"] {
    font-size: 13px !important;
    color: #5A5A5A !important;
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

/* ── Caption (contraste mejorado: #797979 quedaba al límite de WCAG) ── */
[data-testid="stCaptionContainer"] {
    color: #5A5A5A !important;
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
"""


def inject_css() -> None:
    """Inyecta el CSS global. Llamar una vez al inicio del entry point."""
    st.markdown(_CSS, unsafe_allow_html=True)


def _logo_mark(px: int = 13, gap: int = 3) -> str:
    """Isotipo Swiss Medical en CSS puro: 4 cuadrados rojos en grilla 2x2
    (la cruz blanca es el espacio entre ellos). Nítido a cualquier tamaño."""
    cuadrado = (
        f'<div style="width:{px}px; height:{px}px; background:#E4002B; '
        f'border-radius:{max(px // 5, 2)}px;"></div>'
    )
    return (
        f'<div style="display:grid; grid-template-columns:{px}px {px}px; '
        f'gap:{gap}px;">{cuadrado * 4}</div>'
    )


def brand_header_sidebar() -> str:
    """HTML del bloque de marca del sidebar."""
    return f"""
    <div style="padding: 4px 0 14px 0; border-bottom: 1px solid #E9ECEF; margin-bottom: 12px;">
        <div style="display:flex; align-items:center; gap:10px;">
            {_logo_mark(px=12, gap=3)}
            <div>
                <div style="font-size:15px; font-weight:700; color:#212529; line-height:1.1;">
                    Simulador de Costo Médico
                </div>
                <div style="font-size:11px; color:#5A5A5A; letter-spacing:0.5px;">
                    SWISS MEDICAL
                </div>
            </div>
        </div>
    </div>
    """


def brand_header_login() -> str:
    """HTML del encabezado de la pantalla de login."""
    return f"""
    <div style="text-align:center; padding: 36px 0 8px 0;">
        <div style="display:inline-flex; align-items:center; gap:12px;">
            {_logo_mark(px=16, gap=4)}
            <div style="text-align:left;">
                <div style="font-size:22px; font-weight:700; color:#212529; line-height:1.1;">
                    Simulador de Costo Médico
                </div>
                <div style="font-size:12px; color:#5A5A5A; letter-spacing:1px;">
                    SWISS MEDICAL · ACCESO RESTRINGIDO
                </div>
            </div>
        </div>
    </div>
    """
