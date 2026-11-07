"""Shared visual theme helpers for the local teaching dashboards.

This module contains presentation-only Streamlit styling. It does not add
application state, network calls, or changes to the demo protocols.
"""
from __future__ import annotations

import streamlit as st


_THEME_CSS = """
<style>
:root {
    --qkd-canvas: #f5f7fb;
    --qkd-surface: #ffffff;
    --qkd-ink: #17243a;
    --qkd-muted: #65738b;
    --qkd-border: #e3e8f1;
    --qkd-accent: #5368d8;
    --qkd-accent-soft: #eef1ff;
    --qkd-teal: #258b83;
}

[data-testid="stAppViewContainer"] { background: var(--qkd-canvas); }
[data-testid="stHeader"] { background: transparent; }
/* The app-wide typography rule also matches Streamlit icon spans. Restore the
   Material Symbols font for expander ligatures so their names render as icons. */
[data-testid="stExpander"] [data-testid="stIconMaterial"] {
    font-family: "Material Symbols Rounded" !important;
}
/* Some local browsers lack Streamlit's Material Symbols font. Keep its
   sidebar-control hit area intact but prevent the fallback token spilling
   into the page as literal text. */
button[data-testid="stBaseButton-headerNoPadding"] [data-testid="stIconMaterial"] {
    font-size: 0 !important;
    line-height: 0 !important;
}
/* Password visibility controls also use a Material Symbols token. Hide its
   fallback word in browsers without the icon font, but keep the button usable. */
[data-testid="stTextInput"] button [data-testid="stIconMaterial"] {
    font-size: 0 !important;
    line-height: 0 !important;
}
[data-testid="stMainBlockContainer"] {
    max-width: 1560px;
    padding-top: 2rem;
    padding-bottom: 3rem;
}
html, body, [class*="st-"], [data-testid="stMarkdownContainer"] {
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
[data-testid="stMainBlockContainer"] h1 {
    background: linear-gradient(135deg, #1e3a8a 0%, #0d9488 50%, #4338ca 100%);
    background-size: 200% auto;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    animation: shine-title 6s ease-in-out infinite alternate;
    font-size: clamp(2rem, 3.2vw, 2.85rem);
    font-weight: 800;
    letter-spacing: -0.045em;
    line-height: 1.1;
    margin: 0.2rem 0 0.4rem;
}
@keyframes shine-title {
    0% { background-position: 0% 50%; }
    100% { background-position: 100% 50%; }
}
[data-testid="stMainBlockContainer"] h2,
[data-testid="stMainBlockContainer"] h3 {
    color: #0f172a;
    font-weight: 750;
    letter-spacing: -0.025em;
}
[data-testid="stMainBlockContainer"] p,
[data-testid="stMainBlockContainer"] li {
    color: #334158;
    line-height: 1.62;
}
[data-testid="stCaptionContainer"] { color: var(--qkd-muted); }

[data-testid="stSidebar"] {
    background: #fbfcff;
    border-right: 1px solid var(--qkd-border);
}
[data-testid="stSidebarContent"] { padding-top: 1.2rem; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.8rem; }
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 { color: var(--qkd-ink); }
[data-testid="stSidebar"] [role="radiogroup"] { gap: 0.35rem; }
[data-testid="stSidebar"] [role="radiogroup"] label {
    border: 1px solid transparent;
    border-radius: 11px;
    padding: 0.42rem 0.58rem;
    transition: background 120ms ease, border-color 120ms ease;
}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
    background: var(--qkd-accent-soft);
    border-color: #d8defe;
}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {
    color: #3449b4;
    font-weight: 650;
}
.qkd-sidebar-brand {
    display: flex;
    align-items: center;
    gap: 0.72rem;
    padding: 0.4rem 0.15rem 0.85rem;
}
.qkd-brand-mark {
    width: 42px;
    height: 42px;
    display: grid;
    place-items: center;
    flex: 0 0 auto;
    border-radius: 14px;
    background: linear-gradient(145deg, #6678e8, #4658c8);
    color: #fff;
    font-size: 1.12rem;
    font-weight: 760;
    box-shadow: 0 7px 18px rgba(73, 91, 199, 0.22);
}
.qkd-brand-name {
    color: var(--qkd-ink);
    font-size: 0.92rem;
    font-weight: 700;
    line-height: 1.25;
}
.qkd-brand-subtitle {
    margin-top: 0.2rem;
    color: var(--qkd-muted);
    font-size: 0.64rem;
    font-weight: 700;
    letter-spacing: 0.12em;
}
.qkd-page-kicker {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-bottom: 0.35rem;
    color: #556783;
    font-size: 0.72rem;
    font-weight: 750;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}
.qkd-page-kicker .qkd-status {
    display: inline-flex;
    align-items: center;
    border: 1px solid #d5e9e6;
    border-radius: 999px;
    padding: 0.18rem 0.55rem;
    background: #eff9f7;
    color: #26766f;
    font-size: 0.62rem;
    letter-spacing: 0.08em;
}

[data-testid="stVerticalBlockBorderWrapper"] {
    border: 1px solid var(--qkd-border) !important;
    border-radius: 16px !important;
    background: var(--qkd-surface) !important;
    box-shadow: 0 5px 20px rgba(23, 36, 58, 0.035);
    transition: transform 220ms cubic-bezier(0.16, 1, 0.3, 1), box-shadow 220ms cubic-bezier(0.16, 1, 0.3, 1);
}
[data-testid="stVerticalBlockBorderWrapper"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 12px 28px rgba(37, 99, 235, 0.08) !important;
}
[data-testid="stMetric"] {
    min-height: 102px;
    border: 1px solid var(--qkd-border);
    border-radius: 14px;
    padding: 0.95rem 1rem;
    background: var(--qkd-surface);
    box-shadow: 0 3px 14px rgba(23, 36, 58, 0.025);
    transition: transform 200ms ease, box-shadow 200ms ease, border-color 200ms ease;
}
[data-testid="stMetric"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(37, 99, 235, 0.09);
    border-color: #cbd5e1;
}
[data-testid="stMetricLabel"] { color: var(--qkd-muted); font-weight: 600; }
[data-testid="stMetricValue"] { color: var(--qkd-ink); font-weight: 720; }
[data-testid="stAlert"] {
    border-radius: 12px;
    border-width: 1px;
    box-shadow: 0 4px 14px rgba(15, 23, 42, 0.03);
    animation: fadeIn 300ms ease-out;
}
[data-testid="stDataFrame"] {
    border: 1px solid var(--qkd-border);
    border-radius: 12px;
    overflow: hidden;
}
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] input,
[data-testid="stSelectbox"] [data-baseweb="select"] > div {
    border-radius: 10px;
    transition: border-color 180ms ease, box-shadow 180ms ease;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
    border-color: var(--qkd-accent) !important;
    box-shadow: 0 0 0 3px rgba(83, 104, 216, 0.15) !important;
}
.stButton > button {
    min-height: 2.55rem;
    border-radius: 10px;
    font-weight: 640;
    transition: transform 180ms cubic-bezier(0.16, 1, 0.3, 1), box-shadow 180ms ease, background 180ms ease;
}
.stButton > button[kind="primary"] {
    border-color: var(--qkd-accent);
    background: linear-gradient(135deg, #4f46e5 0%, #3b82f6 100%);
    box-shadow: 0 5px 16px rgba(79, 70, 229, 0.28);
}
.stButton > button[kind="primary"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 22px rgba(79, 70, 229, 0.42);
}
.stButton > button:hover { transform: translateY(-1px); }
[data-testid="stCode"] pre,
[data-testid="stCodeBlock"] pre {
    border: 1px solid var(--qkd-border);
    border-radius: 11px;
}
hr { border-color: var(--qkd-border); }

/* --- QUANTUM NODE & LIVE ANIMATION STYLES --- */
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes radarPing {
    0% { transform: scale(0.9); opacity: 0.9; }
    50% { transform: scale(1.8); opacity: 0; }
    100% { transform: scale(1.8); opacity: 0; }
}

@keyframes waveBarMotion {
    0%, 100% { height: 6px; }
    50% { height: 22px; }
}

@keyframes laserSweep {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(100%); }
}

@keyframes borderGlowPulse {
    0%, 100% { border-color: #6366f1; box-shadow: 0 0 15px rgba(99, 102, 241, 0.2); }
    50% { border-color: #06b6d4; box-shadow: 0 0 22px rgba(6, 182, 212, 0.35); }
}

.quantum-node-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 60%, #0f172a 100%);
    border: 1px solid rgba(99, 102, 241, 0.35);
    border-radius: 16px;
    padding: 1.1rem 1.4rem;
    margin: 0.8rem 0 1.2rem;
    box-shadow: 0 10px 25px rgba(15, 23, 42, 0.18);
    position: relative;
    overflow: hidden;
    animation: fadeIn 400ms ease-out;
}

.quantum-node-card::after {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 60%;
    height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.08), transparent);
    animation: laserSweep 5s infinite cubic-bezier(0.4, 0, 0.2, 1);
}

.quantum-node-left {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.quantum-radar-orb {
    position: relative;
    width: 38px;
    height: 38px;
    display: grid;
    place-items: center;
    flex-shrink: 0;
}

.quantum-radar-core {
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: #10b981;
    box-shadow: 0 0 10px #10b981;
    z-index: 2;
}

.quantum-radar-ring {
    position: absolute;
    width: 100%;
    height: 100%;
    border-radius: 50%;
    border: 2px solid #10b981;
    animation: radarPing 2s infinite cubic-bezier(0.2, 0.8, 0.4, 1);
}

.quantum-node-info {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
}

.quantum-node-user-title {
    color: #f8fafc;
    font-size: 1.05rem;
    font-weight: 750;
    letter-spacing: -0.01em;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.quantum-status-pill {
    font-size: 0.65rem;
    font-weight: 700;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    background: rgba(16, 185, 129, 0.2);
    color: #34d399;
    border: 1px solid rgba(16, 185, 129, 0.4);
    letter-spacing: 0.06em;
}

.quantum-token-badge {
    color: #94a3b8;
    font-size: 0.78rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
}

.quantum-token-code {
    background: rgba(15, 23, 42, 0.65);
    border: 1px solid rgba(148, 163, 184, 0.25);
    color: #38bdf8;
    padding: 0.15rem 0.45rem;
    border-radius: 6px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.76rem;
    letter-spacing: 0.02em;
}

.quantum-signal-waves {
    display: flex;
    align-items: flex-end;
    gap: 3px;
    height: 24px;
    padding-right: 0.5rem;
}

.quantum-wave-bar {
    width: 4px;
    background: linear-gradient(180deg, #38bdf8, #818cf8);
    border-radius: 3px;
    animation: waveBarMotion 1.4s infinite ease-in-out;
}

.quantum-wave-bar:nth-child(1) { animation-delay: 0.1s; height: 10px; }
.quantum-wave-bar:nth-child(2) { animation-delay: 0.3s; height: 18px; }
.quantum-wave-bar:nth-child(3) { animation-delay: 0.5s; height: 14px; }
.quantum-wave-bar:nth-child(4) { animation-delay: 0.2s; height: 22px; }
.quantum-wave-bar:nth-child(5) { animation-delay: 0.4s; height: 12px; }

@media (max-width: 760px) {
    [data-testid="stMainBlockContainer"] { padding: 1.15rem 1rem 2rem; }
    [data-testid="stMainBlockContainer"] h1 { font-size: 1.9rem; }
    [data-testid="stMetric"] { min-height: 90px; padding: 0.75rem; }
    .quantum-node-card { flex-direction: column; align-items: flex-start; gap: 0.75rem; }
    .quantum-signal-waves { align-self: flex-end; }
}
</style>
"""


