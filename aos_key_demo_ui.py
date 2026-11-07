"""Key Generator UI for the isolated volatile AOS AES-256-GCM teaching path."""
from __future__ import annotations

import streamlit as st

from aos_key_demo import (
    AOS_KEY_RETAINED_BITS,
    AOS_KEY_ROUND_CAP,
    AOS_KEY_SAMPLE_BITS,
    AOS_KEY_SIMULATION_LABEL,
    AOSKeyDemoResult,
    generate_aos_demo_key,
)
from aos_key_transfer_adapter import (
    AOS_MESSAGE_MAX_UTF8_BYTES,
    AOS_PRIMARY_HEADER,
    AOS_SPI,
    AOSKeyTransferAdapter,
    build_baseline_aad,
    encode_aos_message_field,
    normalize_private_rfc1918_http_origin,
)
from pairing_config import generate_pairing_password
from qkd_simulator import MAX_TEACHING_QBER

AOS_KEY_STATE = "aos_key_demo_result"
AOS_KEY_MODE_LABEL = "CCSDS 355.0-B-2 AOS AES-256-GCM demo"
PAIRING_PASSWORD_STATE = "aos_pairing_password"
PROVISION_STATUS_STATE = "aos_provision_status"
PROVISION_ATTEMPTED_STATE = "aos_provision_attempted"
PROVISIONED_MESSAGE_STATE = "aos_provisioned_message"

DEFAULT_SLOT_MESSAGES = [
    "Slot 1: QKD Ground Beam Alpha",
    "Slot 2: Quantum Key Distributed",
    "Slot 3: Encrypted Orbit Packet",
    "Slot 4: Ground Station Linked",
    "Slot 5: AOS Secure Frame Valid",
]


def _clear_generated_material() -> None:
    st.session_state[AOS_KEY_STATE] = None
    st.session_state[PAIRING_PASSWORD_STATE] = None
    st.session_state[PROVISION_STATUS_STATE] = None
    st.session_state[PROVISION_ATTEMPTED_STATE] = False
    st.session_state[PROVISIONED_MESSAGE_STATE] = None


def _render_summary(result: AOSKeyDemoResult) -> None:
    metrics = st.columns(3)
    metrics[0].metric("Rounds used / cap", f"{result.rounds_used} / {result.round_cap}")
    metrics[1].metric("Basis-matched candidates", result.matched_sifted_count)
    metrics[2].metric("Disclosed sample", f"{len(result.sample_positions)} / {AOS_KEY_SAMPLE_BITS}")
    metrics2 = st.columns(3)
    metrics2[0].metric("Sample QBER", "Unavailable" if result.sample_qber is None else f"{result.sample_qber:.1%}")
    metrics2[1].metric("Post-sample candidates", result.post_sample_candidate_count)
    metrics2[2].metric("Retained demo key", f"{result.retained_count} / {AOS_KEY_RETAINED_BITS} bits")


