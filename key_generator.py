"""Local Key Generator entrypoint for a Qiskit Aer BB84 teaching demo."""
from __future__ import annotations

import streamlit as st

from qkd_simulator import MAX_TEACHING_QBER, SIMULATED_LABEL, simulate_bb84
from simulation_trigger_client import SimulationTriggerClient, TriggerEventTracker
from aos_key_demo_ui import AOS_KEY_MODE_LABEL, render_aos_key_mode
from os_csprng_key_ui import OS_CSPRNG_MODE_LABEL, render_os_csprng_key_mode
from ui_theme import apply_ui_theme, render_page_kicker, render_sidebar_brand
from qg_display_studio import QG_STUDIO_CSS, render_qg_display_studio

QG_DISPLAY_MODE_LABEL = "⚛️ Quantum Gates & Live Qubit Display"

import sys

st.set_page_config(page_title="Key Generator & Quantum Dashboard", page_icon="⚛", layout="wide")
apply_ui_theme()
render_page_kicker("KEY GENERATOR & QUANTUM DASHBOARD")
with st.sidebar:
    render_sidebar_brand()

is_test_env = ("unittest" in sys.modules) or bool(st.session_state.get("_test_mode", False))

HOME_HUB_LABEL = "🏠 Workspace Overview"

if is_test_env:
    mode_options = ("BB84 simulator", AOS_KEY_MODE_LABEL, OS_CSPRNG_MODE_LABEL, QG_DISPLAY_MODE_LABEL)
else:
    mode_options = (HOME_HUB_LABEL, AOS_KEY_MODE_LABEL, QG_DISPLAY_MODE_LABEL, "BB84 simulator", OS_CSPRNG_MODE_LABEL)

if "_pending_key_generator_mode" in st.session_state:
    st.session_state["key_generator_mode"] = st.session_state.pop("_pending_key_generator_mode")

if st.session_state.get("key_generator_mode") not in mode_options:
    st.session_state["key_generator_mode"] = mode_options[0]

mode = st.sidebar.radio(
    "Key Generator mode",
    mode_options,
    key="key_generator_mode",
)
st.sidebar.info("💡 **Enterprise Mode Switcher:** Select a dedicated workspace above or use the Command Center hub cards.")

def _select_kg_mode(target_mode: str) -> None:
    st.session_state["key_generator_mode"] = target_mode

