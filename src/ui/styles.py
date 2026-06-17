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

/* ── Design tokens (identidad Swiss) ── */
:root {
    --sw-red: #E4002B;
    --sw-red-dark: #B8001F;
    --sw-text: #212529;
    --sw-text-2: #5A5A5A;
    --sw-bg: #F8F9FA;
    --sw-surface: #FFFFFF;
    --sw-border: #E9ECEF;
    --sw-pink: #FFF0F3;
    --sw-pink-border: #FAD3DB;
    --sw-radius-sm: 8px;
    --sw-radius: 12px;
    /* Sombras suaves y de bajo contraste: aportan profundidad sin "pesar" */
    --sw-shadow: 0 1px 2px rgba(16,24,40,0.05), 0 1px 3px rgba(16,24,40,0.04);
    --sw-shadow-hover: 0 6px 16px rgba(16,24,40,0.08), 0 2px 4px rgba(16,24,40,0.04);
    /* Botón rojo: sombra discreta tintada, no voluminosa */
    --sw-shadow-red: 0 1px 2px rgba(228,0,43,0.18);
    --sw-shadow-red-hover: 0 4px 10px rgba(228,0,43,0.20);
    --sw-ring: 0 0 0 3px rgba(228,0,43,0.30);
    --sw-ease: 0.18s cubic-bezier(0.4, 0, 0.2, 1);
}

html, body, [class*="css"] {
    font-family: 'Roboto', sans-serif !important;
    color: #212529;
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
[data-testid="stSidebar"] .stRadio > div[role="radiogroup"] {
    gap: 2px;
    display: flex;
    flex-direction: column;
}
[data-testid="stSidebar"] .stRadio > div[role="radiogroup"] > label {
    display: flex;
    align-items: center;
    min-height: 42px;
    padding: 9px 12px;
    margin: 0;
    border-radius: 8px;
    border-left: 3px solid transparent;
    color: #5A5A5A;
    font-weight: 500;
    font-size: 14px;
    transition: background var(--sw-ease), color var(--sw-ease);
    cursor: pointer;
}
[data-testid="stSidebar"] .stRadio > div[role="radiogroup"] > label:hover {
    background-color: #FFF0F3;
    color: #212529;
}
[data-testid="stSidebar"] .stRadio > div[role="radiogroup"] > label:focus-within {
    outline: none;
    box-shadow: var(--sw-ring);
}
/* Ítem seleccionado: pill rosada + borde rojo (requiere :has, fallback: punto nativo) */
[data-testid="stSidebar"] .stRadio > div[role="radiogroup"] > label:has(input:checked) {
    background-color: #FFF0F3;
    border-left: 3px solid #E4002B;
    color: #212529;
    font-weight: 600;
}

/* ── Tipografía / escala ── */
h1 {
    font-family: 'Roboto', sans-serif !important;
    font-weight: 700 !important;
    font-size: 30px !important;
    line-height: 1.2 !important;
    letter-spacing: -0.01em;
    color: #212529 !important;
    border-left: 4px solid #E4002B;
    padding-left: 14px;
    margin-bottom: 16px !important;
}
h2 {
    font-family: 'Roboto', sans-serif !important;
    font-weight: 600 !important;
    font-size: 22px !important;
    line-height: 1.3 !important;
    letter-spacing: -0.005em;
    color: #212529 !important;
}
h3 {
    font-family: 'Roboto', sans-serif !important;
    font-weight: 600 !important;
    font-size: 17px !important;
    line-height: 1.35 !important;
    color: #212529 !important;
}
p, li, label, .stMarkdown { font-size: 15px; line-height: 1.55; }

/* ── Botones primarios ── */
.stButton > button {
    background-color: #E4002B !important;
    color: #FFFFFF !important;
    border: 1px solid #E4002B !important;
    border-radius: 8px !important;
    font-family: 'Roboto', sans-serif !important;
    font-weight: 500 !important;
    font-size: 14px !important;
    letter-spacing: 0.1px;
    padding: 8px 18px !important;
    box-shadow: var(--sw-shadow-red);
    transition: background-color var(--sw-ease), box-shadow var(--sw-ease),
                transform 0.08s ease, border-color var(--sw-ease);
}
.stButton > button:hover {
    background-color: #B8001F !important;
    border-color: #B8001F !important;
    box-shadow: var(--sw-shadow-red-hover) !important;
    transform: translateY(-1px);
}
.stButton > button:active {
    transform: translateY(0);
    box-shadow: var(--sw-shadow-red) !important;
}
.stButton > button:focus-visible {
    outline: none !important;
    box-shadow: var(--sw-ring) !important;
}

/* Botón secundario (kind="secondary") — contorno sobrio */
.stButton > button[kind="secondary"] {
    background-color: #FFFFFF !important;
    color: #E4002B !important;
    border: 1px solid #E9ECEF !important;
    box-shadow: none !important;
}
.stButton > button[kind="secondary"]:hover {
    background-color: #FFF0F3 !important;
    border-color: #E4002B !important;
    box-shadow: none !important;
    transform: translateY(-1px);
}
.stButton > button[kind="secondary"]:active { transform: translateY(0); }

/* ── Botón de descarga ── */
[data-testid="stDownloadButton"] > button {
    background-color: #FFFFFF !important;
    color: #E4002B !important;
    border: 1px solid #E4002B !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    padding: 8px 18px !important;
    box-shadow: none !important;
    transition: background-color var(--sw-ease), box-shadow var(--sw-ease),
                transform 0.08s ease;
}
[data-testid="stDownloadButton"] > button:hover {
    background-color: #FFF0F3 !important;
    box-shadow: 0 2px 8px rgba(228,0,43,0.10) !important;
    transform: translateY(-1px);
}
[data-testid="stDownloadButton"] > button:active { transform: translateY(0); }
[data-testid="stDownloadButton"] > button:focus-visible {
    outline: none !important;
    box-shadow: var(--sw-ring) !important;
}

/* ── Card reutilizable ── */
.sw-card {
    background-color: #FFFFFF;
    border: 1px solid #E9ECEF;
    border-radius: 12px;
    padding: 20px;
    box-shadow: var(--sw-shadow);
    transition: box-shadow var(--sw-ease), transform var(--sw-ease),
                border-color var(--sw-ease);
}
.sw-card--clickable { cursor: pointer; }
.sw-card--clickable:hover {
    box-shadow: var(--sw-shadow-hover);
    border-color: #FAD3DB;
    transform: translateY(-2px);
}

/* Contenedores bordeados de Streamlit (st.container(border=True)) como card */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 12px !important;
    border: 1px solid #E9ECEF !important;
    box-shadow: var(--sw-shadow);
}

