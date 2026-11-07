"""Transient demo-only pairing-PIN and message-key helpers.

This module performs no I/O, logging, persistence, or network operations.
"""
from __future__ import annotations

import base64
import hashlib
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PIN_DIGITS = 6
MESSAGE_KEY_CONTEXT = b"esp32-qkd-teaching-demo/message-key/v1\x00"


def generate_demo_pairing_pin() -> str:
    """Return a six-digit simulated demo PIN; it is not an ESP credential."""
    return f"{secrets.randbelow(10**PIN_DIGITS):0{PIN_DIGITS}d}"


def validate_simulated_bits(bits: str) -> str:
    """Validate manually pasted simulated bit material without storing it."""
    if not isinstance(bits, str):
        raise ValueError("Paste simulated 0/1 bits from Key Generator.")
    normalized = "".join(bits.split())
    if len(normalized) < 16 or any(bit not in "01" for bit in normalized):
        raise ValueError("Use at least 16 simulated bits containing only 0 and 1.")
    return normalized


def derive_demo_message_key(simulated_bits: str) -> bytes:
    """Derive a 256-bit demo key from simulated bits, never from the demo PIN."""
    bits = validate_simulated_bits(simulated_bits)
    return hashlib.sha256(MESSAGE_KEY_CONTEXT + bits.encode("ascii")).digest()


def encrypt_demo_message(simulated_bits: str, plaintext: str) -> dict[str, str]:
    """Encrypt one transient teaching message; the derived key is not returned."""
    if not isinstance(plaintext, str) or not plaintext:
        raise ValueError("Enter a short demo-only message (not a real secret).")
    key = derive_demo_message_key(simulated_bits)
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return {
        "nonce_b64": base64.b64encode(nonce).decode("ascii"),
        "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_demo_message(simulated_bits: str, nonce_b64: str, ciphertext_b64: str) -> str:
    """Decrypt a demo result in memory using the separately supplied bit string."""
    key = derive_demo_message_key(simulated_bits)
    try:
        nonce = base64.b64decode(nonce_b64, validate=True)
        ciphertext = base64.b64decode(ciphertext_b64, validate=True)
        if len(nonce) != 12:
            raise ValueError("Demo nonce has an invalid length.")
        cleartext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise ValueError("Demo decryption failed; check the simulated bits and transient ciphertext.") from exc
    return cleartext.decode("utf-8")
