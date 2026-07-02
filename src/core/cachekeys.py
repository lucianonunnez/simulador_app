"""
Huellas baratas de DataFrames para las claves de caché de Streamlit.

st.cache_data hashea TODOS los argumentos en cada llamada para armar la clave.
Con DataFrames de cientos de miles de filas, ese hasheo cuesta cientos de ms
por función cacheada y por rerun — multiplicado por todas las funciones
cacheadas de la página, los reruns tardaban varios segundos con volumen real
(los elementos "fantasma" de la página anterior quedaban visibles mientras
tanto).

df_fingerprint reemplaza el hasheo profundo de Streamlit por
(filas, columnas, hash vectorizado del contenido). El hash usa
pd.util.hash_pandas_object (C vectorizado): ~107 ms medidos para 500k filas
x 8 columnas — un orden de magnitud más barato que el hasheo de Streamlit y,
a diferencia de la huella anterior (suma de columnas numéricas), detecta
cambios SOLO de texto (p.ej. un tarifario corregido donde únicamente cambió
el Nomenclador o el flag Pauta/No pauta). Con la huella vieja esos cambios
colisionaban y la app servía resultados financieros viejos desde el caché.

Uso:
    @st.cache_data(hash_funcs={pd.DataFrame: df_fingerprint})
"""

from __future__ import annotations

import pandas as pd


def df_fingerprint(df: pd.DataFrame) -> tuple:
    """Huella barata y estable de un DataFrame para claves de caché."""
    if df is None or len(df) == 0:
        return (0, tuple(map(str, getattr(df, "columns", ()))), 0)

    try:
        # Hash por fila combinando todas las columnas (numéricas y de texto),
        # sumado (insensible al orden de filas, igual que la huella anterior).
        contenido = int(pd.util.hash_pandas_object(df, index=False).sum())
    except TypeError:
        # Columnas object con valores no hasheables (listas/dicts): degradar
        # a la huella numérica vieja antes que romper el rerun.
        numericas = df.select_dtypes(include="number")
        contenido = (
            float(numericas.sum().sum()) if len(numericas.columns) else 0.0
        )
    return (len(df), tuple(map(str, df.columns)), contenido)
