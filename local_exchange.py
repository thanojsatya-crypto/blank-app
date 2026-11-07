"""Pure in-process helper for the non-secure local message demonstration.

This module intentionally performs no networking, file I/O, logging, or persistence.
The Streamlit caller owns the returned list in session state only.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

MAX_LOCAL_MESSAGES = 10
MAX_LOCAL_MESSAGE_CHARS = 240
SENT_STATUS = "Sent (local simulation)"
RECEIVED_STATUS = "Received (local simulation)"


def append_local_message(messages: Sequence[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Return a copied session log with one local echo message, capped at ten."""
    if len(messages) >= MAX_LOCAL_MESSAGES:
        raise ValueError(f"The session-only local log is capped at {MAX_LOCAL_MESSAGES} messages.")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Enter a short demo message before sending locally.")
    if len(text) > MAX_LOCAL_MESSAGE_CHARS:
        raise ValueError(f"Local demo messages may contain at most {MAX_LOCAL_MESSAGE_CHARS} characters.")

    message = text.strip()
    return [
        *messages,
        {
            "sent_message": message,
            "received_message": message,
            "sent_status": SENT_STATUS,
            "received_status": RECEIVED_STATUS,
        },
    ]
