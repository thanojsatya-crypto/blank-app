from __future__ import annotations

import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import requests

from aos_key_demo import AOSKeyDemoResult
from aos_key_transfer_adapter import (
    AOSKeyTransferAdapter,
    AOS_PRIMARY_HEADER,
    AOS_SPI,
    TransferContractError,
    build_baseline_aad,
    build_provision_request,
    encode_aos_message_field,
    normalize_private_rfc1918_http_origin,
    pack_retained_bits,
    validate_downlink_response,
)
from pairing_config import validate_pairing_password

ORIGIN = "http://192.168.1.42"
PASSWORD = "Ab_-" * 8
KEY_BITS = "01" * 128
KEY = bytes.fromhex("55" * 32)
MESSAGE = "Hello 🌍"
IV = bytes.fromhex("00112233445566778899aabb")


def successful_result() -> AOSKeyDemoResult:
    return AOSKeyDemoResult(
        rounds_used=512,
        round_cap=1024,
        matched_sifted_count=400,
        sample_positions=tuple(range(64)),
        sample_alice_bits="0" * 64,
        sample_bob_bits="0" * 64,
        sample_error_count=7,
        sample_qber=7 / 64,
        post_sample_candidate_count=336,
        retained_positions=tuple(range(64, 320)),
        retained_bits=KEY_BITS,
        success=True,
        status_message="simulated test key",
    )


def valid_downlink_payload(message: str = MESSAGE, key: bytes = KEY) -> dict[str, str]:
    field = encode_aos_message_field(message)
    aad = build_baseline_aad(AOS_PRIMARY_HEADER, AOS_SPI)
    sealed = AESGCM(key).encrypt(IV, field, aad)
    security = AOS_SPI.to_bytes(2, "big") + IV
    fields = {
        "primary_header_hex": AOS_PRIMARY_HEADER.hex(),
        "security_header_hex": security.hex(),
        "ciphertext_hex": sealed[:-16].hex(),
        "tag_hex": sealed[-16:].hex(),
    }
    fields["frame_hex"] = "".join(fields[name] for name in (
        "primary_header_hex", "security_header_hex", "ciphertext_hex", "tag_hex"
    ))
    fields["key_hex"] = key.hex()
    fields["boot_id"] = "0123456789abcdef0123456789abcdef"
    fields["provision_id"] = "11111111111111111111111111111111"
    return fields


class FakeResponse:
    def __init__(self, payload=None, status=200, content_type="application/json"):
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self._payload = payload

    def json(self):
        return self._payload