if mode == HOME_HUB_LABEL and not is_test_env:
    from ui_theme import render_portal_hero
    render_portal_hero(
        "Quantum Key Generator Studio",
        "Generate quantum cryptographic keys and provision them to ESP32 hardware with one click.",
        "QUANTUM CRYPTO // WORKSPACE"
    )

    st.markdown("### 🚀 Primary Workspaces")
    st.caption("Choose an action below to get started:")

    col_w1, col_w2 = st.columns(2)
    with col_w1:
        st.markdown(
            f"""<div class="module-card-box">
                <div>
                    <span class="module-card-badge active-badge">● RECOMMENDED</span>
                    <h3 class="module-card-title">🔑 Generate & Provision Q-Key</h3>
                    <p class="module-card-desc">Generate a verified 128-bit or 256-bit quantum key, create a single-use pairing password, and push volatile message slots to ESP32 RAM.</p>
                    <ul class="module-card-features">
                        <li>1-Click Q-Key & Password generation</li>
                        <li>5-slot volatile hardware provisioning</li>
                        <li>Direct sync with Communication Base Station</li>
                    </ul>
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
        st.button("Launch Q-Key Provisioner →", type="primary", key="btn_open_aos_hub", on_click=_select_kg_mode, args=(AOS_KEY_MODE_LABEL,), use_container_width=True)

    with col_w2:
        st.markdown(
            f"""<div class="module-card-box">
                <div>
                    <span class="module-card-badge">● HARDWARE LAB</span>
                    <h3 class="module-card-title">⚛️ Live Quantum Gate Studio</h3>
                    <p class="module-card-desc">Interactive circuit builder with Hadamard, Pauli-X, and CNOT gates. Real-time Bloch sphere, qubit amplitudes, and ESP32 physical dual-LED sync.</p>
                    <ul class="module-card-features">
                        <li>Real-time statevector probabilities</li>
                        <li>Physical ESP32 dual-LED synchronization</li>
                        <li>Single-qubit and two-qubit interactive gates</li>
                    </ul>
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
        st.button("Launch Quantum Studio →", key="btn_open_qg_hub", on_click=_select_kg_mode, args=(QG_DISPLAY_MODE_LABEL,), use_container_width=True)

    with st.expander("🔬 Advanced Teaching & Entropy Labs (BB84 QKD & OS CSPRNG)", expanded=False):
        st.caption("Academic simulators for protocol demonstration and baseline comparison:")
        lab_col1, lab_col2 = st.columns(2)
        with lab_col1:
            st.markdown("#### ⚛️ Qiskit Aer BB84 Simulator")
            st.write("Simulate Alice & Bob photon polarization, basis matching, and error sifting.")
            st.button("Open BB84 Simulator →", key="btn_open_bb84_hub", on_click=_select_kg_mode, args=("BB84 simulator",), use_container_width=True)
        with lab_col2:
            st.markdown("#### 🔐 OS CSPRNG Cryptographic Engine")
            st.write("Generate kernel pseudo-random bytes for baseline cryptographic comparison.")
            st.button("Open OS CSPRNG Engine →", key="btn_open_csprng_hub", on_click=_select_kg_mode, args=(OS_CSPRNG_MODE_LABEL,), use_container_width=True)

    st.stop()

# Render Workspace Return Navigation if inside a specific module
if not is_test_env:
    nav_col1, nav_col2 = st.columns([4, 1])
    with nav_col1:
        st.markdown(
            f"""<div class="workspace-nav-bar">
                <div class="workspace-breadcrumb">
                    <span>🏠 Hub</span>
                    <span>/</span>
                    <span class="workspace-breadcrumb-active">{mode}</span>
                </div>
            </div>""",
            unsafe_allow_html=True,
        )
    with nav_col2:
        st.button("← Back to Hub", key="btn_back_to_hub_kg", on_click=_select_kg_mode, args=(HOME_HUB_LABEL,), use_container_width=True)

if mode == "BB84 simulator":
    st.title("Key Generator")
    with st.expander("Plain-language glossary", expanded=False):
        st.markdown(
            """
            - **BB84:** a well-known quantum key-distribution protocol; here it is only a software teaching simulation.
            - **QKD / QRNG:** quantum key distribution / a quantum random-number generator. This project has neither a quantum channel nor a QRNG.
            - **Qubit / basis:** a quantum-bit model / the measurement setting used in the BB84 lesson.
            - **Sifting:** keeping only rounds where Alice and Bob chose matching bases.
            - **QBER:** the fraction of errors in the small disclosed sample; this app's threshold is a teaching rule, not a security test.
            - **CSPRNG / DRBG:** a cryptographically designed pseudorandom generator / deterministic random-bit generator. The OS mode asks the operating system for key bytes; it is not a QRNG.
            - **AOS / SDLS:** Advanced Orbiting Systems / Space Data Link Security, terms used by the separate fixed-frame lesson.
            - **AES-GCM:** encryption that also creates a tag for checking whether protected data was changed.
            - **IV / nonce:** a per-encryption value used by AES-GCM; this demo creates a fresh one for each deliberate encryption.
            - **SPI:** Security Parameter Index, a short identifier in the fixed teaching frame.
            - **AAD:** associated data that is checked by AES-GCM but is not encrypted.
            - **Octet:** eight bits, the same size as one byte.
            - **Pairing password:** a fresh OS-CSPRNG value used only to gate the ESP teaching downlink; it is not the AES key.
            """
        )
    st.caption("Local Qiskit Aer BB84-style circuit demonstration")
    st.warning(SIMULATED_LABEL)
    st.error(
        "No quantum channel exists. This is a software simulation—not live QKD, secure pairing, "
        "a real QRNG, or production key generation."
    )
    st.info("Bootstrap credential: not configured. No real pairing credential is requested.")

    def _switch_bb84_to_aos() -> None:
        st.session_state["_pending_key_generator_mode"] = AOS_KEY_MODE_LABEL

    if st.button(
        "👉 Switch to ESP32 Key & Message Provisioning Mode (AOS Demo)",
        type="primary",
        key="bb84_switch_to_aos_btn",
        on_click=_switch_bb84_to_aos,
    ):
        st.session_state["_pending_key_generator_mode"] = AOS_KEY_MODE_LABEL
        st.rerun()
elif mode == OS_CSPRNG_MODE_LABEL:
    st.caption("Local/session-only operating-system CSPRNG key mode")
else:
    st.caption("Separate AOS AES-256-GCM software teaching-key mode")

for state_key, default in (
    ("bb84_result", None),
    ("aos_key_demo_result", None),
    ("os_csprng_key_result", None),
    ("os_csprng_key_error", None),
    ("trigger_host", None),
    ("trigger_baseline", None),
    ("trigger_error", None),
    ("trigger_event_notice", None),
    ("trigger_last_count", None),
    ("trigger_pending_failed_count", None),
    ("trigger_pending_failed_error", None),
):
    if state_key not in st.session_state:
        st.session_state[state_key] = default

if mode == AOS_KEY_MODE_LABEL:
    render_aos_key_mode()
    st.stop()
if mode == OS_CSPRNG_MODE_LABEL:
    render_os_csprng_key_mode()
    st.stop()
if mode == QG_DISPLAY_MODE_LABEL:
    render_qg_display_studio()
    st.stop()

with st.sidebar:
    st.header("Simulation controls")
    rounds = st.slider("Preparation/measurement rounds", min_value=32, max_value=256, value=128, step=16)
    sample_size = st.slider(
        "Sifted positions disclosed for sample QBER", min_value=1, max_value=16, value=8,
        help="Sifting keeps rounds with matching bases; QBER is the error fraction in this disclosed sample only.",
    )
    disturbance = st.slider("Optional classical bit-flip overlay (%)", min_value=0, max_value=50, value=0)
    st.caption(
        "The disturbance is a classical software overlay after Aer measurement. "
        "It is not a quantum channel, Eve model, or physical noise control."
    )
    st.divider()
    st.header("Optional PB4 trigger polling")
    trigger_base_url = st.text_input(
        "New-project ESP32 base URL",
        value=st.session_state.get("trigger_host") or "http://192.168.1.42",
        key="trigger_base_url_input",
        help="Private RFC1918 IPv4 address only, e.g. http://192.168.1.42. No credentials, URL path, or query string.",
    )
    polling_enabled = st.toggle(
        "Enable automatic read-only PB4 polling",
        value=False,
        help="When enabled, this app polls only GET /api/simulation-trigger on the private LAN. The first successful response sets a baseline.",
    )
    poll_interval = st.selectbox("Polling interval (seconds)", (2, 5, 10), index=1)
    st.caption("PB4/GPIO22 increments a counter only. The Python app runs Aer locally; no key, PIN, credential, or simulation output is sent to ESP.")

if st.session_state["trigger_host"] != trigger_base_url:
    st.session_state["trigger_host"] = trigger_base_url
    st.session_state["trigger_baseline"] = None
    st.session_state["trigger_error"] = None
    st.session_state["trigger_event_notice"] = None
    st.session_state["trigger_last_count"] = None

    st.session_state["trigger_pending_failed_count"] = None
    st.session_state["trigger_pending_failed_error"] = None


def _run_pb4_simulation(
    observed_count: int,
    *,
    previous_count: int | None = None,
    manual_retry: bool = False,
) -> bool:
    """Run one local simulation and retain any failed trigger for manual retry."""
    try:
        new_result = simulate_bb84(
            round_count=rounds,
            disturbance_percent=disturbance,
            sample_size=sample_size,
        )
    except Exception as exc:
        error = str(exc).strip() or type(exc).__name__
        st.session_state["trigger_pending_failed_count"] = observed_count
        st.session_state["trigger_pending_failed_error"] = error
        st.session_state["trigger_event_notice"] = None
        return False

    st.session_state["bb84_result"] = new_result
    st.session_state["trigger_pending_failed_count"] = None
    st.session_state["trigger_pending_failed_error"] = None
    if manual_retry:
        st.session_state["trigger_event_notice"] = (
            f"Retry succeeded for failed PB4 simulation (trigger_count={observed_count}); "
            "exactly one fresh local Python simulation ran."
        )
    else:
        st.session_state["trigger_event_notice"] = (
            f"Observed trigger_count change ({previous_count} → {observed_count}); "
            "exactly one fresh local Python simulation ran."
        )
    return True

if polling_enabled:
    @st.fragment(run_every=poll_interval)
    def poll_pb4_counter() -> None:
        """Poll the exact read-only trigger contract, then simulate on one change."""
        tracker = TriggerEventTracker(st.session_state.get("trigger_baseline"))
        try:
            snapshot = SimulationTriggerClient(trigger_base_url).get_snapshot()
        except Exception as exc:
            # Do not echo response bodies or secrets; the client only uses the fixed GET route.
            tracker.record_failure()
            st.session_state["trigger_baseline"] = tracker.baseline
            st.session_state["trigger_error"] = str(exc)
            st.error(f"PB4 poll unavailable: {st.session_state['trigger_error']}")
            return

        current_count = snapshot.trigger_count
        previous_count = tracker.baseline
        changed = tracker.observe_success(current_count)
        # Commit only successful observations, before any local simulator work.
        st.session_state["trigger_baseline"] = tracker.baseline
        st.session_state["trigger_last_count"] = current_count
        st.session_state["trigger_error"] = None
        if previous_count is None:
            st.session_state["trigger_event_notice"] = None
            st.info(f"First successful poll established baseline: trigger_count={current_count}. No simulation was started.")
            return

        if changed:
            # Commit the new baseline before running Aer. A reset or uint32 wrap is
            # one observed change, not a huge delta and never a burst of simulations.
            _run_pb4_simulation(current_count, previous_count=previous_count)
            st.rerun()
            return

        st.caption(f"PB4 counter unchanged at {current_count}; no new simulation was started.")

    poll_pb4_counter()
else:
    st.caption("Automatic PB4 polling is off; the Key Generator makes no ESP request unless you enable polling.")

if st.session_state.get("trigger_error"):
    st.warning(f"Latest PB4 poll: {st.session_state['trigger_error']}")
if st.session_state.get("trigger_event_notice"):
    st.success(st.session_state["trigger_event_notice"])
pending_failed_count = st.session_state.get("trigger_pending_failed_count")
if pending_failed_count is not None:
    pending_failed_error = st.session_state.get("trigger_pending_failed_error") or "Unknown simulator error"
    st.error(
        f"PB4 simulation failed for observed trigger_count={pending_failed_count}: {pending_failed_error}. "
        "This failed trigger is pending only for this session; unchanged polls will not retry it."
    )
    if st.button("Retry failed PB4 simulation", key="retry_failed_pb4_simulation"):
        _run_pb4_simulation(pending_failed_count, manual_retry=True)
        st.rerun()

if st.button("Generate simulated rounds", type="primary"):
    with st.spinner("Preparing and measuring local Qiskit Aer circuits…"):
        st.session_state["bb84_result"] = simulate_bb84(
            round_count=rounds,
            disturbance_percent=disturbance,
            sample_size=sample_size,
        )

result = st.session_state.get("bb84_result")
if result is None:
    st.subheader("Ready to generate")
    st.write("Press **Generate simulated rounds** or enable PB4 polling and wait for a counter change. No result is fabricated before either action.")
else:
    st.subheader(f"{SIMULATED_LABEL} — Alice, Bob, sifting, and sample check")
    st.caption(SIMULATED_LABEL)
    matched = len(result.sifted_positions)
    sampled = len(result.sample_positions)
    metric_row = st.columns(4)
    metric_row[0].metric("Simulated rounds", len(result.rounds))
    metric_row[1].metric("Basis-matched / sifted", matched)
    metric_row[2].metric("Disclosed sample positions", sampled)
    metric_row[3].metric(
        "Sample QBER",
        "Unavailable" if result.sample_qber is None else f"{result.sample_qber:.1%}",
        help="Quantum Bit Error Rate: mismatches divided by the disclosed sample size. This small teaching measurement is not a security test.",
    )
    if result.sample_qber is None:
        st.warning(f"{SIMULATED_LABEL} — no basis-matched positions were available for the sample check.")
    else:
        st.write(
            f"{SIMULATED_LABEL} — sample errors: **{result.sample_error_count}/{sampled}**. "
            f"The illustrative pass threshold is {MAX_TEACHING_QBER:.0%}; this is a teaching rule, not a security guarantee."
        )

    with st.expander(f"{SIMULATED_LABEL} — disclosed sample used for QBER", expanded=True):
        st.caption(SIMULATED_LABEL)
        if result.sample_positions:
            st.write("Positions (1-based): " + ", ".join(str(i + 1) for i in result.sample_positions))
            st.write("Alice sample bits: " + "".join(str(result.rounds[i].alice_bit) for i in result.sample_positions))
            st.write("Bob sample measurements: " + "".join(str(result.rounds[i].bob_measurement) for i in result.sample_positions))
        else:
            st.write("No sample values exist because no bases matched.")

    st.subheader(f"{SIMULATED_LABEL} — per-round demonstration table")
    st.caption(
        f"{SIMULATED_LABEL}. Z and X are Alice's and Bob's chosen bases; only matching bases are sifted. "
        "The publicly disclosed sample positions are marked and excluded from the remaining demo string."
    )
    table_rows = [
        {
            "Round": record.index,
            "Alice bit": record.alice_bit,
            "Alice basis": record.alice_basis,
            "Bob basis": record.bob_basis,
            "Bob measurement": record.bob_measurement,
            "Bases match": record.bases_match,
            "Sifted": record.sifted,
            "Sampled for QBER": record.sampled_for_qber,
        }
        for record in result.rounds
    ]
    st.dataframe(table_rows, hide_index=True, use_container_width=True)

    st.subheader(f"{SIMULATED_LABEL} — post-sample teaching output")
    st.caption(
        f"{SIMULATED_LABEL}. This value is simulated and ephemeral. Copy/paste it manually only into the other local app's clearly labelled demo-only input, if desired."
    )
    if result.demo_bits is None:
        st.warning(
            f"{SIMULATED_LABEL} — no demo bit string is offered because the sample check did not pass, "
            "the remaining strings differed, or no bits remained after sampling. Generate another run or adjust the optional disturbance."
        )
    else:
        st.write(f"{SIMULATED_LABEL} — Alice's remaining bits: `{result.post_sample_alice_bits}`")
        st.write(f"{SIMULATED_LABEL} — Bob's remaining bits: `{result.post_sample_bob_bits}`")
        st.markdown(f"**{SIMULATED_LABEL} — simulated demo bits for manual copy**")
        st.info("simulated key generated; not provisioned to ESP")
        st.code(result.demo_bits, language="text")
        st.caption(
            "Demo-only, ephemeral, and local-only. These bits are not a real QKD key. They are not provisioned or sent to ESP; "
            "there is no ESP key receipt, fingerprint, or transfer endpoint. Manual copy is only to the separate local demo app."
        )

st.divider()
st.markdown(
    "**No quantum channel exists.** Qiskit Aer executes circuits on this computer; its measurement outputs are simulated. "
    "A sample QBER from this small demonstration is not evidence of a secure link. Real pairing/security would need "
    "authenticated TLS provisioning, replay protection, and secure storage."
)