/* ── Inputs / selects ── */
[data-baseweb="input"],
[data-baseweb="select"] > div,
[data-baseweb="textarea"] {
    border-radius: 8px !important;
    transition: border-color var(--sw-ease), box-shadow var(--sw-ease);
}
[data-baseweb="input"]:focus-within,
[data-baseweb="select"] > div:focus-within,
[data-baseweb="textarea"]:focus-within {
    border-color: #E4002B !important;
    box-shadow: var(--sw-ring) !important;
}

/* ── Expanders ── */
[data-testid="stExpander"] {
    background-color: #FFFFFF;
    border: 1px solid #E9ECEF !important;
    border-radius: 12px !important;
    box-shadow: var(--sw-shadow);
    overflow: hidden;
}
[data-testid="stExpander"] summary {
    font-weight: 500;
    transition: color var(--sw-ease);
}
[data-testid="stExpander"] summary:hover { color: #E4002B; }

/* ── Tabs ── */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background-color: transparent;
    border-bottom: 1px solid #E9ECEF;
    gap: 4px;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    font-family: 'Roboto', sans-serif !important;
    font-weight: 500;
    font-size: 14px;
    color: #5A5A5A;
    padding: 8px 16px;
    border-radius: 8px 8px 0 0;
    background-color: transparent;
    border: none;
    transition: background var(--sw-ease), color var(--sw-ease);
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
    border-radius: 10px !important;
    overflow: hidden;
    border: 1px solid #E9ECEF;
    box-shadow: var(--sw-shadow);
}

/* ── Métricas nativas (card limpia) ── */
[data-testid="stMetric"] {
    background-color: #FFFFFF;
    border: 1px solid #E9ECEF;
    border-radius: 12px;
    padding: 18px 20px !important;
    box-shadow: var(--sw-shadow);
    transition: box-shadow var(--sw-ease), transform var(--sw-ease),
                border-color var(--sw-ease);
}
[data-testid="stMetric"]:hover {
    box-shadow: var(--sw-shadow-hover);
    border-color: #FAD3DB;
    transform: translateY(-2px);
}
[data-testid="stMetricLabel"] {
    font-size: 13px !important;
    color: #5A5A5A !important;
    font-weight: 500 !important;
    letter-spacing: 0.2px;
}
[data-testid="stMetricValue"] {
    font-size: 28px !important;
    font-weight: 700 !important;
    line-height: 1.15 !important;
    color: #212529 !important;
}

/* ── Alertas ── */
[data-testid="stAlert"] {
    border-radius: 10px !important;
    border-left: 4px solid #E4002B !important;
    box-shadow: var(--sw-shadow);
}

/* ── Divider ── */
hr { border-color: #E9ECEF !important; }

/* ── Caption (contraste mejorado: #797979 quedaba al límite de WCAG) ── */
[data-testid="stCaptionContainer"] {
    color: #5A5A5A !important;
    font-size: 13px !important;
    line-height: 1.45;
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
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: #F8F9FA; }
::-webkit-scrollbar-thumb { background: #CED4DA; border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #5A5A5A; }
* { scrollbar-color: #CED4DA #F8F9FA; }
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
                <div style="font-size:15px; font-weight:700; color:#212529; line-height:1.15;">
                    Simulador de Costo Médico
                </div>
                <div style="font-size:11px; color:#5A5A5A; letter-spacing:0.5px; margin-top:1px;">
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
                <div style="font-size:22px; font-weight:700; color:#212529; line-height:1.15;">
                    Simulador de Costo Médico
                </div>
                <div style="font-size:12px; color:#5A5A5A; letter-spacing:1px; margin-top:2px;">
                    SWISS MEDICAL · ACCESO RESTRINGIDO
                </div>
            </div>
        </div>
    </div>
    """
