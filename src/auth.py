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
from core.audit import _client_ip, log_event

logger = logging.getLogger(__name__)


def _clave_usuario(username: str | None) -> str:
    """Bucket de lockout por username INTENTADO ("global" si no se conoce)."""
    return f"user:{username}" if username else "global"


def _segundos_bloqueado(username: str | None) -> int:
    """
    Segundos de bloqueo vigentes para el intento actual (0 = libre).

    Chequea dos buckets, con el MISMO criterio con el que se registran los
    fallos (username intentado + IP de origen):
      - por username: MAX_INTENTOS fallos/ventana. Frena la fuerza bruta
        contra una cuenta puntual.
      - por IP: umbral más alto (MAX_INTENTOS_IP) para frenar ataques
        distribuidos entre usernames, sin que 5 fallos ajenos alcancen para
        bloquearle la cuenta (DoS) a un usuario legítimo. Detrás de un proxy
        sin X-Forwarded-For la IP puede ser "unknown": todas esas sesiones
        comparten bucket, por eso el umbral más holgado.
    """
    return max(
        ratelimit.segundos_bloqueado(_clave_usuario(username)),
        ratelimit.segundos_bloqueado(
            f"ip:{_client_ip()}", max_intentos=ratelimit.MAX_INTENTOS_IP
        ),
    )


def _instalar_lockout(authenticator: stauth.Authenticate) -> None:
    """
    Envuelve check_credentials para aplicar el lockout REAL.

    streamlit-authenticator no expone el username intentado cuando el login
    falla (solo lo guarda en session_state si es correcto), así que antes la
    clave del lockout salía de la sesión ANTERIOR: bastaba abrir una sesión
    nueva por intento para evadirlo. Acá se intercepta el chequeo de
    credenciales, el único punto donde el username intentado SÍ se conoce:
      - si el username o la IP están bloqueados, se rechaza ANTES de validar
        la contraseña (aunque sea correcta: no entra ni se emite cookie);
      - cada submit fallido REAL (no los reruns) registra el fallo en ambos
        buckets (username intentado + IP), siempre con el mismo criterio.
    """
    handler = authenticator.authentication_handler
    original = handler.check_credentials

    def check_con_lockout(username: str, password: str, *args, **kwargs):
        restante = _segundos_bloqueado(username)
        if restante > 0:
            log_event("login_blocked", username=username, success=False)
            st.session_state["_lockout_restante"] = restante
            st.session_state["authentication_status"] = False
            return False
        ok = original(username, password, *args, **kwargs)
        if not ok:
            ratelimit.registrar_fallo(_clave_usuario(username))
            ratelimit.registrar_fallo(f"ip:{_client_ip()}")
        return ok

    handler.check_credentials = check_con_lockout


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
    # Acceder a st.secrets cuando NO existe .streamlit/secrets.toml lanza
    # FileNotFoundError Y ADEMÁS Streamlit pinta su propio banner rojo crudo
    # (st.error interno), aun si atrapamos la excepción — caso típico de un
    # checkout limpio / Codespace nuevo. load_if_toml_exists() chequea la
    # existencia SIN imprimir ese banner y sin levantar excepción.
    try:
        tiene_archivo = st.secrets.load_if_toml_exists()
    except Exception:
        # Streamlit viejo sin el método, o secrets.toml malformado: degradar
        # al chequeo directo (que sí puede pintar el banner, pero es un caso
        # de borde y el mensaje accionable de abajo igual se muestra).
        tiene_archivo = False

    if not tiene_archivo or "credentials" not in st.secrets:
        st.error("🔒 Falta configurar las credenciales de acceso.")
        st.info(
            "No se encontró `.streamlit/secrets.toml`. Para crearlo:\n\n"
            "1. Copiá la plantilla: "
            "`cp .streamlit/secrets.toml.example .streamlit/secrets.toml`\n"
            "2. Generá el `cookie_key` y el hash del password: "
            "`python scripts/gen_credentials.py`\n"
            "3. Pegá los valores en `secrets.toml` y recargá la página.\n\n"
            "En un despliegue (Hugging Face Spaces, servidor), cargá esos "
            "mismos valores como *secrets* del entorno."
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
    _instalar_lockout(authenticator)

    # Guardamos el authenticator en session_state para poder usar el logout
    st.session_state["_authenticator"] = authenticator

    # Encabezado de marca sobre el formulario (solo mientras no hay sesión).
    if st.session_state.get("authentication_status") is not True:
        from ui.styles import brand_header_login

        st.markdown(brand_header_login(), unsafe_allow_html=True)

    # Aviso previo al formulario (best-effort: acá todavía no se conoce el
    # username de ESTE intento). El chequeo real, con el username intentado,
    # ocurre dentro de check_credentials (ver _instalar_lockout).
    restante = _segundos_bloqueado(st.session_state.get("username"))
    if restante > 0:
        st.error(
            f"Demasiados intentos fallidos. El acceso queda bloqueado "
            f"{restante // 60 + 1} minuto(s) más por seguridad."
        )
        st.stop()

    # El método login() muestra el formulario y actualiza session_state
    # con authentication_status, name, username.
    try:
        authenticator.login(
            location="main",
            fields={
                "Form name": "Ingreso",
                "Username": "Usuario",
                "Password": "Contraseña",
                "Login": "Ingresar",
            },
        )
    except Exception:
        # El detalle va al log: el mensaje de excepción puede filtrar rutas
        # o configuración interna al usuario.
        logger.exception("Error inesperado en el formulario de login")
        st.error("No se pudo iniciar sesión. Reintentá; si persiste, contactá al administrador.")
        st.stop()

    status = st.session_state.get("authentication_status")
    _audit_login(status)

    if status is False:
        # Si el intento se rechazó por lockout, decirlo (y no "contraseña
        # incorrecta", que invita a seguir probando).
        restante = st.session_state.pop("_lockout_restante", 0)
        if restante > 0:
            st.error(
                f"Demasiados intentos fallidos. El acceso queda bloqueado "
                f"{restante // 60 + 1} minuto(s) más por seguridad."
            )
        else:
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
        # Login OK: se limpia solo el bucket del username. El de IP se
        # conserva a propósito: entrar con una cuenta propia no debe "lavar"
        # el contador de un ataque distribuido desde esa misma IP.
        ratelimit.reset(_clave_usuario(username))
    elif status is False and prev is not False:
        # El registro del fallo en los buckets de lockout ocurre en
        # check_credentials (una vez por submit real, no por rerun); acá solo
        # se audita la transición para no spamear el log.
        log_event("login_failed", username=username, success=False)

    st.session_state["_audit_last_status"] = status


def get_current_user() -> dict:
    """
    Devuelve un dict con la info del usuario logueado.

    Returns:
        {
            "username": str,   # el "luciano"
            "name": str,       # el "Luciano Núñez"
        }

    Nota: el campo "role" se eliminó a propósito. Ningún módulo autorizaba
    nada con él, así que daba una falsa sensación de control de acceso
    (hallazgo de la auditoría de seguridad). Si en el futuro hay acciones
    que requieran privilegios, reintroducirlo junto con el gate real.
    """
    return {
        "username": st.session_state.get("username", ""),
        "name": st.session_state.get("name", ""),
    }


def render_logout() -> None:
    """Renderiza el botón de cerrar sesión. Llamar desde el sidebar."""
    authenticator = st.session_state.get("_authenticator")
    if authenticator is not None:
        authenticator.logout(button_name="Cerrar sesión", location="sidebar")
