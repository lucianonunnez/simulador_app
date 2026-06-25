"""
Módulo de autenticación.

Usa streamlit-authenticator con usuarios definidos en secrets.toml.
Los passwords están hasheados con bcrypt (no se guardan en texto plano).

Uso desde streamlit_app.py:
    require_login()         # si no está logueado, muestra form y corta
    user = get_current_user()  # devuelve dict con name, username, email
    render_logout()         # botón de cerrar sesión en sidebar

Gestión de usuarios:
    Editar .streamlit/secrets.toml (local, gitignored). Para generar el hash
    bcrypt de un password y un cookie_key: python scripts/gen_credentials.py
    Ver README.md y docs/DESPLIEGUE_SEGURO.md.
"""

import logging

import streamlit as st
import streamlit_authenticator as stauth

from core import ratelimit
from core.audit import log_event

logger = logging.getLogger(__name__)


def _clave_ratelimit() -> str:
    """Clave para el lockout: el último username intentado si se conoce
    (queda en session_state tras el primer intento), o un bucket global."""
    return st.session_state.get("username") or "global"


def _build_authenticator() -> stauth.Authenticate:
    """
    Construye el objeto Authenticate leyendo credenciales desde st.secrets.

    Estructura esperada en secrets.toml:

        cookie_key = "..."
        cookie_name = "simulador_cm_auth"
        cookie_expiry_days = 1

        [credentials.usernames.luciano]
        name = "Luciano Núñez"
        email = "luciano@ejemplo.com"
        password = "$2b$12$..."   # hash bcrypt
    """
    if "credentials" not in st.secrets:
        st.error(
            "Faltan credenciales configuradas. "
            "Pedile al administrador que complete `secrets.toml`."
        )
        st.stop()

    # streamlit-authenticator espera un dict con esta estructura específica
    credentials = {
        "usernames": {
            username: {
                "name": user_data["name"],
                "email": user_data.get("email", ""),
                "password": user_data["password"],
            }
            for username, user_data in st.secrets["credentials"]["usernames"].items()
        }
    }

    return stauth.Authenticate(
        credentials=credentials,
        cookie_name=st.secrets.get("cookie_name", "simulador_cm_auth"),
        cookie_key=st.secrets["cookie_key"],
        # Default corto (1 día) por seguridad; configurable en secrets.toml.
        cookie_expiry_days=st.secrets.get("cookie_expiry_days", 1),
    )


def require_login() -> None:
    """
    Si el usuario no está autenticado, muestra el form de login y
    detiene la ejecución (con st.stop()) hasta que se loguee bien.

    Llamar esto al principio de streamlit_app.py, antes de renderizar
    cualquier contenido.
    """
    authenticator = _build_authenticator()

    # Guardamos el authenticator en session_state para poder usar el logout
    st.session_state["_authenticator"] = authenticator

    # Encabezado de marca sobre el formulario (solo mientras no hay sesión).
    if st.session_state.get("authentication_status") is not True:
        from ui.styles import brand_header_login

        st.markdown(brand_header_login(), unsafe_allow_html=True)

    # Lockout anti fuerza bruta: si hubo demasiados intentos fallidos
    # recientes, frenar ANTES de procesar credenciales.
    restante = ratelimit.segundos_bloqueado(_clave_ratelimit())
    if restante > 0:
        st.error(
            f"Demasiados intentos fallidos. El acceso queda bloqueado "
            f"{restante // 60 + 1} minuto(s) más por seguridad."
        )
        st.stop()

    # El método login() muestra el formulario y actualiza session_state
    # con authentication_status, name, username.
    try:
        authenticator.login(location="main")
    except Exception:
        # El detalle va al log: el mensaje de excepción puede filtrar rutas
        # o configuración interna al usuario.
        logger.exception("Error inesperado en el formulario de login")
        st.error("No se pudo iniciar sesión. Reintentá; si persiste, contactá al administrador.")
        st.stop()

    status = st.session_state.get("authentication_status")
    _audit_login(status)

    if status is False:
        st.error("Usuario o contraseña incorrectos")
        st.stop()
    elif status is None:
        st.info("Ingresá tus credenciales para continuar")
        st.stop()
    # Si status es True, sigue la ejecución normal


def _audit_login(status) -> None:
    """
    Registra eventos de login sin spamear por los reruns de Streamlit:
    el éxito se loguea una vez por sesión y el fallo solo en la transición
    a "incorrecto".
    """
    username = st.session_state.get("username")
    prev = st.session_state.get("_audit_last_status", "init")

    if status is True:
        if not st.session_state.get("_audit_login_logged"):
            log_event("login_success", username=username, success=True)
            st.session_state["_audit_login_logged"] = True
            # Cachear el rol para que data_loader y otros lo lean rápido
            st.session_state["_user_role"] = get_current_role()
        ratelimit.reset(username or "global")
    elif status is False and prev is not False:
        log_event("login_failed", username=username, success=False)
        ratelimit.registrar_fallo(username or "global")

    st.session_state["_audit_last_status"] = status


def get_current_role() -> str:
    """
    Devuelve el rol del usuario logueado: 'admin', 'manager' o 'viewer'.

    Lee el campo `role` de secrets.toml para el usuario actual.
    Si el campo no existe, devuelve 'viewer' (el más restrictivo).

    Roles válidos:
      admin   — puede cargar datos + todos los módulos
      manager — todos los módulos, sin carga de datos
      viewer  — solo Módulo 1
    """
    username = st.session_state.get("username", "")
    if not username:
        return "viewer"
    try:
        user_conf = st.secrets["credentials"]["usernames"].get(username, {})
        return user_conf.get("role", "viewer")
    except Exception:
        return "viewer"


def get_current_user() -> dict:
    """
    Devuelve un dict con la info del usuario logueado.

    Returns:
        {
            "username": str,   # "luciano"
            "name": str,       # "Luciano Núñez"
            "role": str,       # "admin" | "manager" | "viewer"
        }
    """
    return {
        "username": st.session_state.get("username", ""),
        "name": st.session_state.get("name", ""),
        "role": get_current_role(),
    }


def render_logout() -> None:
    """Renderiza el botón de cerrar sesión. Llamar desde el sidebar."""
    authenticator = st.session_state.get("_authenticator")
    if authenticator is not None:
        authenticator.logout(button_name="Cerrar sesión", location="sidebar")
