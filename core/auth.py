"""
Auth — InvestAI
Login session-based via Streamlit Secrets.
Le credenziali NON sono nel codice sorgente: vivono solo in st.secrets
(Streamlit Cloud → App Settings → Secrets).

Flusso:
 1. Se la sessione è già autenticata → passa subito all'app.
 2. Altrimenti mostra il form di login.
 3. Verifica username + hash SHA-256 della password contro st.secrets["auth"].
 4. In caso di successo setta st.session_state["authenticated"] = True.
 5. Dopo 5 tentativi falliti applica un cooldown di 30 secondi.
"""
from __future__ import annotations

import hashlib
import time
import logging

import streamlit as st

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS  = 5
_COOLDOWN_SECS = 30


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _secrets_ok() -> bool:
    """Verifica che le secrets necessarie esistano."""
    try:
        _ = st.secrets["auth"]["username"]
        _ = st.secrets["auth"]["password_hash"]
        return True
    except (KeyError, FileNotFoundError):
        return False


def _init_state() -> None:
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False
    if "_login_attempts" not in st.session_state:
        st.session_state["_login_attempts"] = 0
    if "_login_locked_until" not in st.session_state:
        st.session_state["_login_locked_until"] = 0.0


def is_authenticated() -> bool:
    _init_state()
    return bool(st.session_state.get("authenticated", False))


def logout() -> None:
    st.session_state["authenticated"] = False
    st.session_state["_login_attempts"] = 0
    st.rerun()


def render_login_page() -> None:
    """
    Mostra la pagina di login.
    Ritorna senza fare nulla se l'utente è già autenticato.
    Se il login ha successo, setta authenticated=True e chiama st.rerun().
    """
    _init_state()

    # Se le secrets non sono configurate, mostra istruzioni di setup
    if not _secrets_ok():
        st.error(
            "⚙️ **Secrets non configurate.**\n\n"
            "Vai su **Streamlit Cloud → App Settings → Secrets** e incolla il contenuto "
            "di `.streamlit/secrets.toml.example`."
        )
        st.stop()
        return

    # Layout centrato
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        st.markdown("""
        <div style="text-align:center; padding: 40px 0 20px;">
            <div style="font-size: 3.5rem;">💎</div>
            <h1 style="margin: 8px 0 4px; color: #004d40; font-size: 2rem;">InvestAI</h1>
            <p style="color: #888; font-size: 0.9rem; margin: 0;">Assistente Finanziario Personale</p>
        </div>
        """, unsafe_allow_html=True)

        # Cooldown attivo?
        locked_until = st.session_state["_login_locked_until"]
        remaining = locked_until - time.time()
        if remaining > 0:
            st.warning(f"⏳ Troppi tentativi. Riprova tra **{int(remaining)+1} secondi**.")
            time.sleep(1)
            st.rerun()
            return

        with st.container(border=True):
            st.markdown("### 🔐 Accedi")

            username_input = st.text_input(
                "Username",
                placeholder="nicola",
                key="login_username",
                autocomplete="username",
            )
            password_input = st.text_input(
                "Password",
                type="password",
                placeholder="••••••••",
                key="login_password",
                autocomplete="current-password",
            )

            login_btn = st.button(
                "Accedi",
                type="primary",
                use_container_width=True,
                key="login_btn",
            )

            if login_btn:
                expected_user = st.secrets["auth"]["username"]
                expected_hash = st.secrets["auth"]["password_hash"]

                if (
                    username_input == expected_user
                    and _hash(password_input) == expected_hash
                ):
                    # ✅ Login OK
                    st.session_state["authenticated"] = True
                    st.session_state["_login_attempts"] = 0
                    st.session_state["_login_locked_until"] = 0.0
                    logger.info(f"[auth] Login riuscito per '{username_input}'")
                    st.rerun()
                else:
                    # ❌ Credenziali errate
                    st.session_state["_login_attempts"] += 1
                    attempts = st.session_state["_login_attempts"]
                    logger.warning(f"[auth] Tentativo fallito #{attempts} per '{username_input}'")

                    if attempts >= _MAX_ATTEMPTS:
                        st.session_state["_login_locked_until"] = time.time() + _COOLDOWN_SECS
                        st.session_state["_login_attempts"] = 0
                        st.error(f"🔒 Troppi tentativi. Attendi {_COOLDOWN_SECS} secondi.")
                    else:
                        remaining_attempts = _MAX_ATTEMPTS - attempts
                        st.error(
                            f"❌ Username o password errati. "
                            f"({remaining_attempts} {'tentativo' if remaining_attempts == 1 else 'tentativi'} rimanenti)"
                        )

        st.markdown("""
        <div style="text-align:center; font-size:0.72rem; color:#bbb; margin-top:24px;">
            ⚠️ Solo uso personale — non costituisce consulenza finanziaria
        </div>
        """, unsafe_allow_html=True)
