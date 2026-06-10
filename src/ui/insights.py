"""
Insights automáticos para los gráficos: una línea que dice QUÉ mirar.

Cada función es pura (recibe listas/arrays, devuelve un string en español o
None si no hay nada para decir) para poder testearlas sin Streamlit. La UI
las muestra como caption debajo del gráfico, y marca el punto señalado con
un anillo sutil sobre la serie.
"""

from __future__ import annotations

import numpy as np


def tendencia_pct_mensual(valores) -> float | None:
    """Pendiente de la recta de ajuste, relativa al promedio (%/mes)."""
    v = np.asarray(list(valores), dtype=float)
    if len(v) < 3:
        return None
    media = float(np.nanmean(v))
    if media == 0:
        return None
    pendiente = float(np.polyfit(np.arange(len(v)), v, 1)[0])
    return pendiente / abs(media) * 100


def insight_evolucion(etiquetas, valores, fmt=str) -> tuple[int, str] | None:
    """
    Para una serie mensual: dónde está el pico y cómo viene la tendencia.

    Returns:
        (indice_del_pico, texto) o None si no hay datos suficientes.
    """
    v = [float(x) for x in valores]
    if len(v) < 2:
        return None
    etiquetas = [str(e) for e in etiquetas]
    i_pico = int(np.argmax(v))

    partes = [f"El pico fue {etiquetas[i_pico]} ({fmt(v[i_pico])})"]
    t = tendencia_pct_mensual(v)
    if t is not None:
        if abs(t) >= 0.5:
            direccion = "creciente" if t > 0 else "decreciente"
            partes.append(f"tendencia {direccion} de ~{abs(t):.1f}% por mes")
        else:
            partes.append("sin tendencia clara")
    partes.append(f"promedio mensual {fmt(float(np.mean(v)))}")
    return i_pico, " · ".join(partes) + "."


def insight_concentracion(
    etiquetas, valores, top_n: int = 3, sufijo: str = "del total"
) -> str | None:
    """Cuánto concentran las primeras categorías (regla 80/20 visible)."""
    etiquetas = [str(e) for e in etiquetas]
    v = np.asarray(list(valores), dtype=float)
    total = float(np.nansum(v))
    if len(v) == 0 or total <= 0:
        return None
    orden = np.argsort(v)[::-1]
    n = min(top_n, len(v))
    share = float(np.nansum(v[orden[:n]])) / total * 100
    nombres = ", ".join(etiquetas[i] for i in orden[:n])
    return f"Las {n} primeras categorías ({nombres}) concentran el {share:.0f}% {sufijo}."


def insight_anomalias(meses, desvios_pct) -> str:
    """Resumen de los desvíos detectados (o tranquilidad si no hay)."""
    meses = [str(m) for m in meses]
    if not meses:
        return (
            "Sin desvíos relevantes en el período: el comportamiento se "
            "mantiene dentro de lo esperado."
        )
    texto = f"{len(meses)} mes(es) fuera de lo esperado"
    desvios = [d for d in desvios_pct if d is not None and not np.isnan(d)]
    if desvios:
        i_peor = int(np.argmax(np.abs(desvios)))
        texto += (
            f"; el desvío más fuerte fue {meses[i_peor]} "
            f"({desvios[i_peor]:+.0f}% contra su promedio móvil)"
        )
    return texto + ". Conviene revisar esos meses primero."


def insight_prediccion(reales, predichos) -> str | None:
    """Qué tan bien viene prediciendo el modelo y hacia dónde se desvía."""
    r = np.asarray(list(reales), dtype=float)
    p = np.asarray(list(predichos), dtype=float)
    mask = r > 0
    if not mask.any():
        return None
    errores = (p[mask] - r[mask]) / r[mask] * 100
    mae = float(np.mean(np.abs(errores)))
    sesgo = float(np.mean(errores))
    if sesgo > 1:
        tendencia = f"tiende a sobreestimar ({sesgo:+.1f}%)"
    elif sesgo < -1:
        tendencia = f"tiende a subestimar ({sesgo:+.1f}%)"
    else:
        tendencia = "está balanceado (sin sesgo claro)"
    return f"Error promedio del {mae:.1f}% mensual; el modelo {tendencia}."