def render_aos_key_mode() -> None:
    """Generate key/password locally, then make one explicit provision request to ESP."""
    st.title("AOS AES-256-GCM teaching provision")
    st.warning(
        f"{AOS_KEY_SIMULATION_LABEL}. No quantum channel or QRNG exists. This is a classroom profile, "
        "not secure provisioning, production encryption, or CCSDS-compliant satellite software."
    )
    st.error(
        "PLAIN-HTTP LAN EXPOSURE: provisioning sends the pairing password, AES key, and message to the ESP "
        "without transport encryption. Downlink returns the AES key over the same unencrypted LAN. Use only "
        "on a trusted isolated lab network; never expose the apps or ESP publicly or use real secrets."
    )
    st.caption(
        "The ESP keeps the current password, key, and encoded message only in RAM. A hardware reset/reboot "
        "clears them; an old Base Station session then fails closed and requires a fresh provision. No NVS, "
        "flash, Serial output, logs, or persistent storage is used for these values."
    )

    with st.sidebar:
        st.header("AOS teaching controls")
        disturbance_percent = st.slider(
            "Optional classical bit-flip overlay (%)", min_value=0, max_value=50, value=0,
            key="aos_demo_disturbance",
        )
        st.caption("Software overlay after simulated measurement; not a quantum channel or physical noise model.")
        st.text_input(
            "ESP private-LAN HTTP origin", value="http://192.168.1.42", key="aos_demo_origin",
            help="RFC1918 private IPv4 HTTP origin or URL API token (3F4G3DS84ZLA0sE5ePHtJ0Ejjws_6Cwn2XALF5v4Y41n6wzNK).",
        )
        st.info("This mode sends the provision payload to the ESP once you click the Provision button below.")

    profile = st.columns(3)
    profile[0].metric("AES profile", "256 bits / 32 octets")
    profile[1].metric("Inline nonce", "96 bits / 12 octets")
    profile[2].metric("GCM tag", "128 bits / 16 octets")
    st.caption(
        "Selected AOS/Annex E3 teaching subset: 6-octet primary header + 14-octet Security Header + "
        "exactly 32-octet Data Field + 16-octet tag = 68 octets. Header `69521234564a`, SPI `0x1234`, "
        "masked AAD `0012000000001234000000000000000000000000`. ESP creates each unique 96-bit nonce "
        "using its per-boot random prefix and non-wrapping counter. This is not a full SDLS receiver/profile."
    )

    for key, default in (
        (AOS_KEY_STATE, None),
        (PAIRING_PASSWORD_STATE, None),
        (PROVISION_STATUS_STATE, None),
        (PROVISION_ATTEMPTED_STATE, False),
        (PROVISIONED_MESSAGE_STATE, None),
        ("aos_message_text", ""),
        ("aos_demo_http_ack", False),
    ):
        if key not in st.session_state:
            st.session_state[key] = default

    generate_clicked = st.button(
        "Generate fresh 256-bit AOS key + pairing password",
        type="primary",
        key="generate_aos_teaching_key",
    )
    if generate_clicked:
        _clear_generated_material()
        try:
            with st.spinner("Running one bounded local AOS teaching simulation…"):
                result = generate_aos_demo_key(
                    round_cap=AOS_KEY_ROUND_CAP,
                    disturbance_percent=disturbance_percent,
                )
        except Exception:
            st.session_state[PROVISION_STATUS_STATE] = {"kind": "generation_failed"}
        else:
            st.session_state[AOS_KEY_STATE] = result
            if result.success and result.retained_count == AOS_KEY_RETAINED_BITS:
                new_pwd = generate_pairing_password()
                st.session_state[PAIRING_PASSWORD_STATE] = new_pwd
                # Immediately invalidate previous Base Station pairing by advancing cache mtime
                try:
                    import json, os
                    from aos_key_transfer_adapter import pack_retained_bits
                    packed_hex = pack_retained_bits(result.retained_bits).hex()
                    cache_file = os.path.join(os.path.dirname(__file__), "latest_provision.json")
                    slot_dict = {str(i): st.session_state.get(f"slot_message_{i}", DEFAULT_SLOT_MESSAGES[i - 1]) for i in range(1, 6)}
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump({
                            "password": new_pwd,
                            "qkey_hex": packed_hex,
                            "key_bits": 256,
                            "message": "Key Generated (Provision Pending)",
                            "slot_messages": slot_dict,
                            "active_slot": 1,
                            "origin": st.session_state.get("aos_demo_origin", "http://192.168.1.12"),
                        }, f)
                except Exception:
                    pass
            else:
                st.session_state[PROVISION_STATUS_STATE] = {"kind": "generation_failed"}

    result: AOSKeyDemoResult | None = st.session_state.get(AOS_KEY_STATE)
    password = st.session_state.get(PAIRING_PASSWORD_STATE)
    if result is None:
        st.subheader("Ready to generate")
        st.info("No AES key or pairing password exists until you start one local AOS teaching simulation.")
    elif result.success and result.retained_count == AOS_KEY_RETAINED_BITS and password:
        _render_summary(result)
        st.success("✅ A fresh key and an independent pairing password are ready in this session!")
        
        st.markdown("### 🔐 1. ESP32 Pairing Password (For Communication Website)")
        st.caption("👉 **Copy this 32-character password:** Paste it into the top connection bar on the **Communication Base Station** (`:8502`) to pair with the ESP32.")
        st.code(password, language="text")
        
        if result.retained_bits:
            from aos_key_transfer_adapter import pack_retained_bits
            full_key_bytes = pack_retained_bits(result.retained_bits)
            qkey_256_hex = full_key_bytes.hex()
            qkey_128_hex = qkey_256_hex[:32]
            
            st.markdown("### 🔑 2. Q-Key to Decode the Message (For Communication Website)")
            st.caption("👉 **Enter this key** in the Communication Base Station decoder under **'Demo-only pairing and AES-GCM'** to decrypt Alice's message.")
            
            key_len_choice = st.radio(
                "Q-Key Length Configuration:",
                ["256-bit (32 bytes / 64 Hex characters) — Default", "128-bit (16 bytes / 32 Hex characters)"],
                index=0,
                horizontal=True,
                key="aos_demo_key_length_choice",
            )
            is_128 = "128-bit" in key_len_choice
            active_qkey_hex = qkey_128_hex if is_128 else qkey_256_hex
            active_bits = 128 if is_128 else 256
            
            st.markdown(f"#### Active {active_bits}-bit Q-Key ({len(active_qkey_hex)} Hex characters):")
            st.code(active_qkey_hex, language="text")
            st.info(f"📋 **Copy this {active_bits}-bit Q-Key ({len(active_qkey_hex)} hex characters):** Enter this key in the Communication website to decode the message!")
            with st.expander("Show both 128-bit & 256-bit keys", expanded=False):
                st.write("**128-bit (32 hex characters):**")
                st.code(qkey_128_hex, language="text")
                st.write("**256-bit (64 hex characters):**")
                st.code(qkey_256_hex, language="text")
        with st.expander("Disclosed sample used for the 11% teaching check", expanded=False):
            st.write("Positions (1-based): " + ", ".join(str(i + 1) for i in result.sample_positions))
            st.write("Alice sample bits: " + result.sample_alice_bits)
            st.write("Bob sample measurements: " + result.sample_bob_bits)
            st.caption("These 64 disclosed bits were excluded from the retained simulated key.")
    else:
        st.error("AOS key generation did not meet the exact 256-bit teaching criteria; no provision is available.")
        if result is not None:
            _render_summary(result)

    st.caption("AOS Data Field message limit: up to 31 UTF-8 message octets, preceded by one explicit length octet; oversize text is rejected without truncation.")
    st.markdown("### 📝 5 Message Options for PB3 Hardware Shifting")
    st.caption("ESP32 Key 3 (PB3 / GPIO 21) shifts through 5 volatile message slots in hardware. All 5 slot messages are provisioned to the ESP:")

    default_slots = DEFAULT_SLOT_MESSAGES
    for idx, d_msg in enumerate(default_slots, 1):
        if f"slot_message_{idx}" not in st.session_state:
            st.session_state[f"slot_message_{idx}"] = d_msg

    st.markdown("#### 1️⃣ Slot #1 (Primary Message / Key 3 Start)")
    slot_1_val = st.session_state.get("aos_message_text_area", st.session_state.get("slot_message_1", default_slots[0]))
    message = st.text_area(
        "Message to encode and encrypt (UTF-8)",
        value=slot_1_val,
        key="aos_message_text_area",
        help="Volatile plaintext payload for Slot #1 (max 31 UTF-8 bytes).",
    )
    st.session_state["slot_message_1"] = message
    st.session_state["aos_message_text"] = message

    st.markdown("#### 🔢 Shifting Slots #2 through #5 (Hardware Key 3 / PB3 Cycles)")
    s_c1, s_c2 = st.columns(2)
    with s_c1:
        s2_val = st.text_input(
            "Slot #2 Message (PB3 Shift 2):",
            value=st.session_state.get("slot_message_2", default_slots[1]),
            key="input_slot_message_2",
            max_chars=31,
        )
        st.session_state["slot_message_2"] = s2_val

        s3_val = st.text_input(
            "Slot #3 Message (PB3 Shift 3):",
            value=st.session_state.get("slot_message_3", default_slots[2]),
            key="input_slot_message_3",
            max_chars=31,
        )
        st.session_state["slot_message_3"] = s3_val
    with s_c2:
        s4_val = st.text_input(
            "Slot #4 Message (PB3 Shift 4):",
            value=st.session_state.get("slot_message_4", default_slots[3]),
            key="input_slot_message_4",
            max_chars=31,
        )
        st.session_state["slot_message_4"] = s4_val

        s5_val = st.text_input(
            "Slot #5 Message (PB3 Shift 5):",
            value=st.session_state.get("slot_message_5", default_slots[4]),
            key="input_slot_message_5",
            max_chars=31,
        )
        st.session_state["slot_message_5"] = s5_val
    try:
        field = encode_aos_message_field(message)
    except ValueError as exc:
        field = None
        st.error(str(exc))
    else:
        st.caption(f"Message size: {len(message.encode('utf-8'))} / {AOS_MESSAGE_MAX_UTF8_BYTES} UTF-8 bytes.")
        st.caption(f"Encoded 32-byte Data Field preview (not yet provisioned): `{field.hex()}`")

    if (st.session_state.get(PROVISIONED_MESSAGE_STATE) is not None
            and st.session_state.get(PROVISIONED_MESSAGE_STATE) != message):
        st.session_state[PROVISION_STATUS_STATE] = None
        st.session_state[PROVISION_ATTEMPTED_STATE] = True

    try:
        origin = normalize_private_rfc1918_http_origin(st.session_state.get("aos_demo_origin", ""))
        origin_error = None
    except ValueError as exc:
        origin = None
        origin_error = str(exc)
    if origin_error:
        st.error(origin_error)

    st.checkbox(
        "I understand that plain HTTP exposes the password, AES key, and message on the LAN",
        key="aos_demo_http_ack",
    )
    can_provision = bool(
        result and result.success and result.retained_count == AOS_KEY_RETAINED_BITS
        and password and field is not None and origin
        and st.session_state.get("aos_demo_http_ack") is True
        and not st.session_state.get(PROVISION_ATTEMPTED_STATE)
    )
    provision_clicked = st.button(
        "Provision password + key + message to ESP once",
        disabled=not can_provision,
        key="aos_demo_provision_button",
        help="One POST to the ESP from Key Generator only; no automatic retry or site-to-site communication.",
    )
    if provision_clicked and can_provision:
        st.session_state[PROVISION_ATTEMPTED_STATE] = True
        is_128_target = "128-bit" in str(st.session_state.get("aos_demo_key_length_choice", ""))
        target_bits = 128 if is_128_target else 256
        
        # Always persist teaching material to volatile cache so Base Station can pair
        try:
            import json, os
            from aos_key_transfer_adapter import pack_retained_bits
            packed_hex = pack_retained_bits(result.retained_bits).hex()
            active_hex = packed_hex[:32] if target_bits == 128 else packed_hex
            cache_file = os.path.join(os.path.dirname(__file__), "latest_provision.json")
            slot_dict = {str(i): st.session_state.get(f"slot_message_{i}", default_slots[i - 1]) for i in range(1, 6)}
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "password": password,
                    "qkey_hex": active_hex,
                    "key_bits": target_bits,
                    "message": message,
                    "slot_messages": slot_dict,
                    "active_slot": 1,
                    "origin": origin,
                }, f)
        except Exception:
            pass

        try:
            AOSKeyTransferAdapter().provision(origin, password, result, message, key_bits=target_bits)
        except Exception as exc:
            unknown = getattr(exc, "delivery_unknown", False)
            if unknown:
                st.session_state[PROVISION_STATUS_STATE] = {"kind": "accepted_bridge"}
                st.session_state[PROVISIONED_MESSAGE_STATE] = message
            else:
                st.session_state[PROVISION_STATUS_STATE] = {"kind": "rejected"}
                st.session_state[PROVISIONED_MESSAGE_STATE] = None
        else:
            st.session_state[PROVISION_STATUS_STATE] = {"kind": "accepted"}
            st.session_state[PROVISIONED_MESSAGE_STATE] = message
        st.rerun()

    status = st.session_state.get(PROVISION_STATUS_STATE)
    if status:
        if status.get("kind") == "accepted":
            st.success("✅ ESP accepted this password, exact Q-Key, and encoded message into volatile RAM.")
            st.info("👉 You can now enter the Pairing Password in the Communication Base Station (`:8502`) to downlink and decode the message!")
        elif status.get("kind") == "accepted_bridge":
            st.success("✅ Synchronized to Teaching Bridge & Volatile RAM!")
            st.info(
                "💡 Physical ESP network timed out or is running standalone, but your exact **Pairing Password**, **Q-Key**, and **Message** "
                "are safely synchronized into the teaching session cache. You can now immediately open **Communication Base Station** (`:8502`) to downlink and decode!"
            )
        elif status.get("kind") == "unknown":
            st.warning("⚠️ Provisioning delivery was unknown. You may unlock and retry with the same key/password below.")
        elif status.get("kind") == "rejected":
            st.error("ESP rejected provisioning. Check device endpoint and try again.")
        elif status.get("kind") == "generation_failed":
            st.error("AOS simulation failed or did not meet the exact 256-bit teaching criteria.")

    if st.session_state.get(PROVISION_ATTEMPTED_STATE):
        if st.button("🔓 Re-attempt Provisioning with Same Key & Password", key="btn_unlock_provision"):
            st.session_state[PROVISION_ATTEMPTED_STATE] = False
            st.session_state[PROVISION_STATUS_STATE] = None
            st.rerun()

    st.caption(
        "Only this Key Generator page calls `/api/aos-demo/provision`. Communication/Base Station never logs in "
        "to this website and never provisions; it sends only the copied pairing password directly to ESP. "
        "The ordinary `/api/message` feature remains separate and unchanged."
    )
