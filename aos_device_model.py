"""Software-only model of the ESP's volatile AOS provisioning boundary for tests."""
from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from aos_key_transfer_adapter import (
    AOS_PRIMARY_HEADER,
    AOS_SPI,
    encode_aos_message_field,
    build_baseline_aad,
)
from pairing_config import validate_pairing_password


class AOSDeviceError(RuntimeError):
    def __init__(self, status_code: int, code: str):
        super().__init__(code)
        self.status_code = status_code
        self.code = code


class VolatileAOSDevice:
    """Minimal local model: no filesystem, persistence, logging, or web-site calls."""

    def __init__(self, *, random_bytes=os.urandom):
        self._random_bytes = random_bytes
        self._password = bytearray()
        self._key = bytearray(32)
        self._data_field = bytearray(32)
        self._provisioned = False
        self._nonce_prefix = self._random_bytes(8)
        if len(self._nonce_prefix) != 8:
            raise ValueError("The nonce source must return exactly eight bytes.")
        self._boot_id = os.urandom(16).hex()
        self._provision_id = None
        self._nonce_counter = 0

    @property
    def has_provision(self) -> bool:
        return self._provisioned

    def provision(self, password: str, key_bytes: bytes, message: str) -> dict[str, bool]:
        if not validate_pairing_password(password):
            raise AOSDeviceError(422, "invalid_pairing_password")
        if not isinstance(key_bytes, bytes) or len(key_bytes) != 32:
            raise AOSDeviceError(422, "key_must_be_exactly_32_bytes")
        try:
            field = encode_aos_message_field(message)
        except ValueError as exc:
            raise AOSDeviceError(422, "message_invalid_or_too_large") from exc
        self._clear_provisioning()
        self._password = bytearray(password.encode("ascii"))
        self._key[:] = key_bytes
        self._data_field[:] = field
        self._provision_id = os.urandom(16).hex()
        self._provisioned = True
        return {"accepted": True, "provisioned": True}

    def downlink(self, password: str) -> dict[str, str]:
        if not self._provisioned:
            raise AOSDeviceError(409, "demo_provision_required")
        try:
            supplied = password.encode("ascii")
        except (AttributeError, UnicodeEncodeError) as exc:
            raise AOSDeviceError(403, "demo_pairing_rejected") from exc
        expected = bytes(self._password)
        # Compare over the same maximum width to model constant-time credential checks.
        width = max(len(supplied), len(expected))
        mismatch = len(supplied) ^ len(expected)
        for index in range(width):
            left = supplied[index] if index < len(supplied) else 0
            right = expected[index] if index < len(expected) else 0
            mismatch |= left ^ right
        if mismatch:
            raise AOSDeviceError(403, "demo_pairing_rejected")
        if self._nonce_counter >= 0xFFFFFFFF:
            raise AOSDeviceError(503, "demo_iv_counter_unavailable_or_exhausted")
        self._nonce_counter += 1
        iv = self._nonce_prefix + self._nonce_counter.to_bytes(4, "big")
        security_header = AOS_SPI.to_bytes(2, "big") + iv
        aad = build_baseline_aad(AOS_PRIMARY_HEADER, AOS_SPI)
        sealed = AESGCM(bytes(self._key)).encrypt(iv, bytes(self._data_field), aad)
        ciphertext, tag = sealed[:-16], sealed[-16:]
        frame = AOS_PRIMARY_HEADER + security_header + ciphertext + tag
        return {
            "primary_header_hex": AOS_PRIMARY_HEADER.hex(),
            "security_header_hex": security_header.hex(),
            "ciphertext_hex": ciphertext.hex(),
            "tag_hex": tag.hex(),
            "frame_hex": frame.hex(),
            "key_hex": bytes(self._key).hex(),
            "boot_id": self._boot_id,
            "provision_id": self._provision_id,
        }

    def reset_or_reboot(self) -> None:
        """Model volatile-RAM loss and a new per-boot nonce prefix."""
        self._clear_provisioning()
        self._nonce_prefix = self._random_bytes(8)
        if len(self._nonce_prefix) != 8:
            raise ValueError("The nonce source must return exactly eight bytes.")
        self._boot_id = os.urandom(16).hex()
        self._nonce_counter = 0

    def _clear_provisioning(self) -> None:
        for buffer in (self._password, self._key, self._data_field):
            for index in range(len(buffer)):
                buffer[index] = 0
        self._password.clear()
        self._provision_id = None
        self._provisioned = False
