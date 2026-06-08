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

import streamlit as st
import streamlit_authenticator as stauth

from core.audit import log_event


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
        role = "admin"
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

    # El método login() muestra el formulario y actualiza session_state
    # con authentication_status, name, username.
    try:
        authenticator.login(location="main")
    except Exception as e:
        st.error(f"Error en login: {e}")
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
    elif status is False and prev is not False:
        log_event("login_failed", username=username, success=False)

    st.session_state["_audit_last_status"] = status


def get_current_user() -> dict:
    """
    Devuelve un dict con la info del usuario logueado.

    Returns:
        {
            "username": str,   # el "luciano"
            "name": str,       # el "Luciano Núñez"
            "role": str,       # "admin" o "user"
        }
    """
    username = st.session_state.get("username", "")
    name = st.session_state.get("name", "")

    # role no viene de session_state, lo sacamos de secrets directo
    role = "user"
    try:
        role = st.secrets["credentials"]["usernames"][username].get("role", "user")
    except (KeyError, AttributeError):
        pass

    return {
        "username": username,
        "name": name,
        "role": role,
    }


def render_logout() -> None:
    """Renderiza el botón de cerrar sesión. Llamar desde el sidebar."""
    authenticator = st.session_state.get("_authenticator")
    if authenticator is not None:
        authenticator.logout(button_name="Cerrar sesión", location="sidebar")
