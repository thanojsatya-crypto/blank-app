"""Generate a 256-bit key using Python's operating-system-backed secrets API."""
from __future__ import annotations

import secrets

KEY_BYTES = 32
KEY_BITS = KEY_BYTES * 8


def generate_os_csprng_key() -> bytes:
    """Return 32 bytes from the strongest randomness source provided by the OS.

    Python's :mod:`secrets` module is intended for cryptographic secrets and
    delegates to the operating system's secure random source. The output is
    cryptographically secure pseudorandom data, not a claim of true physical
    randomness, quantum randomness, or QKD.
    """
    key = secrets.token_bytes(KEY_BYTES)
    if not isinstance(key, bytes) or len(key) != KEY_BYTES:
        raise RuntimeError("Operating-system CSPRNG returned an invalid key length")
    return key
