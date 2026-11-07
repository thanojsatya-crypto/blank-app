"""
Quantum Gate Display & Circuit Logic Studio
Extracted from qg_display_app.py with live CSS animations and ESP32 hardware integration.
"""
from __future__ import annotations

import time
import requests
import json
import numpy as np
import streamlit as st

QG_STUDIO_CSS = """
<style>
    /* Live Qubit Orb Stage Animation */
    .qubit-stage {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: linear-gradient(135deg, #f0fdfa 0%, #e0f2fe 50%, #eff6ff 100%);
        border: 1px solid #ccfbf1;
        border-radius: 20px;
        padding: 24px 30px;
        margin-bottom: 22px;
        box-shadow: inset 0 2px 8px rgba(255, 255, 255, 0.9), 0 8px 24px -6px rgba(13, 148, 136, 0.12);
        position: relative;
        overflow: hidden;
    }

    .qubit-orb-container {
        position: relative;
        width: 100px;
        height: 100px;
        display: grid;
        place-items: center;
    }

    .qubit-ring {
        position: absolute;
        width: 90px;
        height: 38px;
        border: 2px solid #0d9488;
        border-radius: 50%;
        transform: rotate(-30deg);
        animation: spin-slow 8s linear infinite;
        opacity: 0.7;
    }

    .qubit-ring-2 {
        position: absolute;
        width: 85px;
        height: 34px;
        border: 2px solid #3b82f6;
        border-radius: 50%;
        transform: rotate(40deg);
        animation: spin-slow 11s linear infinite reverse;
        opacity: 0.6;
    }

    .qubit-core {
        width: 58px;
        height: 58px;
        border-radius: 50%;
        background: linear-gradient(135deg, #14b8a6 0%, #0284c7 100%);
        display: grid;
        place-items: center;
        color: #ffffff;
        font-size: 26px;
        font-weight: 800;
        box-shadow: 0 0 24px rgba(20, 184, 166, 0.5);
        z-index: 2;
        animation: float-orb 3.5s ease-in-out infinite alternate;
    }

    @keyframes spin-slow {
        100% { transform: rotate(330deg); }
    }

    @keyframes float-orb {
        0% { transform: translateY(-3px) scale(0.98); }
        100% { transform: translateY(4px) scale(1.02); }
    }

    /* Badges */
    .badge-live-light {
        background: #ecfdf5;
        color: #059669;
        border: 1px solid #a7f3d0;
        border-radius: 20px;
        padding: 5px 14px;
        font-weight: 700;
        font-size: 13px;
        display: inline-flex;
        align-items: center;
        gap: 7px;
    }

    .badge-live-light::before {
        content: "";
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #10b981;
        box-shadow: 0 0 8px #10b981;
        animation: pulse-dot 1.8s infinite;
    }

    @keyframes pulse-dot {
        0%, 100% { opacity: 0.4; transform: scale(0.9); }
        50% { opacity: 1; transform: scale(1.15); }
    }

    .badge-demo-light {
        background: #fff7ed;
        color: #c2410c;
        border: 1px solid #fed7aa;
        border-radius: 20px;
        padding: 5px 14px;
        font-weight: 700;
        font-size: 13px;
    }

    /* Metric Grid Tiles */
    .metric-grid-tile {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 16px 14px;
        text-align: center;
        box-shadow: 0 2px 8px rgba(0,0,0,0.02);
    }

    .tile-title {
        font-size: 11px;
        font-weight: 700;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 5px;
    }

    .tile-value {
        font-size: 22px;
        font-weight: 800;
        color: #0f172a;
    }

    /* Interactive Circuit Visualizer Bar */
    .circuit-strip {
        background: #f1f5f9;
        border: 2px dashed #cbd5e1;
        border-radius: 14px;
        padding: 16px 20px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 16px;
        font-weight: 600;
        color: #0f766e;
        display: flex;
        align-items: center;
        gap: 10px;
        overflow-x: auto;
        min-height: 56px;
        margin: 12px 0 18px;
    }

    .gate-token {
        background: #ffffff;
        border: 1px solid #99f6e4;
        color: #0f766e;
        border-radius: 8px;
        padding: 6px 12px;
        box-shadow: 0 2px 6px rgba(13, 148, 136, 0.1);
        display: inline-flex;
        align-items: center;
        gap: 4px;
    }

    .protocol-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-left: 4px solid #0d9488;
        border-radius: 10px;
        padding: 14px 18px;
        margin: 10px 0;
        font-size: 13px;
        line-height: 1.6;
        color: #334158;
    }
</style>
"""

