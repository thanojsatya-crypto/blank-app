"""Strict client-side parser and fail-closed verifier for ESP-originated AOS telemetry."""
from __future__ import annotations

from dataclasses import dataclass
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from aos_key_transfer_adapter import (
    AOS_MESSAGE_MAX_UTF8_BYTES,
    AOS_PRIMARY_HEADER,
    AOS_SPI,
    AOS_FRAME_OCTETS,
    EncryptedAosFrame,
    build_baseline_aad,
    validate_downlink_response,
    validate_encrypt_response,
)


@dataclass(frozen=True)
class AOSDownlinkVerification:
    """Authenticated frame data; message content exists only after tag and format checks."""

    frame: EncryptedAosFrame
    iv_hex: str
    tag_verified: bool
    fixture_valid: bool
    plaintext: bytes | None
    message_text: str | None
    failure_reason: str | None


def decode_aos_message_field(field: bytes) -> str:
    """Decode length-prefixed UTF-8 bytes and require zero-only unused field padding."""
    if not isinstance(field, bytes) or len(field) != 32:
        raise ValueError("Authenticated AOS Data Field must be exactly 32 octets.")
    message_length = field[0]
    if not 1 <= message_length <= AOS_MESSAGE_MAX_UTF8_BYTES:
        raise ValueError("Authenticated AOS message length is outside the 1–31-octet teaching limit.")
    message_bytes = field[1:1 + message_length]
    if any(field[1 + message_length:]):
        raise ValueError("Authenticated AOS Data Field has non-zero bytes after its declared message length.")
    try:
        message = message_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("Authenticated AOS message is not valid UTF-8.") from exc
    if not message:
        raise ValueError("Authenticated AOS message is empty.")
    return message


def _frame_from_payload(payload: object) -> tuple[EncryptedAosFrame, bytes, bytes]:
    if not isinstance(payload, dict):
        raise ValueError("ESP downlink response must be a JSON object.")
    if "key_hex" in payload:
        response = validate_downlink_response(payload)
        frame = response.frame
        key_bytes = response.key_bytes
    else:
        frame = validate_encrypt_response(payload)
        key_bytes = b""
    raw = bytes.fromhex(frame.frame_hex)
    if len(raw) != AOS_FRAME_OCTETS:
        raise ValueError("The returned AOS frame is not exactly 68 octets.")
    primary_header = raw[:6]
    security_header = raw[6:20]
    ciphertext = raw[20:52]
    tag = raw[52:68]
    if primary_header != AOS_PRIMARY_HEADER:
        raise ValueError("The AOS primary header does not match the selected fixture.")
    spi = int.from_bytes(security_header[:2], "big")
    if spi != AOS_SPI:
        raise ValueError("The Security Header SPI does not match the selected fixture.")
    if len(security_header[2:]) != 12:
        raise ValueError("The AOS inline IV is not exactly 96 bits.")
    if (security_header.hex() != frame.security_header_hex
            or ciphertext.hex() != frame.ciphertext_hex or tag.hex() != frame.tag_hex):
        raise ValueError("Frame components do not match the returned 68-octet frame.")
    aad = build_baseline_aad(primary_header, spi)
    if aad.hex() != frame.aad_hex:
        raise ValueError("The Annex E3 AAD does not match the selected fixture.")
    return frame, key_bytes, raw


def verify_firmware_telemetry(payload: object, key_bytes: bytes | None = None) -> AOSDownlinkVerification:
    """Authenticate/decrypt a firmware frame; validate the encoded message before release.

    The normal downlink response includes the matching key returned by ESP after
    its pairing-password check. A test or teaching caller may supply an explicit
    local key instead. No plaintext is returned on a tag or Data Field failure.
    """
    frame, returned_key, raw = _frame_from_payload(payload)
    if key_bytes is None:
        key_bytes = returned_key
    if not isinstance(key_bytes, bytes) or len(key_bytes) not in (16, 32):
        raise ValueError("A local 16-byte (128-bit) or 32-byte (256-bit) AOS demo key is required for verification.")
    if returned_key and key_bytes != returned_key and len(key_bytes) == len(returned_key):
        raise ValueError("The local key does not match the AES key returned by ESP.")

    security_header = raw[6:20]
    ciphertext = raw[20:52]
    tag = raw[52:68]
    iv = security_header[2:]
    aad = build_baseline_aad(AOS_PRIMARY_HEADER, AOS_SPI)
    try:
        plaintext = AESGCM(key_bytes).decrypt(iv, ciphertext + tag, aad)
    except InvalidTag:
        return AOSDownlinkVerification(
            frame=frame,
            iv_hex=iv.hex(),
            tag_verified=False,
            fixture_valid=False,
            plaintext=None,
            message_text=None,
            failure_reason="GCM tag verification failed; plaintext withheld.",
        )

    try:
        message_text = decode_aos_message_field(plaintext)
    except ValueError as exc:
        return AOSDownlinkVerification(
            frame=frame,
            iv_hex=iv.hex(),
            tag_verified=True,
            fixture_valid=False,
            plaintext=None,
            message_text=None,
            failure_reason=f"Authenticated Data Field was invalid; plaintext withheld ({exc}).",
        )

    return AOSDownlinkVerification(
        frame=frame,
        iv_hex=iv.hex(),
        tag_verified=True,
        fixture_valid=True,
        plaintext=plaintext,
        message_text=message_text,
        failure_reason=None,
    )
