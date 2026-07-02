#!/usr/bin/env python3
"""
Generador de credenciales para .streamlit/secrets.toml.

Hashea passwords con bcrypt (cost 12) y genera un cookie_key aleatorio fuerte.
Nunca guarda nada en texto plano ni en disco: imprime un bloque listo para
pegar en secrets.toml (que es local y está gitignored).

Uso:
    python scripts/gen_credentials.py              # asistente interactivo
    python scripts/gen_credentials.py --cookie-key # solo un cookie_key nuevo
"""

from __future__ import annotations

import argparse
import getpass
import secrets

try:
    import bcrypt
except ImportError:
    raise SystemExit(
        "Falta bcrypt. Instalalo con: pip install bcrypt "
        "(viene con streamlit-authenticator)."
    )


def hash_password(password: str) -> str:
    """Devuelve el hash bcrypt (cost 12) de un password."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def gen_cookie_key() -> str:
    """cookie_key aleatorio de 32 bytes (64 hex)."""
    return secrets.token_hex(32)


def _interactive() -> int:
    print("Generador de credenciales para .streamlit/secrets.toml\n")
    username = input("username (login, sin espacios): ").strip()
    if not username:
        print("El username no puede estar vacío.")
        return 1
    name = input("Nombre completo: ").strip()
    email = input("Email (opcional): ").strip()
    # Sin prompt de "Rol": el campo se eliminó de la app (no autorizaba nada,
    # daba una falsa sensación de control de acceso — ver auth.get_current_user).

    pw = getpass.getpass("Password: ")
    pw2 = getpass.getpass("Repetir password: ")
    if not pw:
        print("El password no puede estar vacío.")
        return 1
    if pw != pw2:
        print("Las contraseñas no coinciden.")
        return 1

    hashed = hash_password(pw)

    print("\n" + "=" * 60)
    print("Pegá este bloque en .streamlit/secrets.toml:")
    print("=" * 60 + "\n")
    print(f"[credentials.usernames.{username}]")
    print(f'name = "{name}"')
    if email:
        print(f'email = "{email}"')
    print(f'password = "{hashed}"')
    print()
    print("# Si el archivo todavía no tiene cookie_key, agregá al inicio:")
    print(f'# cookie_key = "{gen_cookie_key()}"')
    print('# cookie_name = "simulador_cm_auth"')
    print("# cookie_expiry_days = 1")
    print()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera credenciales para secrets.toml")
    ap.add_argument(
        "--cookie-key",
        action="store_true",
        help="Solo imprime un cookie_key nuevo y sale",
    )
    args = ap.parse_args()

    if args.cookie_key:
        print(gen_cookie_key())
        return 0

    return _interactive()


if __name__ == "__main__":
    raise SystemExit(main())