def fetch_telemetry(base_url: str):
    import time
    now = time.time()
    cache = st.session_state.get("_telemetry_cache")
    if cache and (now - cache.get("ts", 0)) < 2.0 and cache.get("data") is not None:
        return cache["data"], cache["err"]

    url = base_url.rstrip("/") + "/api/telemetry"
    try:
        resp = requests.get(url, timeout=(0.4, 0.9))
        if resp.status_code == 200:
            data = resp.json()
            st.session_state["_telemetry_cache"] = {"ts": now, "data": data, "err": None}
            return data, None
        err = f"HTTP {resp.status_code}"
    except Exception as e:
        err = str(e)

    if cache and cache.get("data") is not None:
        return cache["data"], None
    st.session_state["_telemetry_cache"] = {"ts": now, "data": None, "err": err}
    return None, err


def post_control_chain(base_url: str, chain: list):
    url = base_url.rstrip("/") + "/api/control"
    try:
        payload = {"action": "set_chain", "chain": chain}
        resp = requests.post(url, json=payload, timeout=2.5)
        if resp.status_code == 200:
            return resp.json(), None
        return None, f"HTTP {resp.status_code}: {resp.text}"
    except Exception as e:
        return None, str(e)


def render_qg_display_studio(esp_endpoint: str = "http://192.168.1.12"):
    """Renders the complete QG Display & Gate Logic Studio with animations."""
    st.markdown(QG_STUDIO_CSS, unsafe_allow_html=True)

    # State initialization
    if "qg_mode" not in st.session_state:
        st.session_state["qg_mode"] = "Live"
    if "qg_esp_ip" not in st.session_state:
        st.session_state["qg_esp_ip"] = esp_endpoint
    if "gate_chain" not in st.session_state:
        st.session_state["gate_chain"] = ["I"]
    if "circuit_width" not in st.session_state:
        st.session_state["circuit_width"] = "1 qubit"
    if "target_qubit" not in st.session_state:
        st.session_state["target_qubit"] = 0
    if "auto_poll" not in st.session_state:
        st.session_state["auto_poll"] = True

    # Top Header Banner
    h1, h2 = st.columns([3, 1])
    with h1:
        st.markdown("## **QG Display & Gate Logic Studio**")
        st.caption("Quantum Circuit Simulator & Live ESP32 Hardware Integration with Dynamic Micro-Animations")
    with h2:
        if st.session_state["qg_mode"] == "Live":
            st.markdown('<div style="text-align: right; padding-top: 8px;"><span class="badge-live-light">CONNECTED · LIVE ESP32</span></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div style="text-align: right; padding-top: 8px;"><span class="badge-demo-light">SYNTHETIC DEMO</span></div>', unsafe_allow_html=True)

    # Control Bar
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 1, 1])
    with ctrl_col1:
        st.session_state["qg_esp_ip"] = st.text_input(
            "ESP32 Hardware Target / URL API",
            value=st.session_state.get("qg_esp_ip", esp_endpoint),
            help="URL API, node token (3F4G3DS84ZLA0sE5ePHtJ0Ejjws_6Cwn2XALF5v4Y41n6wzNK), or local IP 192.168.1.12",
            key="qg_studio_ip_input"
        ).strip()
    with ctrl_col2:
        st.session_state["qg_mode"] = st.radio(
            "Operation Mode",
            ["Live", "Demo"],
            index=0 if st.session_state["qg_mode"] == "Live" else 1,
            horizontal=True,
            key="qg_studio_mode_radio"
        )
    with ctrl_col3:
        st.session_state["auto_poll"] = st.toggle(
            "Live Hardware Polling",
            value=st.session_state["auto_poll"],
            help="Smooth background query so physical GPIO pin pushes update immediately.",
            key="qg_studio_poll_toggle"
        )

    # Main Layout
    left_pane, right_pane = st.columns([1, 1], gap="large")

    with left_pane:
        poll_rate = 3 if (st.session_state.get("qg_mode") == "Live" and st.session_state.get("auto_poll", True)) else None

        @st.fragment(run_every=poll_rate)
        def render_live_telemetry_stage():
            telemetry = None
            err = None
            target_url = st.session_state.get("qg_esp_ip", esp_endpoint)
            if target_url in ("3F4G3DS84ZLA0sE5ePHtJ0Ejjws_6Cwn2XALF5v4Y41n6wzNK", "esp32", "master"):
                target_url = "http://192.168.1.12"
            if not target_url.startswith(("http://", "https://")):
                target_url = "http://" + target_url

            if st.session_state["qg_mode"] == "Live":
                telemetry, err = fetch_telemetry(target_url)
            else:
                telemetry = {
                    "device": "qg-esp32 (Demo)",
                    "uptime_ms": 348200,
                    "boot_id": "demo-boot-session-id",
                    "provision_id": "demo-provision-session-id",
                    "state": 0,
                    "message_index": 1,
                    "display_mode": "qubit",
                    "reseed_count": 0,
                }
            st.session_state["latest_telemetry"] = telemetry

            # High-level Animated Qubit Display Card
            phys_state = telemetry.get("state", 0) if telemetry else 0
            state_symbol = f"|{phys_state}⟩"

            st.markdown(f"""
            <div class="qubit-stage">
                <div>
                    <div style="font-size: 11px; font-weight: 800; color: #0f766e; text-transform: uppercase; letter-spacing: 0.12em;">
                        Hardware Registered State
                    </div>
                    <div style="font-size: 26px; font-weight: 800; color: #0f172a; margin-top: 2px;">
                        Physical Display Value
                    </div>
                    <div style="font-size: 13px; color: #64748b; margin-top: 4px;">
                        Triggered via ESP32 GPIO Pins 18, 19, or 27
                    </div>
                </div>
                <div class="qubit-orb-container">
                    <div class="qubit-ring"></div>
                    <div class="qubit-ring-2"></div>
                    <div class="qubit-core">{state_symbol}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Live Quantum State Animation Video Player (|0> and |1>)
            if "selected_video_state" not in st.session_state:
                st.session_state["selected_video_state"] = None
            if "video_autoplay" not in st.session_state:
                st.session_state["video_autoplay"] = True
            if "video_quality_mode" not in st.session_state:
                st.session_state["video_quality_mode"] = "Auto (1080p/720p Adaptive)"
            if "video_size_choice" not in st.session_state:
                st.session_state["video_size_choice"] = "2X Widescreen (480px)"

            video_state = st.session_state["selected_video_state"]
            if video_state is None:
                video_state = 0 if phys_state == 0 else 1

            # Determine player height (default is 2X length = 480px with 2X expanded width)
            chosen_size = st.session_state.get("video_size_choice", "2X Widescreen (480px)")
            if "720px" in chosen_size or "3X" in chosen_size:
                player_height = 720
            elif "360px" in chosen_size:
                player_height = 360
            else:
                player_height = 480  # 2X length

            # Base Google Drive Preview Video URLs
            base_drive_url = (
                "https://drive.google.com/file/d/1c-d15l3kZ-_TGunswprq95ictFkym1Ev/preview"
                if video_state == 0
                else "https://drive.google.com/file/d/1YlYULtRtG2tY8xt9V7-_E4o5KE9h9Uvo/preview"
            )

            # Auto play handling
            is_autoplay = st.session_state.get("video_autoplay", True)
            video_url = f"{base_drive_url}?autoplay=1" if is_autoplay else base_drive_url

            # Auto Quality adjust handling
            quality_mode = st.session_state.get("video_quality_mode", "Auto (1080p/720p Adaptive)")
            if "1080p" in quality_mode and "Auto" not in quality_mode:
                quality_badge = "💎 1080p FHD"
                filter_style = "image-rendering: -webkit-optimize-contrast;"
            elif "720p" in quality_mode and "Auto" not in quality_mode:
                quality_badge = "⚡ 720p HD"
                filter_style = ""
            elif "480p" in quality_mode:
                quality_badge = "💾 480p SD"
                filter_style = "filter: contrast(102%);"
            else:
                quality_badge = "🌟 AUTO (ADAPTIVE HD)"
                filter_style = ""

            st.markdown(f"""
            <div style="border: 1px solid #0d9488; border-radius: 16px; overflow: hidden; background: #0f172a; margin: 14px 0 16px; box-shadow: 0 8px 30px rgba(0, 0, 0, 0.15); width: 100%;">
                <div style="background: linear-gradient(135deg, #0f766e 0%, #0369a1 100%); padding: 10px 18px; display: flex; align-items: center; justify-content: space-between;">
                    <div style="font-weight: 800; color: #ffffff; font-size: 14px; display: flex; align-items: center; gap: 10px;">
                        <span>🎬 Quantum State Video Theater (2X Display)</span>
                        <span style="background: rgba(255, 255, 255, 0.2); color: #ffffff; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700;">
                            {quality_badge}
                        </span>
                        <span style="background: rgba(255, 255, 255, 0.2); color: #ffffff; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700;">
                            {'⚡ AUTOPLAY: ON' if is_autoplay else '⏸️ AUTOPLAY: OFF'}
                        </span>
                    </div>
                    <span style="background: #ffffff; color: #0f766e; padding: 3px 12px; border-radius: 999px; font-size: 13px; font-weight: 900;">
                        STATE: |{video_state}⟩
                    </span>
                </div>
                <iframe src="{video_url}" style="width: 100%; height: {player_height}px; min-height: {player_height}px; border: 0; display: block; {filter_style}" allow="autoplay; fullscreen; picture-in-picture; encrypted-media" allowfullscreen></iframe>
            </div>
            """, unsafe_allow_html=True)

            # Interactive State Switchers & Controls
            v_col1, v_col2, v_col3 = st.columns([1, 1, 1.2])
            with v_col1:
                if st.button("▶️ |0⟩ Video (Auto-Play)", use_container_width=True, key="btn_vid_0"):
                    st.session_state["selected_video_state"] = 0
                    st.session_state["video_autoplay"] = True
                    st.rerun()
            with v_col2:
                if st.button("▶️ |1⟩ Video (Auto-Play)", use_container_width=True, key="btn_vid_1"):
                    st.session_state["selected_video_state"] = 1
                    st.session_state["video_autoplay"] = True
                    st.rerun()
            with v_col3:
                if st.button("🔄 Follow ESP State", use_container_width=True, key="btn_vid_auto"):
                    st.session_state["selected_video_state"] = None
                    st.rerun()

            # Auto Quality & Display Size Controls
            q_col1, q_col2 = st.columns([1.2, 1])
            with q_col1:
                new_quality = st.selectbox(
                    "Auto Quality Adjust Option",
                    [
                        "Auto (1080p/720p Adaptive)",
                        "Ultra HD (1080p)",
                        "Standard HD (720p)",
                        "Data Saver (480p)",
                    ],
                    index=0,
                    key="quality_selector_box",
                    help="Auto-selects optimal stream resolution based on available bandwidth."
                )
                if new_quality != st.session_state.get("video_quality_mode"):
                    st.session_state["video_quality_mode"] = new_quality
                    st.rerun()
            with q_col2:
                new_size = st.selectbox(
                    "Display Size Scaling",
                    [
                        "2X Widescreen (480px)",
                        "3X Cinema Display (720px)",
                        "Standard (360px)",
                    ],
                    index=0,
                    key="size_selector_box",
                    help="2X length (480px) with 2X expanded width."
                )
                if new_size != st.session_state.get("video_size_choice"):
                    st.session_state["video_size_choice"] = new_size
                    st.rerun()

            # Telemetry Diagnostic Matrix (4 Tiles)
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.markdown(f"""
                <div class="metric-grid-tile">
                    <div class="tile-title">Slot (PB3)</div>
                    <div class="tile-value">#{telemetry.get('message_index', 1) if telemetry else '-'}</div>
                </div>
                """, unsafe_allow_html=True)
            with m2:
                st.markdown(f"""
                <div class="metric-grid-tile">
                    <div class="tile-title">Mode (PB5)</div>
                    <div class="tile-value">{str(telemetry.get('display_mode', 'qubit') if telemetry else '-').upper()}</div>
                </div>
                """, unsafe_allow_html=True)
            with m3:
                st.markdown(f"""
                <div class="metric-grid-tile">
                    <div class="tile-title">PB4 Triggers</div>
                    <div class="tile-value">{telemetry.get('reseed_count', 0) if telemetry else '-'}</div>
                </div>
                """, unsafe_allow_html=True)
            with m4:
                uptime_val = (telemetry.get('uptime_ms', 0) / 1000.0) if telemetry else 0
                st.markdown(f"""
                <div class="metric-grid-tile">
                    <div class="tile-title">Uptime</div>
                    <div class="tile-value">{uptime_val:.0f}s</div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)

            # Real-Time Dynamic Waveform Plot
            st.markdown("#### **Real-Time Quantum Phase Waveform**")
            t_samples = np.linspace(0, 4 * np.pi, 160)
            if phys_state == 0:
                wave_data = np.sin(t_samples)
            else:
                wave_data = np.sin(2 * t_samples) * np.cos(t_samples)

            st.line_chart(wave_data, height=190)

            # Live Simulation probabilities from Telemetry if present
            if telemetry and "simulation" in telemetry and telemetry["simulation"]:
                sim = telemetry["simulation"]
                st.markdown("#### **Live ESP32 Quantum State Simulation**")
                final_probs = sim.get("final_state", {}).get("probabilities", [])
                if final_probs:
                    prob_dict = {f"|{item.get('basis')}⟩": item.get("value", 0.0) for item in final_probs}
                    st.bar_chart(prob_dict, height=160)

            # Detailed Telemetry Inspector
            with st.expander("🔍 Complete ESP32 Telemetry Inspector", expanded=False):
                if telemetry:
                    st.json(telemetry)
                elif err:
                    st.error(f"Cannot reach ESP32 at {target_url}: {err}")

            with st.expander("📌 Hardware 6-Key & Dual-LED Pinout Reference", expanded=False):
                st.dataframe(
                    [
                        {"Control": "Key 1 (PB1)", "Pin": "GPIO 18", "Function": "H Gate -> State |0⟩", "LED Response": "Light 2 turns OFF (Ground State |0⟩)"},
                        {"Control": "Key 2 (PB2)", "Pin": "GPIO 19", "Function": "X Gate -> State |1⟩", "LED Response": "Light 2 turns ON (Excited State |1⟩)"},
                        {"Control": "Key 3 (PB3)", "Pin": "GPIO 21", "Function": "Cycle Slot 1..5", "LED Response": "Light 2 pulses N times (1..5), returns to state"},
                        {"Control": "Key 4 (PB4)", "Pin": "GPIO 22", "Function": "Hardware TRNG Q-Key Gen", "LED Response": "Light 2 pulses 3 times to confirm fresh 128-bit key"},
                        {"Control": "Key 5 (PB5)", "Pin": "GPIO 25", "Function": "Display Mode (Qubit/Cipher)", "LED Response": "Light 2 does 1 short pulse (160ms)"},
                        {"Control": "Key 6 (PB6)", "Pin": "GPIO 27", "Function": "Reset to Identity & State |0⟩", "LED Response": "Light 2 does 2 flashes, then stays OFF (|0⟩)"},
                        {"Control": "Light 1 (Onboard)", "Pin": "GPIO 2", "Function": "Wi-Fi & Web Communication Only", "LED Response": "Steady ON when Wi-Fi connected; micro-dips on API / Password verify"},
                        {"Control": "Light 2 (External)", "Pin": "GPIO 4", "Function": "Quantum Bit State Only", "LED Response": "|0⟩ = OFF, |1⟩ = ON; pulses briefly during key actions"},
                    ],
                    hide_index=True,
                    use_container_width=True
                )
                st.caption("All 6 physical keys are active-low (connect button between GPIO and GND). Light 2 (External LED) connects to GPIO 4 with a 220Ω resistor to GND.")

        render_live_telemetry_stage()

    with right_pane:
        st.markdown("### **Quantum Circuit Gate Builder**")
        st.caption("Design arbitrary quantum gate chains and dispatch to ESP32 for state-vector evaluation.")

        # Circuit Configuration Selection
        w1, w2 = st.columns([1, 1])
        with w1:
            st.session_state["circuit_width"] = st.selectbox(
                "Circuit Register Size",
                ["1 Qubit (Ground |0⟩)", "2 Qubits (Ground |00⟩)"],
                index=0 if "1" in st.session_state.get("circuit_width", "1") else 1,
                key="circuit_width_select"
            )
        with w2:
            if "2" in st.session_state["circuit_width"]:
                st.session_state["target_qubit"] = st.selectbox(
                    "Target Qubit Index", [0, 1], format_func=lambda x: f"q{x} (Qubit {x})",
                    key="target_qubit_select"
                )

        # Gate Palette
        st.markdown("**Single-Qubit Gate Palette:**")
        gate_palette = ["I", "H", "X", "Y", "Z", "S", "T"]
        p_cols = st.columns(7)
        for idx, gate_name in enumerate(gate_palette):
            if p_cols[idx].button(gate_name, key=f"btn_palette_{gate_name}", use_container_width=True):
                if "1" in st.session_state["circuit_width"]:
                    st.session_state["gate_chain"].append(gate_name)
                else:
                    st.session_state["gate_chain"].append({"gate": gate_name, "target": st.session_state["target_qubit"]})
                st.rerun()

        # Controlled Gates for 2-Qubit Mode
        if "2" in st.session_state["circuit_width"]:
            if st.button("➕ Insert CNOT Gate (Control: q0 ➔ Target: q1)", use_container_width=True, key="btn_cnot"):
                st.session_state["gate_chain"].append({"gate": "CNOT", "control": 0, "target": 1})
                st.rerun()

        # Visual Circuit Sequence Strip
        strip_tokens = []
        for elem in st.session_state["gate_chain"]:
            if isinstance(elem, str):
                strip_tokens.append(f'<span class="gate-token">{elem}</span>')
            elif isinstance(elem, dict):
                if elem.get("gate") == "CNOT":
                    strip_tokens.append(f'<span class="gate-token">CNOT(q{elem.get("control")}→q{elem.get("target")})</span>')
                else:
                    strip_tokens.append(f'<span class="gate-token">{elem.get("gate")}(q{elem.get("target")})</span>')
        
        strip_html = "".join(strip_tokens) if strip_tokens else '<span style="color:#94a3b8; font-style:italic;">(Circuit empty · Click gates above to build sequence)</span>'
        st.markdown(f'<div class="circuit-strip">{strip_html}</div>', unsafe_allow_html=True)

        # Action Toolbar
        act1, act2 = st.columns([1, 2])
        with act1:
            if st.button("🗑️ Reset Circuit", use_container_width=True, key="btn_reset_circ"):
                st.session_state["gate_chain"] = ["I"] if "1" in st.session_state["circuit_width"] else []
                st.rerun()
        with act2:
            if st.button("⚡ Dispatch Circuit to ESP32", type="primary", use_container_width=True, key="btn_dispatch_circ"):
                target_url = st.session_state.get("qg_esp_ip", esp_endpoint)
                if target_url in ("3F4G3DS84ZLA0sE5ePHtJ0Ejjws_6Cwn2XALF5v4Y41n6wzNK", "esp32", "master"):
                    target_url = "http://192.168.1.12"
                if not target_url.startswith(("http://", "https://")):
                    target_url = "http://" + target_url

                if st.session_state["qg_mode"] == "Live":
                    with st.spinner("Dispatching circuit to ESP32 API..."):
                        calc_res, post_err = post_control_chain(target_url, st.session_state["gate_chain"])
                        if post_err:
                            st.error(f"ESP32 Execution Failed: {post_err}")
                        else:
                            st.success("✅ State-vector calculated by ESP32!")
                            st.session_state["last_sim"] = calc_res
                            st.rerun()
                else:
                    st.info("Demo mode: Circuit evaluated synthetically.")

        # Quantum State-Vector Probability Spectrum
        sim_obj = None
        telemetry = st.session_state.get("latest_telemetry")
        if telemetry and "simulation" in telemetry:
            sim_obj = telemetry["simulation"]
        elif "last_sim" in st.session_state and st.session_state["last_sim"] and "simulation" in st.session_state["last_sim"]:
            sim_obj = st.session_state["last_sim"]["simulation"]

        if sim_obj:
            st.markdown("#### **Measured Probability Spectrum |ψ⟩**")
            final_probs = sim_obj.get("final_state", {}).get("probabilities", [])
            if final_probs:
                prob_dict = {f"|{item.get('basis')}⟩": item.get("value", 0.0) for item in final_probs}
                st.bar_chart(prob_dict, height=180)
