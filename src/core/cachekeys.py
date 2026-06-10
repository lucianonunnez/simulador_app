"""
Huellas baratas de DataFrames para las claves de caché de Streamlit.

st.cache_data hashea TODOS los argumentos en cada llamada para armar la clave.
Con DataFrames de cientos de miles de filas, ese hasheo cuesta cientos de ms
por función cacheada y por rerun — multiplicado por todas las funciones
cacheadas de la página, los reruns tardaban varios segundos con volumen real
(los elementos "fantasma" de la página anterior quedaban visibles mientras
tanto).

df_fingerprint reemplaza el hasheo del contenido completo por una huella
O(columnas) + una suma vectorizada: (filas, columnas, suma de las columnas
numéricas). Dos DataFrames distintos del dominio (otro prestador, otro mes,
otro filtro) difieren prácticamente siempre en esa huella; la colisión
requeriría mismas filas, mismas columnas y misma suma exacta de todos los
importes/cantidades.

Uso:
    @st.cache_data(hash_funcs={pd.DataFrame: df_fingerprint})
"""

from __future__ import annotations

import pandas as pd


def df_fingerprint(df: pd.DataFrame) -> tuple:
    """Huella barata y estable de un DataFrame para claves de caché."""
    if df is None or len(df) == 0:
        return (0, tuple(map(str, getattr(df, "columns", ()))), 0.0)

    numericas = df.select_dtypes(include="number")
    total = float(numericas.sum().sum()) if len(numericas.columns) else 0.0
    return (len(df), tuple(map(str, df.columns)), total)
