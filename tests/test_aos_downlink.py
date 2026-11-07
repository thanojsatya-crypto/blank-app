from __future__ import annotations

import unittest

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from aos_downlink import decode_aos_message_field, verify_firmware_telemetry
from aos_key_transfer_adapter import (
    AOS_PRIMARY_HEADER,
    AOS_SPI,
    build_baseline_aad,
    encode_aos_message_field,
)

KEY = bytes(range(32))
IV = bytes.fromhex("00112233445566778899aabb")
MESSAGE = "Hi 🌍"
FIELD = encode_aos_message_field(MESSAGE)


def make_payload(*, key: bytes = KEY, field: bytes = FIELD, include_key: bool = False) -> dict[str, str]:
    aad = build_baseline_aad(AOS_PRIMARY_HEADER, AOS_SPI)
    sealed = AESGCM(key).encrypt(IV, field, aad)
    security = AOS_SPI.to_bytes(2, "big") + IV
    ciphertext, tag = sealed[:-16], sealed[-16:]
    frame = AOS_PRIMARY_HEADER + security + ciphertext + tag
    payload = {
        "primary_header_hex": AOS_PRIMARY_HEADER.hex(),
        "security_header_hex": security.hex(),
        "ciphertext_hex": ciphertext.hex(),
        "tag_hex": tag.hex(),
        "frame_hex": frame.hex(),
    }
    if include_key:
        payload["key_hex"] = key.hex()
        payload["boot_id"] = "0123456789abcdef0123456789abcdef"
        payload["provision_id"] = "11111111111111111111111111111111"
    return payload


class AOSDownlinkTests(unittest.TestCase):
    def test_valid_firmware_frame_round_trip_discloses_message_only_after_tag_passes(self):
        result = verify_firmware_telemetry(make_payload(include_key=True))
        self.assertEqual(len(bytes.fromhex(result.frame.frame_hex)), 68)
        self.assertEqual(result.iv_hex, IV.hex())
        self.assertTrue(result.tag_verified)
        self.assertTrue(result.fixture_valid)
        self.assertEqual(result.plaintext, FIELD)
        self.assertEqual(result.message_text, MESSAGE)
        self.assertEqual(result.frame.aad_hex, "0012000000001234000000000000000000000000")

    def test_ciphertext_or_tag_tampering_fails_closed_without_plaintext(self):
        valid = make_payload(include_key=True)
        for field_name in ("ciphertext_hex", "tag_hex"):
            changed = dict(valid)
            changed[field_name] = ("00" if changed[field_name][:2] != "00" else "01") + changed[field_name][2:]
            changed["frame_hex"] = (
                changed["primary_header_hex"] + changed["security_header_hex"]
                + changed["ciphertext_hex"] + changed["tag_hex"]
            )
            with self.subTest(field=field_name):
                result = verify_firmware_telemetry(changed)
                self.assertFalse(result.tag_verified)
                self.assertIsNone(result.plaintext)
                self.assertIsNone(result.message_text)
                self.assertFalse(result.fixture_valid)

    def test_wrong_key_fails_closed_without_plaintext(self):
        result = verify_firmware_telemetry(make_payload(), bytes(reversed(KEY)))
        self.assertFalse(result.tag_verified)
        self.assertIsNone(result.plaintext)
        self.assertIsNone(result.message_text)
        self.assertIn("tag verification failed", result.failure_reason.lower())

    def test_changed_returned_key_fails_closed(self):
        payload = make_payload(include_key=True)
        payload["key_hex"] = bytes(reversed(KEY)).hex()
        result = verify_firmware_telemetry(payload)
        self.assertFalse(result.tag_verified)
        self.assertIsNone(result.plaintext)
        self.assertIsNone(result.message_text)

    def test_authenticated_but_malformed_length_utf8_or_padding_is_not_released(self):
        invalid_fields = (
            bytes(32),  # zero length
            bytes([32]) + b"A" * 31,  # oversize declared length
            bytes([2]) + b"\xc0\xaf" + bytes(29),  # invalid UTF-8
            bytes([1]) + b"A" + b"\x01" + bytes(29),  # non-zero padding
        )
        for invalid in invalid_fields:
            with self.subTest(field=invalid):
                result = verify_firmware_telemetry(make_payload(field=invalid), KEY)
                self.assertTrue(result.tag_verified)
                self.assertFalse(result.fixture_valid)
                self.assertIsNone(result.plaintext)
                self.assertIsNone(result.message_text)

    def test_message_field_decoder_requires_exact_size_and_length(self):
        self.assertEqual(decode_aos_message_field(FIELD), MESSAGE)
        for invalid in (b"short", bytes(31), bytes([0]) + bytes(31), bytes([1]) + b"A" + b"X" + bytes(29)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                decode_aos_message_field(invalid)

    def test_rejects_malformed_or_changed_frame_before_decryption(self):
        valid = make_payload()
        wrong_header = dict(valid)
        wrong_header["primary_header_hex"] = "69521234564b"
        wrong_header["frame_hex"] = (
            wrong_header["primary_header_hex"] + wrong_header["security_header_hex"]
            + wrong_header["ciphertext_hex"] + wrong_header["tag_hex"]
        )
        with self.assertRaises(ValueError):
            verify_firmware_telemetry(wrong_header, KEY)
        with self.assertRaises(ValueError):
            verify_firmware_telemetry({**valid, "extra": "field"}, KEY)
        with self.assertRaises(ValueError):
            verify_firmware_telemetry(valid, b"short")


if __name__ == "__main__":
    unittest.main(verbosity=2)
