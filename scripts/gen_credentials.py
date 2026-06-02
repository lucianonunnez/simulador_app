#!/usr/bin/env python3
"""
Generador de credenciales para `.streamlit/secrets.toml`.

Sirve para rotar la `cookie_key` y crear/actualizar usuarios con su contraseña
hasheada en bcrypt (nunca texto plano). No escribe el archivo: imprime el
bloque listo para copiar, para que el secreto no quede en logs ni en disco por
accidente.

Uso:

    # Generar solo una cookie_key nueva
    python scripts/gen_credentials.py --cookie-key

    # Generar el hash de un usuario (pide la contraseña sin mostrarla)
    python scripts/gen_credentials.py --user luciano --name "Luciano Núñez" \
        --email luciano@ejemplo.com --role admin

    # Bloque completo (cookie_key + un usuario)
    python scripts/gen_credentials.py --cookie-key \
        --user luciano --name "Luciano Núñez" --email luciano@ejemplo.com --role admin

Requisitos: pip install bcrypt
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys

try:
    import bcrypt
except ImportError:
    sys.exit("Falta 'bcrypt'. Instalalo con:  pip install bcrypt")


def new_cookie_key() -> str:
    """Clave aleatoria URL-safe de 256 bits para firmar la cookie de sesión."""
    return secrets.token_urlsafe(32)


def hash_password(plain: str) -> str:
    """Devuelve el hash bcrypt (cost 12) de una contraseña."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def main() -> None:
    ap = argparse.ArgumentParser(description="Genera credenciales para secrets.toml")
    ap.add_argument("--cookie-key", action="store_true", help="Generar una cookie_key nueva")
    ap.add_argument("--user", help="username (clave del usuario)")
    ap.add_argument("--name", help="Nombre visible del usuario")
    ap.add_argument("--email", default="", help="Email del usuario")
    ap.add_argument("--role", default="user", choices=["admin", "user"], help="Rol")
    args = ap.parse_args()

    if not args.cookie_key and not args.user:
        ap.print_help()
        sys.exit(0)

    print("\n# ── Pegar en .streamlit/secrets.toml ──")

    if args.cookie_key:
        print(f'cookie_key = "{new_cookie_key()}"')
        print('cookie_name = "simulador_cm_auth"')
        print("cookie_expiry_days = 7")

    if args.user:
        if not args.name:
            sys.exit("Falta --name para el usuario.")
        # La contraseña se pide de forma interactiva y no se muestra en pantalla.
        pwd = getpass.getpass(f"Contraseña para '{args.user}': ")
        pwd2 = getpass.getpass("Repetir contraseña: ")
        if pwd != pwd2:
            sys.exit("Las contraseñas no coinciden.")
        if len(pwd) < 8:
            sys.exit("Usá una contraseña de al menos 8 caracteres.")

        print(f"\n[credentials.usernames.{args.user}]")
        print(f'name = "{args.name}"')
        print(f'email = "{args.email}"')
        print(f'password = "{hash_password(pwd)}"')
        print(f'role = "{args.role}"')

    print()


if __name__ == "__main__":
    main()
