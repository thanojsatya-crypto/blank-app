"""Shared visual theme helpers for the local teaching dashboards.

This module contains presentation-only Streamlit styling and UI components.
It does not alter application state, network calls, or cryptographic demo protocols.
"""
from __future__ import annotations

import streamlit as st


_THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap');

:root {
    --qkd-canvas: #f8fafc;
    --qkd-surface: #ffffff;
    --qkd-surface-elevated: #f1f5f9;
    --qkd-surface-card: #ffffff;
    --qkd-ink: #0f172a;
    --qkd-muted: #64748b;
    --qkd-border: #e2e8f0;
    --qkd-border-hover: #cbd5e1;
    --qkd-border-glow: rgba(79, 70, 229, 0.2);
    --qkd-accent: #4f46e5;
    --qkd-accent-hover: #4338ca;
    --qkd-accent-soft: rgba(79, 70, 229, 0.08);
    --qkd-teal: #0d9488;
    --qkd-emerald: #10b981;
    --qkd-amber: #d97706;
}

/* App Background & Typography - Light Mode */
[data-testid="stAppViewContainer"] {
    background-color: var(--qkd-canvas) !important;
    background: #f8fafc !important;
    color: var(--qkd-ink) !important;
}
[data-testid="stHeader"] {
    background: rgba(255, 255, 255, 0.88) !important;
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border-bottom: 1px solid var(--qkd-border);
}

/* Material symbols compatibility for test regression and crisp icon rendering */
[data-testid="stIconMaterial"] {
    font-family: "Material Symbols Rounded" !important;
}
[data-testid="stExpander"] [data-testid="stIconMaterial"] {
    font-family: "Material Symbols Rounded" !important;
}
button[data-testid="stBaseButton-headerNoPadding"] [data-testid="stIconMaterial"] {
    font-size: 0 !important;
    line-height: 0 !important;
}
[data-testid="stTextInput"] button [data-testid="stIconMaterial"] {
    font-size: 0 !important;
    line-height: 0 !important;
}

/* Prevent any sidebar collapse ligature text leaking */
[data-testid="collapsedControl"] button span,
button[data-testid="stSidebarCollapseButton"] span,
button[data-testid="stBaseButton-headerNoPadding"] span {
    font-size: 0 !important;
    line-height: 0 !important;
    color: transparent !important;
    display: none !important;
}
[data-testid="collapsedControl"] button::before,
button[data-testid="stSidebarCollapseButton"]::before,
button[data-testid="stBaseButton-headerNoPadding"]::before {
    content: "☰" !important;
    font-size: 16px !important;
    line-height: 1 !important;
    color: #475569 !important;
}

[data-testid="stMainBlockContainer"] {
    max-width: 1440px;
    padding-top: 1.5rem;
    padding-bottom: 4rem;
}
html, body, [class*="st-"], [data-testid="stMarkdownContainer"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    letter-spacing: -0.012em;
    color: #0f172a;
}
code, pre, .mono {
    font-family: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace !important;
}

