"""
Tema visual compartido — paleta Swiss Medical y layout base de gráficos.

Centraliza los colores y el layout de Plotly que antes vivían duplicados (o
directamente ausentes: el Módulo 3 usaba una paleta genérica violeta/azul que
rompía la identidad visual al navegar entre módulos).
"""

from __future__ import annotations

# ── Paleta Swiss Medical ──
COLOR_ROJO    = "#E4002B"
COLOR_ROJO_DK = "#B8001F"
COLOR_GRIS    = "#797979"
COLOR_GRIS_DK = "#343A40"
COLOR_TEXTO   = "#212529"
COLOR_FONDO   = "#F8F9FA"
COLOR_BLANCO  = "#FFFFFF"

# Series comparadas (real vs simulado/predicho)
COLOR_PRINCIPAL  = COLOR_ROJO      # serie principal / modelo principal
COLOR_SECUNDARIO = COLOR_GRIS_DK   # serie de referencia (valor real, etc.)
COLOR_TERCIARIO  = COLOR_GRIS      # serie adicional (segundo modelo, etc.)


def layout_base(title: str = "", height: int = 450) -> dict:
    """Layout Plotly común a todos los gráficos de la app (tipografía Roboto,
    fondos y grillas Swiss Medical). Usar con fig.update_layout(**layout_base(...))."""
    return dict(
        title=dict(text=title, font=dict(color=COLOR_TEXTO, size=15, family="Roboto", weight="bold")),
        plot_bgcolor=COLOR_BLANCO,
        paper_bgcolor=COLOR_FONDO,
        font=dict(family="Roboto", color=COLOR_TEXTO),
        hovermode="x unified",
        height=height,
        xaxis=dict(
            title_font=dict(color=COLOR_TEXTO, size=13, weight="bold"),
            tickfont=dict(color=COLOR_TEXTO, size=11),
            gridcolor="#E9ECEF",
            linecolor="#E9ECEF",
        ),
        yaxis=dict(
            title_font=dict(color=COLOR_TEXTO, size=13, weight="bold"),
            tickfont=dict(color=COLOR_TEXTO),
            gridcolor="#E9ECEF",
            linecolor="#E9ECEF",
        ),
        legend=dict(font=dict(color=COLOR_TEXTO)),
    )