def apply_ui_theme() -> None:
    """Apply a calm, card-based light theme to a Streamlit app."""
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


def render_sidebar_brand() -> None:
    """Render a project-specific sidebar identity, not a Cue feature or account."""
    st.markdown(
        """<div class="qkd-sidebar-brand">
            <div class="qkd-brand-mark">Q</div>
            <div>
                <div class="qkd-brand-name">QKD Teaching Project</div>
                <div class="qkd-brand-subtitle">LOCAL WORKSPACE</div>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_page_kicker(section: str, status: str = "LOCAL TEACHING DEMO") -> None:
    """Add a compact section label and an accurate local-demo status pill."""
    st.markdown(
        f"""<div class="qkd-page-kicker">
            <span>{section}</span><span class="qkd-status">{status}</span>
        </div>""",
        unsafe_allow_html=True,
    )


def render_animated_node_banner(user_name: str = "Quantum_Node_Master", api_token: str = "http://192.168.1.42", status: str = "LIVE ONLINE") -> None:
    """Render a responsive animated quantum node connection banner with pulsing radar & signal waves."""
    st.markdown(
        f"""<div class="quantum-node-card">
            <div class="quantum-node-left">
                <div class="quantum-radar-orb">
                    <div class="quantum-radar-ring"></div>
                    <div class="quantum-radar-core"></div>
                </div>
                <div class="quantum-node-info">
                    <div class="quantum-node-user-title">
                        <span>Node User: <strong>{user_name}</strong></span>
                        <span class="quantum-status-pill">● {status}</span>
                    </div>
                    <div class="quantum-token-badge">
                        <span>ESP Endpoint:</span>
                        <span class="quantum-token-code">{api_token}</span>
                    </div>
                </div>
            </div>
            <div class="quantum-signal-waves" title="Quantum signal transmission link active">
                <div class="quantum-wave-bar"></div>
                <div class="quantum-wave-bar"></div>
                <div class="quantum-wave-bar"></div>
                <div class="quantum-wave-bar"></div>
                <div class="quantum-wave-bar"></div>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )

