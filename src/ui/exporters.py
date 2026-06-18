"""
Exportación unificada de tablas — CSV y PDF con formato "tabla" Swiss Medical.

Toda tabla de la app se exporta con el MISMO componente (`render_export_buttons`)
para que el usuario elija el formato (.csv o .pdf) y obtenga siempre el mismo
diseño: encabezado rojo, filas alternadas (banding), título y pie con metadatos.

El PDF se arma con reportlab (orientación apaisada, la tabla se reparte a lo
ancho y los textos largos envuelven). La generación es cacheada por huella del
DataFrame: solo se rearma cuando cambian los datos o el formato elegido.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pandas as pd
import streamlit as st

from core.cachekeys import df_fingerprint
from ui.formatters import format_int

# ── Paleta Swiss Medical (réplica de ui.theme para el PDF) ──
_ROJO       = "#E4002B"
_GRIS_BANDA = "#F5F5F5"
_GRIS_LINEA = "#E9ECEF"
_GRIS_TX    = "#797979"

# Tope de filas a volcar en el PDF: un PDF con cientos de miles de filas es
# inviable (peso y tiempo de armado). El CSV sigue incluyendo todo.
_PDF_MAX_FILAS = 1_500


# ============================================================================
# CSV
# ============================================================================
def df_to_csv_bytes(df: pd.DataFrame, include_index: bool = False) -> bytes:
    """CSV en UTF-8 con BOM (para que Excel abra acentos y el formato es-AR)."""
    return df.to_csv(index=include_index).encode("utf-8-sig")


@st.cache_data(show_spinner=False, max_entries=20,
               hash_funcs={pd.DataFrame: df_fingerprint})
def _csv_bytes_cached(df: pd.DataFrame, include_index: bool) -> bytes:
    """CSV cacheado: con el detalle completo (cientos de miles de filas)
    serializarlo en cada rerun costaba segundos."""
    return df_to_csv_bytes(df, include_index)


# ============================================================================
# PDF (estilo tabla Swiss Medical)
# ============================================================================
def _build_pdf(
    df: pd.DataFrame, title: str, subtitle: str | None, include_index: bool
) -> tuple[bytes, bool]:
    """Arma el PDF y devuelve (bytes, truncado)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    data = df.reset_index() if include_index else df
    n_total = len(data)
    truncado = n_total > _PDF_MAX_FILAS
    if truncado:
        data = data.head(_PDF_MAX_FILAS)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=title,
    )

    base = getSampleStyleSheet()
    st_title = ParagraphStyle(
        "swiss_title", parent=base["Title"], alignment=0,
        textColor=colors.HexColor(_ROJO), fontSize=16, spaceAfter=4,
    )
    st_sub = ParagraphStyle(
        "swiss_sub", parent=base["Normal"],
        textColor=colors.HexColor(_GRIS_TX), fontSize=9, spaceAfter=10,
    )
    st_cell = ParagraphStyle("swiss_cell", parent=base["Normal"], fontSize=7.5, leading=9)
    st_head = ParagraphStyle(
        "swiss_head", parent=base["Normal"], fontSize=8, leading=10,
        textColor=colors.white, fontName="Helvetica-Bold",
    )

    elems: list = [Paragraph(title, st_title)]
    meta = subtitle or f"Generado el {date.today().strftime('%d/%m/%Y')}"
    elems.append(Paragraph(meta, st_sub))

    cols = [str(c) for c in data.columns]
    header = [Paragraph(c, st_head) for c in cols]
    body = [
        [Paragraph("" if pd.isna(v) else str(v), st_cell) for v in row]
        for _, row in data.iterrows()
    ]
    table_data = [header] + body

    # Ancho repartido en partes iguales sobre el ancho útil de la página, para
    # que nunca se desborde (los Paragraph envuelven el texto largo).
    n_cols = max(len(cols), 1)
    col_w = doc.width / n_cols

    table = Table(table_data, colWidths=[col_w] * n_cols, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_ROJO)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor(_GRIS_BANDA)]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(_GRIS_LINEA)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elems.append(table)

    if truncado:
        elems.append(Spacer(1, 6 * mm))
        elems.append(Paragraph(
            f"Mostrando las primeras {format_int(_PDF_MAX_FILAS)} filas de "
            f"{format_int(n_total)}. Para el detalle completo, exportá en CSV.",
            st_sub,
        ))

    doc.build(elems)
    return buf.getvalue(), truncado


@st.cache_data(show_spinner=False, max_entries=40,
               hash_funcs={pd.DataFrame: df_fingerprint})
def _pdf_bytes_cached(
    df: pd.DataFrame, title: str, subtitle: str | None, include_index: bool
) -> tuple[bytes, bool]:
    return _build_pdf(df, title, subtitle, include_index)


# ============================================================================
# COMPONENTE DE UI
# ============================================================================
def render_export_buttons(
    df: pd.DataFrame,
    *,
    filename: str,
    title: str,
    key: str,
    subtitle: str | None = None,
    csv_df: pd.DataFrame | None = None,
    include_index: bool = False,
) -> None:
    """
    Selector de formato (CSV / PDF) + botón de descarga, con diseño unificado.

    Args:
        df: tabla a exportar (lo que se muestra). Se usa para el PDF y, salvo
            que se pase `csv_df`, también para el CSV.
        filename: nombre base del archivo (sin extensión).
        title: título que encabeza el PDF.
        key: clave única (evita choques entre tablas en la misma página).
        subtitle: línea de contexto bajo el título del PDF (opcional).
        csv_df: tabla a usar SOLO para el CSV (p. ej. el detalle completo, sin
            truncar ni formatear). Si es None, se usa `df`.
        include_index: incluir el índice como primera columna (tablas cuyo
            índice tiene información, p. ej. el nombre de la prestación).
    """
    if df is None or len(df) == 0:
        return

    c1, c2 = st.columns([1, 2])
    with c1:
        fmt = st.radio(
            "Formato de exportación", ["CSV", "PDF"],
            horizontal=True, key=f"exp_fmt_{key}", label_visibility="collapsed",
        )
    with c2:
        if fmt == "CSV":
            data = _csv_bytes_cached(
                csv_df if csv_df is not None else df, include_index
            )
            st.download_button(
                "⬇  Descargar CSV", data, f"{filename}.csv", "text/csv",
                key=f"exp_dl_{key}", use_container_width=True,
            )
        else:
            data, _ = _pdf_bytes_cached(df, title, subtitle, include_index)
            st.download_button(
                "⬇  Descargar PDF", data, f"{filename}.pdf", "application/pdf",
                key=f"exp_dl_{key}", use_container_width=True,
            )
