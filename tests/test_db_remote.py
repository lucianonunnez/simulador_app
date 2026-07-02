"""
Tests del conector remoto (Supabase / PostgreSQL).

No requieren una base real: se testea `build_select` (puro) y que sin
configuración de Supabase la app NO active la fuente remota (cae a DuckDB).
"""

from __future__ import annotations

from core import db_remote


def test_build_select_sin_filtros():
    sql, params = db_remote.build_select("simulador", "consumo", "Mes")
    assert sql == 'SELECT * FROM "simulador"."consumo"'
    assert params == []


def test_build_select_filtra_por_prestador():
    sql, params = db_remote.build_select(
        "simulador", "consumo", "Mes", prestador_ids=(1130,)
    )
    assert 'WHERE "Prestador ID" IN (%s)' in sql
    assert params == [1130]


def test_build_select_filtra_por_prestador_y_meses():
    sql, params = db_remote.build_select(
        "simulador", "valores", "Mes Vigencia",
        prestador_ids=(1130, 1127), meses=("05-2026", "04-2026"),
    )
    assert '"Prestador ID" IN (%s,%s)' in sql
    assert '"Mes Vigencia" IN (%s,%s)' in sql
    assert sql.index('"Prestador ID"') < sql.index('"Mes Vigencia"')  # AND en orden
    assert params == [1130, 1127, "05-2026", "04-2026"]


def test_build_select_escapa_identificadores():
    """Defensa básica de quoting: comillas en el nombre no rompen la query."""
    sql, _ = db_remote.build_select('sch"x', 'tab"y', "Mes")
    assert '"sch""x"."tab""y"' in sql


def test_dsn_fuerza_sslmode_require():
    """TLS no negociable hacia Supabase: si el DSN no trae sslmode se agrega
    require; si el usuario ya definió uno (p. ej. verify-full), se respeta."""
    assert db_remote._forzar_sslmode(
        "postgresql://u:p@h:5432/db"
    ) == "postgresql://u:p@h:5432/db?sslmode=require"
    # DSN con query string previa: se agrega con '&', no con un segundo '?'.
    assert db_remote._forzar_sslmode(
        "postgresql://u:p@h:5432/db?connect_timeout=5"
    ) == "postgresql://u:p@h:5432/db?connect_timeout=5&sslmode=require"
    # Un sslmode explícito del usuario no se pisa.
    dsn = "postgresql://u:p@h:5432/db?sslmode=verify-full"
    assert db_remote._forzar_sslmode(dsn) == dsn

    # Camino real por variable de entorno (deploy headless).
    import os

    prev = os.environ.get("SUPABASE_DATABASE_URL")
    try:
        os.environ["SUPABASE_DATABASE_URL"] = "postgresql://u:p@h:5432/db"
        cfg = db_remote._read_secrets()
        assert cfg["database_url"].endswith("?sslmode=require")
    finally:
        if prev is None:
            os.environ.pop("SUPABASE_DATABASE_URL", None)
        else:
            os.environ["SUPABASE_DATABASE_URL"] = prev


def test_remote_no_configurado_sin_secrets():
    """Sin secrets ni env var, remote_configured() es False -> la app usa DuckDB
    y el camino existente queda intacto."""
    import os

    prev = os.environ.pop("SUPABASE_DATABASE_URL", None)
    try:
        assert db_remote.remote_configured() is False
    finally:
        if prev is not None:
            os.environ["SUPABASE_DATABASE_URL"] = prev