/* Headers in Light Mode */
[data-testid="stMainBlockContainer"] h1 {
    color: #0f172a !important;
    font-size: clamp(1.85rem, 2.8vw, 2.45rem);
    font-weight: 750;
    letter-spacing: -0.035em;
    line-height: 1.15;
    margin: 0.15rem 0 0.4rem;
}
[data-testid="stMainBlockContainer"] h2,
[data-testid="stMainBlockContainer"] h3 {
    color: #1e293b !important;
    font-weight: 700;
    letter-spacing: -0.02em;
}
[data-testid="stMainBlockContainer"] p,
[data-testid="stMainBlockContainer"] li {
    color: #334155 !important;
    line-height: 1.62;
    font-size: 0.95rem;
}
[data-testid="stCaptionContainer"] { color: #64748b !important; font-size: 0.82rem; }

/* Sidebar Precision Styling in Light Mode */
[data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid var(--qkd-border) !important;
}
[data-testid="stSidebarContent"] { padding-top: 1.2rem; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.6rem; }
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 { color: #0f172a !important; }
[data-testid="stSidebar"] [role="radiogroup"] { gap: 0.25rem; }
[data-testid="stSidebar"] [role="radiogroup"] label {
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 0.4rem 0.65rem;
    transition: all 140ms ease;
    color: #334155 !important;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {
    background: #f1f5f9 !important;
}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
    background: #eef2ff !important;
    border-color: #c7d2fe !important;
}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {
    color: #4338ca !important;
    font-weight: 600;
}

/* Sidebar Brand */
.qkd-sidebar-brand {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.4rem 0.2rem 0.9rem;
    border-bottom: 1px solid var(--qkd-border);
    margin-bottom: 0.8rem;
}
.qkd-brand-mark {
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
    flex: 0 0 auto;
    border-radius: 10px;
    background: linear-gradient(135deg, #4f46e5 0%, #06b6d4 100%);
    color: #fff;
    font-size: 1.05rem;
    font-weight: 750;
    box-shadow: 0 4px 14px rgba(79, 70, 229, 0.25);
}
.qkd-brand-name {
    color: #0f172a !important;
    font-size: 0.9rem;
    font-weight: 650;
    line-height: 1.25;
}
.qkd-brand-subtitle {
    margin-top: 0.15rem;
    color: #64748b !important;
    font-size: 0.64rem;
    font-weight: 700;
    letter-spacing: 0.12em;
}

/* Page Kicker */
.qkd-page-kicker {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-bottom: 0.35rem;
    color: #64748b;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}
.qkd-page-kicker .qkd-status {
    display: inline-flex;
    align-items: center;
    border: 1px solid rgba(16, 185, 129, 0.3);
    border-radius: 999px;
    padding: 0.14rem 0.52rem;
    background: rgba(16, 185, 129, 0.1);
    color: #059669;
    font-size: 0.62rem;
    letter-spacing: 0.08em;
}

/* Containers */
[data-testid="stVerticalBlockBorderWrapper"] {
    border: 1px solid var(--qkd-border) !important;
    border-radius: 12px !important;
    background: #ffffff !important;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);
}
[data-testid="stVerticalBlockBorderWrapper"]:hover {
    border-color: #cbd5e1 !important;
}

/* Metrics */
[data-testid="stMetric"] {
    min-height: 96px;
    border: 1px solid var(--qkd-border);
    border-radius: 12px;
    padding: 0.9rem 1.1rem;
    background: #ffffff !important;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
}
[data-testid="stMetricLabel"] { color: #64748b !important; font-size: 0.8rem; font-weight: 550; }
[data-testid="stMetricValue"] { color: #0f172a !important; font-weight: 700; font-size: 1.55rem; font-family: "JetBrains Mono", monospace; }

/* Alerts in Light Mode */
[data-testid="stAlert"] {
    border-radius: 10px !important;
    border-width: 1px !important;
    border-style: solid !important;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.03);
}
[data-testid="stAlert"]:has([data-testid="stNotificationContentWarning"]) {
    border-color: #fde68a !important;
    border-left: 4px solid #f59e0b !important;
    background: #fffbeb !important;
    color: #92400e !important;
}
[data-testid="stAlert"]:has([data-testid="stNotificationContentInfo"]) {
    border-color: #c7d2fe !important;
    border-left: 4px solid #6366f1 !important;
    background: #eef2ff !important;
    color: #3730a3 !important;
}
[data-testid="stAlert"]:has([data-testid="stNotificationContentSuccess"]) {
    border-color: #a7f3d0 !important;
    border-left: 4px solid #10b981 !important;
    background: #ecfdf5 !important;
    color: #065f46 !important;
}
[data-testid="stAlert"]:has([data-testid="stNotificationContentError"]) {
    border-color: #fecaca !important;
    border-left: 4px solid #ef4444 !important;
    background: #fef2f2 !important;
    color: #991b1b !important;
}

/* Expanders */
[data-testid="stExpander"] {
    border: 1px solid var(--qkd-border) !important;
    border-radius: 10px !important;
    background: #ffffff !important;
    margin-bottom: 0.75rem;
}
[data-testid="stExpander"] summary {
    font-weight: 600;
    color: #1e293b !important;
}
[data-testid="stExpander"] summary:hover {
    color: #4f46e5 !important;
}

/* Tables & DataFrames */
[data-testid="stDataFrame"] {
    border: 1px solid var(--qkd-border);
    border-radius: 10px;
    background: #ffffff;
}

/* Inputs */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] input,
[data-testid="stSelectbox"] [data-baseweb="select"] > div {
    border-radius: 8px;
    background: #ffffff !important;
    border: 1px solid #cbd5e1 !important;
    color: #0f172a !important;
    font-family: inherit;
    transition: all 140ms ease;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stTextArea"] textarea:focus {
    border-color: #4f46e5 !important;
    box-shadow: 0 0 0 2px rgba(79, 70, 229, 0.15) !important;
}

/* Buttons */
.stButton > button {
    min-height: 2.45rem;
    border-radius: 8px;
    font-weight: 600;
    font-size: 0.88rem;
    border: 1px solid #cbd5e1;
    background: #ffffff;
    color: #1e293b;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    transition: all 150ms cubic-bezier(0.16, 1, 0.3, 1);
}
.stButton > button:hover {
    border-color: #94a3b8;
    background: #f8fafc;
    color: #0f172a;
    transform: translateY(-1px);
}
.stButton > button[kind="primary"] {
    border: 1px solid #4f46e5;
    background: #4f46e5;
    color: #ffffff;
    box-shadow: 0 2px 8px rgba(79, 70, 229, 0.25);
}
.stButton > button[kind="primary"]:hover {
    background: #4338ca;
    transform: translateY(-1px);
}

[data-testid="stCode"] pre,
[data-testid="stCodeBlock"] pre {
    border: 1px solid var(--qkd-border);
    border-radius: 10px;
    background: #f8fafc !important;
    color: #0284c7;
    font-family: "JetBrains Mono", monospace !important;
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

.quantum-node-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 1rem 1.3rem;
    margin: 0.6rem 0 1rem;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.04);
    position: relative;
    overflow: hidden;
    animation: fadeIn 350ms ease-out;
}

.quantum-node-left {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.quantum-radar-orb {
    position: relative;
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
    flex-shrink: 0;
}

.quantum-radar-core {
    width: 12px;
    height: 12px;
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
    animation: radarPing 2.2s infinite cubic-bezier(0.2, 0.8, 0.4, 1);
}

.quantum-node-info {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
}

.quantum-node-user-title {
    color: #0f172a;
    font-size: 0.98rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.quantum-status-pill {
    font-size: 0.65rem;
    font-weight: 700;
    padding: 0.12rem 0.5rem;
    border-radius: 999px;
    background: rgba(16, 185, 129, 0.12);
    color: #059669;
    border: 1px solid rgba(16, 185, 129, 0.3);
    letter-spacing: 0.06em;
}

.quantum-token-badge {
    color: #64748b;
    font-size: 0.78rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
}

.quantum-token-code {
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    color: #0284c7;
    padding: 0.12rem 0.45rem;
    border-radius: 5px;
    font-family: "JetBrains Mono", monospace;
    font-size: 0.76rem;
}

.quantum-signal-waves {
    display: flex;
    align-items: flex-end;
    gap: 3px;
    height: 22px;
    padding-right: 0.4rem;
}

.quantum-wave-bar {
    width: 3px;
    background: linear-gradient(180deg, #0284c7, #4f46e5);
    border-radius: 2px;
    animation: waveBarMotion 1.4s infinite ease-in-out;
}
.quantum-wave-bar:nth-child(1) { animation-delay: 0.1s; height: 8px; }
.quantum-wave-bar:nth-child(2) { animation-delay: 0.3s; height: 16px; }
.quantum-wave-bar:nth-child(3) { animation-delay: 0.5s; height: 12px; }
.quantum-wave-bar:nth-child(4) { animation-delay: 0.2s; height: 20px; }
.quantum-wave-bar:nth-child(5) { animation-delay: 0.4s; height: 10px; }

/* --- HOME PORTAL & MODULE WORKSPACE CARDS IN LIGHT MODE --- */
.portal-header-box {
    background: #ffffff;
    border: 1px solid var(--qkd-border);
    border-radius: 14px;
    padding: 1.5rem 1.8rem;
    margin-bottom: 1.5rem;
    box-shadow: 0 4px 18px rgba(0, 0, 0, 0.03);
}
.portal-tagline {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    color: #4f46e5;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 0.5rem;
}
.portal-title {
    color: #0f172a;
    font-size: 1.85rem;
    font-weight: 750;
    letter-spacing: -0.03em;
    margin: 0 0 0.4rem;
    line-height: 1.2;
}
.portal-desc {
    color: #64748b;
    font-size: 0.95rem;
    max-width: 860px;
    line-height: 1.6;
    margin: 0;
}

.module-card-box {
    background: #ffffff;
    border: 1px solid var(--qkd-border);
    border-radius: 14px;
    padding: 1.4rem 1.4rem 1.2rem;
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.03);
    transition: all 180ms cubic-bezier(0.16, 1, 0.3, 1);
}
.module-card-box:hover {
    border-color: #818cf8;
    box-shadow: 0 8px 24px rgba(79, 70, 229, 0.08);
    transform: translateY(-2px);
}
.module-card-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.18rem 0.55rem;
    border-radius: 999px;
    font-size: 0.64rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    background: #eef2ff;
    color: #4338ca;
    border: 1px solid #c7d2fe;
}
.module-card-badge.active-badge {
    background: #ecfdf5;
    color: #047857;
    border-color: #a7f3d0;
}
.module-card-title {
    color: #0f172a;
    font-size: 1.18rem;
    font-weight: 700;
    margin: 0.7rem 0 0.4rem;
    letter-spacing: -0.015em;
}
.module-card-desc {
    color: #64748b;
    font-size: 0.88rem;
    line-height: 1.55;
    margin-bottom: 1rem;
    flex-grow: 1;
}
.module-card-features {
    list-style: none;
    padding: 0;
    margin: 0 0 1.2rem;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
}
.module-card-features li {
    color: #334155;
    font-size: 0.8rem;
    display: flex;
    align-items: center;
    gap: 0.45rem;
}
.module-card-features li::before {
    content: '✓';
    color: #10b981;
    font-weight: 700;
    font-size: 0.8rem;
}

/* Workspace Breadcrumb Header in Light Mode */
.workspace-nav-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.6rem 0.9rem;
    background: #ffffff;
    border: 1px solid var(--qkd-border);
    border-radius: 10px;
    margin-bottom: 1.2rem;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.03);
}
.workspace-breadcrumb {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    color: #64748b;
    font-size: 0.84rem;
    font-weight: 550;
}
.workspace-breadcrumb-active {
    color: #0f172a;
    font-weight: 650;
}

@media (max-width: 768px) {
    [data-testid="stMainBlockContainer"] { padding: 1rem 0.8rem 2.5rem; }
    [data-testid="stMainBlockContainer"] h1 { font-size: 1.6rem; }
    .portal-title { font-size: 1.45rem; }
    .quantum-node-card { flex-direction: column; align-items: flex-start; gap: 0.75rem; }
    .quantum-signal-waves { align-self: flex-end; }
    .workspace-nav-bar { flex-direction: column; align-items: flex-start; gap: 0.6rem; }
}
</style>
"""


def apply_ui_theme() -> None:
    """Apply a calm, card-based enterprise theme to a Streamlit app."""
    st.markdown(_THEME_CSS, unsafe_allow_html=True)


def render_sidebar_brand() -> None:
    """Render a project-specific sidebar identity."""
    st.markdown(
        """<div class="qkd-sidebar-brand">
            <div class="qkd-brand-mark">Q</div>
            <div>
                <div class="qkd-brand-name">QKD Teaching Project</div>
                <div class="qkd-brand-subtitle">ENTERPRISE WORKSPACE</div>
            </div>
        </div>""",
        unsafe_allow_html=True,
    )


def render_page_kicker(section: str, status: str = "LOCAL TEACHING DEMO") -> None:
    """Add a compact section label and an accurate status pill."""
    st.markdown(
        f"""<div class="qkd-page-kicker">
            <span>{section}</span><span class="qkd-status">{status}</span>
        </div>""",
        unsafe_allow_html=True,
    )


def render_animated_node_banner(user_name: str = "Quantum_Node_Master", api_token: str = "http://192.168.1.13", status: str = "LIVE ONLINE") -> None:
    """Render a responsive animated quantum node connection banner."""
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


def render_portal_hero(title: str, subtitle: str, badge_text: str = "MISSION WORKSPACE HUB") -> None:
    """Render the central portal hero header."""
    st.markdown(
        f"""<div class="portal-header-box">
            <div class="portal-tagline">
                <span>◈</span>
                <span>{badge_text}</span>
            </div>
            <h2 class="portal-title">{title}</h2>
            <p class="portal-desc">{subtitle}</p>
        </div>""",
        unsafe_allow_html=True,
    )
