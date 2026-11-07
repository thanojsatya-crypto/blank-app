"""Streamlit UI for a separate local/session-only OS-CSPRNG key mode."""
from __future__ import annotations

import streamlit as st

from os_csprng_key import KEY_BITS, KEY_BYTES, generate_os_csprng_key

OS_CSPRNG_MODE_LABEL = "OS CSPRNG (256-bit local key)"
OS_CSPRNG_KEY_STATE = "os_csprng_key_result"
OS_CSPRNG_ERROR_STATE = "os_csprng_key_error"


def render_os_csprng_key_mode() -> None:
    """Render one explicit generation flow; no network or persistence is used."""
    st.title("OS CSPRNG key generator")
    st.warning("OS CSPRNG/DRBG pseudorandom output — not true randomness, not a QRNG, live QKD, or physical entropy source.")
    st.warning(
        "⚠️ **Notice:** You are currently in the local OS CSPRNG mode, which only generates an offline 64-hex key. "
        "This mode has **no message typing box** and does **not** pair with the Communication website."
    )
    from aos_key_demo_ui import AOS_KEY_MODE_LABEL

    def _switch_mode_to_aos() -> None:
        st.session_state["_pending_key_generator_mode"] = AOS_KEY_MODE_LABEL

    if st.button(
        "👉 Switch to ESP32 Key & Message Provisioning Mode",
        type="primary",
        key="switch_to_aos_btn",
        on_click=_switch_mode_to_aos,
    ):
        st.session_state["_pending_key_generator_mode"] = AOS_KEY_MODE_LABEL
        st.rerun()
    st.info(
        "This mode is local/session-only: it makes no API or ESP request, writes no key to a file, "
        "and has no AOS provisioning path. The value remains in this Streamlit session's memory."
    )
    st.caption(
        "The key is displayed below as hexadecimal, so anyone who can view this session can read it. "
        "Keep the app on a trusted local computer; this teaching mode is not secure key provisioning."
    )

    if OS_CSPRNG_KEY_STATE not in st.session_state:
        st.session_state[OS_CSPRNG_KEY_STATE] = None
    if OS_CSPRNG_ERROR_STATE not in st.session_state:
        st.session_state[OS_CSPRNG_ERROR_STATE] = None

    generate_clicked = st.button(
        "Generate 256-bit OS-CSPRNG key",
        type="primary",
        key="generate_os_csprng_key",
    )
    clear_clicked = st.button("Clear OS-CSPRNG key", key="clear_os_csprng_key")

    if clear_clicked:
        st.session_state[OS_CSPRNG_KEY_STATE] = None
        st.session_state[OS_CSPRNG_ERROR_STATE] = None
    elif generate_clicked:
        # Drop any prior result before requesting fresh bytes; failures cannot
        # leave an earlier key available under the appearance of a new run.
        st.session_state[OS_CSPRNG_KEY_STATE] = None
        st.session_state[OS_CSPRNG_ERROR_STATE] = None
        try:
            st.session_state[OS_CSPRNG_KEY_STATE] = generate_os_csprng_key()
        except Exception:
            # Do not surface provider exception details in the UI.
            st.session_state[OS_CSPRNG_ERROR_STATE] = "Key generation failed; no key is available."

    error = st.session_state.get(OS_CSPRNG_ERROR_STATE)
    if error:
        st.error(error)
        return

    key = st.session_state.get(OS_CSPRNG_KEY_STATE)
    if key is None:
        st.subheader("Ready to generate")
        st.write("No key is created until you explicitly press the generate button.")
        return
    if not isinstance(key, bytes) or len(key) != KEY_BYTES:
        st.session_state[OS_CSPRNG_KEY_STATE] = None
        st.error("Invalid key state; the value was cleared.")
        return

    st.success("Generated one 256-bit OS-CSPRNG key.")
    st.metric("Key size", f"{KEY_BITS} bits / {KEY_BYTES} bytes")
    st.code(key.hex(), language="text")