class AOSAdapterTests(unittest.TestCase):
    def test_adapter_uses_only_new_dedicated_routes_and_not_ordinary_message_api(self):
        import aos_key_transfer_adapter as adapter_module
        from pathlib import Path
        source = Path(adapter_module.__file__).read_text(encoding="utf-8")
        self.assertIn("/api/aos-demo/provision", source)
        self.assertIn("/api/aos-demo/downlink", source)
        for obsolete in ("/api/pair", "/api/demo-key", "/api/aos-demo/encrypt", "/api/aos-demo/telemetry", "/api/message"):
            self.assertNotIn(obsolete, source)

    def test_message_field_has_explicit_utf8_length_padding_and_oversize_rejection(self):
        field = encode_aos_message_field(MESSAGE)
        encoded = MESSAGE.encode("utf-8")
        self.assertEqual(len(field), 32)
        self.assertEqual(field[0], len(encoded))
        self.assertEqual(field[1:1 + len(encoded)], encoded)
        self.assertEqual(field[1 + len(encoded):], bytes(31 - len(encoded)))
        self.assertEqual(encode_aos_message_field("é" * 15)[0], 30)
        for message in ("", "é" * 16, "A" * 32, "\ud800"):
            with self.subTest(message=repr(message)), self.assertRaises(ValueError):
                encode_aos_message_field(message)

    def test_exact_256_bit_big_endian_packing_and_provision_body(self):
        self.assertEqual(pack_retained_bits(KEY_BITS), bytes.fromhex("55" * 32))
        request = build_provision_request(PASSWORD, successful_result(), MESSAGE)
        self.assertEqual(set(request), {"password", "key_hex", "message"})
        self.assertEqual(request, {"password": PASSWORD, "key_hex": bytes.fromhex("55" * 32).hex(), "message": MESSAGE})
        self.assertNotIn("pairing_id", request)
        self.assertNotIn("key_id", request)
        self.assertTrue(validate_pairing_password(PASSWORD))
        with self.assertRaises(ValueError):
            pack_retained_bits("1" * 255)
        with self.assertRaises(ValueError):
            build_provision_request("DEMO-ONLY-PAIRING", successful_result(), MESSAGE)

    def test_private_ipv4_http_origin_allowlist_is_strict(self):
        self.assertEqual(normalize_private_rfc1918_http_origin("http://192.168.1.42:80/"), "http://192.168.1.42:80")
        for value in (
            "https://192.168.1.42", "http://8.8.8.8", "http://127.0.0.1", "http://169.254.1.2",
            "http://esp32.local", "http://192.168.1.42/api", "http://192.168.1.42?x=1",
            "http://user:pass@192.168.1.42", "http://[::1]", "http://192.168.1.42:",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_private_rfc1918_http_origin(value)

    @patch("aos_key_transfer_adapter.requests.post")
    def test_key_generator_posts_password_key_and_message_once_without_echoing_secrets(self, post):
        post.return_value = FakeResponse({"accepted": True, "provisioned": True})
        AOSKeyTransferAdapter().provision(ORIGIN, PASSWORD, successful_result(), MESSAGE)
        post.assert_called_once()
        args, options = post.call_args
        self.assertEqual(args[0], ORIGIN + "/api/aos-demo/provision")
        self.assertEqual(options["json"], {
            "password": PASSWORD,
            "key_hex": bytes.fromhex("55" * 32).hex(),
            "message": MESSAGE,
        })
        self.assertEqual(options["allow_redirects"], False)
        self.assertEqual(options["timeout"], 2.0)
        self.assertEqual(set(options["json"]), {"password", "key_hex", "message"})

    @patch("aos_key_transfer_adapter.requests.post")
    def test_unknown_provision_delivery_is_not_retried(self, post):
        post.side_effect = requests.Timeout("sensitive detail not exposed")
        with self.assertRaises(TransferContractError) as caught:
            AOSKeyTransferAdapter().provision(ORIGIN, PASSWORD, successful_result(), MESSAGE)
        self.assertTrue(caught.exception.delivery_unknown)
        post.assert_called_once()
        self.assertNotIn("sensitive detail", str(caught.exception))

    @patch("aos_key_transfer_adapter.requests.post")
    def test_base_station_sends_only_password_and_validates_returned_frame_and_key(self, post):
        post.return_value = FakeResponse(valid_downlink_payload())
        result = AOSKeyTransferAdapter().fetch_downlink(ORIGIN, PASSWORD)
        post.assert_called_once()
        args, options = post.call_args
        self.assertEqual(args[0], ORIGIN + "/api/aos-demo/downlink")
        self.assertEqual(options["json"], {"password": PASSWORD})
        self.assertEqual(set(options["json"]), {"password"})
        self.assertEqual(result.boot_id, "0123456789abcdef0123456789abcdef")
        self.assertEqual(result.provision_id, "11111111111111111111111111111111")
        self.assertEqual(result.key_bytes, KEY)
        self.assertEqual(len(bytes.fromhex(result.frame.frame_hex)), 68)

    def test_downlink_response_contract_rejects_extra_or_invalid_key_fields(self):
        payload = valid_downlink_payload()
        parsed = validate_downlink_response(payload)
        self.assertEqual(parsed.key_bytes, KEY)
        with self.assertRaises(ValueError):
            validate_downlink_response({**payload, "password": PASSWORD})
        with self.assertRaises(ValueError):
            validate_downlink_response({**payload, "key_hex": "0" * 62})
        with self.assertRaises(ValueError):
            validate_downlink_response({**payload, "boot_id": "short"})
        with self.assertRaises(ValueError):
            validate_downlink_response({**payload, "provision_id": "short"})

    @patch("aos_key_transfer_adapter.requests.post")
    def test_stale_or_wrong_password_responses_are_reported_without_retry(self, post):
        for status, expected in ((409, "volatile provision"), (403, "password")):
            post.reset_mock()
            post.return_value = FakeResponse({"error": "safe code"}, status=status)
            with self.subTest(status=status), self.assertRaises(TransferContractError) as caught:
                AOSKeyTransferAdapter().fetch_downlink(ORIGIN, PASSWORD)
            self.assertEqual(caught.exception.status_code, status)
            self.assertIn(expected, str(caught.exception))
            post.assert_called_once()

    def test_annex_e3_teaching_aad_is_fixed(self):
        self.assertEqual(build_baseline_aad(AOS_PRIMARY_HEADER, AOS_SPI).hex(), "0012000000001234000000000000000000000000")


if __name__ == "__main__":
    unittest.main(verbosity=2)
