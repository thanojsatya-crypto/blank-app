from __future__ import annotations

from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import copy
import json
import re
import threading
import time
import unittest
import zlib
from unittest.mock import patch

import requests
from local_exchange import append_local_message

from esp_api import (
    EspApiClient,
    EspApiError,
    MAX_ESP_MESSAGE_HISTORY,
    MAX_MESSAGE_BODY_BYTES,
    MAX_MESSAGE_RETRIES,
    MAX_MESSAGE_UTF8_BYTES,
    MESSAGE_TIMEOUT_SECONDS,
    MessageFrame,
    UINT32_MAX,
    append_esp_message_history,
    build_gate,
    build_message_frame,
    compute_message_crc32,
    message_utf8_byte_length,
    parse_telemetry,
    validate_message_ack,
    validate_chain,
)

MOCK_SIMULATION = {
    "type": "classical_state_vector",
    "interpretation": "MOCK ONLY — canned classical calculation, not hardware",
    "qubit_count": 1,
    "basis_order": [0, 1],
    "initial_state": {
        "amplitudes": [{"basis": 0, "real": 1.0, "imag": 0.0}],
        "probabilities": [{"basis": 0, "value": 1.0}],
    },
    "final_state": {
        "amplitudes": [{"basis": 0, "real": 1.0, "imag": 0.0}],
        "probabilities": [{"basis": 0, "value": 1.0}],
    },
    "measurement_performed": False,
}
MOCK_TELEMETRY = {
    "device": "MOCK ONLY — fake ESP32",
    "uptime_ms": 3210,
    "boot_id": "0123456789abcdef0123456789abcdef",
    "provision_id": "11111111111111111111111111111111",
    "state": 1,
    "message_index": 3,
    "display_mode": "cipher",
    "reseed_count": 7,
    "chain": [{"gate": "H", "target": 0}],
    "simulation": MOCK_SIMULATION,
}


class RecordingServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler):
        super().__init__(address, handler)
        self.seen = []
        self.get_mode = "success"
        self.post_mode = "success"
        self.message_mode = "success"
        self.message_frames = []
        self.message_cache = OrderedDict()
        self.message_accepted_count = 0
        self.message_drop_first_reply = False
        self.message_drop_delay = 0.15


class FakeHandler(BaseHTTPRequestHandler):
    server: RecordingServer

    def log_message(self, _format, *_args):
        return

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self._send_raw(status, body, "application/json")

    def _send_raw(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # The lost-response test intentionally times out before this write.
            return

    def do_GET(self):
        self.server.seen.append({"method": "GET", "path": self.path})
        if self.path != "/api/telemetry":
            self._send(404, {"error": "not_found"})
        elif self.server.get_mode == "http_error":
            self._send(503, {"error": "unavailable"})
        elif self.server.get_mode == "invalid_json":
            self._send_raw(200, b"not-json", "text/plain")
        elif self.server.get_mode == "timeout":
            time.sleep(0.2)  # Deliberately withhold the response past the short client timeout.
        else:
            self._send(200, MOCK_TELEMETRY)

    def do_POST(self):
        raw_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if self.path == "/api/message":
            self.server.message_frames.append(raw_body)
            self.server.seen.append({"method": "POST", "path": self.path, "raw_body": raw_body})
            self._handle_message(raw_body)
            return
        body = json.loads(raw_body)
        self.server.seen.append({"method": "POST", "path": self.path, "body": body})
        if self.path != "/api/control":
            self._send(404, {"error": "not_found"})
        elif self.server.post_mode == "http_error":
            self._send(503, {"error": "unavailable"})
        else:
            self._send(200, {"chain": body["chain"], "simulation": MOCK_SIMULATION})

    def _message_error(self, status, error, *, message_id=None, sequence=None, computed_crc32=None):
        payload = {
            "device": "esp32-qkd-teaching",
            "ack": False,
            "status": status,
            "integrity": "invalid" if status == "crc_mismatch" else "not_checked",
            "error": error,
        }
        if message_id is not None:
            payload["message_id"] = message_id
        if sequence is not None:
            payload["sequence"] = sequence
        if computed_crc32 is not None:
            payload["computed_crc32"] = computed_crc32
        return payload

    def _handle_message(self, raw_body):
        mode = self.server.message_mode
        if len(raw_body) > MAX_MESSAGE_BODY_BYTES:
            self._send(413, self._message_error("too_large", "body exceeds 1024 bytes"))
            return
        if mode == "server_5xx":
            self._send(503, {"error": "mock_server_error"})
            return
        if mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "/api/message/elsewhere")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, self._message_error("bad_request", "invalid JSON"))
            return
        if not isinstance(body, dict) or set(body) != {"message_id", "sequence", "message", "crc32"}:
            self._send(400, self._message_error("bad_request", "invalid fields"))
            return
        if (
            not isinstance(body["message_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", body["message_id"], re.ASCII)
            or type(body["sequence"]) is not int
            or not 1 <= body["sequence"] <= 0xffffffff
            or not isinstance(body["message"], str)
            or not isinstance(body["crc32"], str)
            or not re.fullmatch(r"[0-9a-f]{8}", body["crc32"], re.ASCII)
        ):
            self._send(400, self._message_error("bad_request", "invalid fields"))
            return
        if mode.startswith("force_"):
            forced = int(mode.removeprefix("force_"))
            status_name = {400: "bad_request", 409: "id_conflict", 413: "too_large", 422: "crc_mismatch"}[forced]
            computed = f"{zlib.crc32(body.get('message', '').encode('utf-8')) & 0xffffffff:08x}" if forced == 422 else None
            self._send(forced, self._message_error(
                status_name,
                "mocked protocol error",
                message_id=body.get("message_id"),
                sequence=body.get("sequence"),
                computed_crc32=computed,
            ))
            return
        if mode == "ack_false":
            self._send(200, self._message_error(
                "rejected", "mock rejected the request", message_id=body["message_id"], sequence=body["sequence"]
            ))
            return

        message_bytes = body["message"].encode("utf-8") if isinstance(body["message"], str) else b""
        computed_crc32 = f"{zlib.crc32(message_bytes) & 0xffffffff:08x}"
        if len(message_bytes) > MAX_MESSAGE_UTF8_BYTES:
            self._send(400, self._message_error("bad_request", "message too long"))
            return

        # Check cached IDs before CRC so any changed tuple under a live ID is a conflict.
        cached = self.server.message_cache.get(body["message_id"])
        fingerprint = (body["sequence"], body["message"], body["crc32"])
        if cached is not None:
            cached_fingerprint, original = cached
            if fingerprint != cached_fingerprint:
                self._send(409, self._message_error(
                    "id_conflict", "cached ID has different content",
                    message_id=body["message_id"], sequence=body["sequence"],
                ))
                return
            duplicate = copy.deepcopy(original)
            duplicate["status"] = "duplicate"
            duplicate["duplicate"] = True
            self._send(200, duplicate)
            return
        if body["crc32"] != computed_crc32:
            self._send(422, self._message_error(
                "crc_mismatch", "CRC mismatch", message_id=body["message_id"],
                sequence=body["sequence"], computed_crc32=computed_crc32,
            ))
            return

        self.server.message_accepted_count += 1
        self.server.message_accepted_count &= 0xffffffff
        esp_sequence = self.server.message_accepted_count
        accepted = {
            "device": "esp32-qkd-teaching",
            "message_id": body["message_id"],
            "sequence": body["sequence"],
            "ack": True,
            "status": "accepted",
            "esp_sequence": esp_sequence,
            "received_message": body["message"],
            "reply_message": "ESP32 received: " + body["message"],
            "request_crc32": body["crc32"],
            "computed_crc32": computed_crc32,
            "integrity": "valid",
            "duplicate": False,
        }
        self.server.message_cache[body["message_id"]] = (fingerprint, accepted)
        while len(self.server.message_cache) > 8:
            self.server.message_cache.popitem(last=False)
        if self.server.message_drop_first_reply:
            self.server.message_drop_first_reply = False
            time.sleep(self.server.message_drop_delay)
        if mode == "bad_integrity":
            accepted = copy.deepcopy(accepted)
            accepted["computed_crc32"] = "ffffffff" if computed_crc32 != "ffffffff" else "00000000"
            accepted["integrity"] = "invalid"
        self._send(200, accepted)


class EspApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = RecordingServer(("127.0.0.1", 0), FakeHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.server.seen.clear()
        self.server.get_mode = "success"
        self.server.post_mode = "success"
        self.server.message_mode = "success"
        self.server.message_frames.clear()
        self.server.message_cache.clear()
        self.server.message_accepted_count = 0
        self.server.message_drop_first_reply = False
        self.client = EspApiClient(self.base_url, timeout_seconds=1, allow_loopback_for_tests=True)

    def test_live_client_rejects_loopback_without_test_opt_in(self):
        with self.assertRaisesRegex(ValueError, "private LAN IPv4"):
            EspApiClient(self.base_url, timeout_seconds=1)

    def test_get_reads_exact_telemetry_route_and_preserves_physical_state(self):
        telemetry = self.client.get_telemetry()
        self.assertEqual(self.server.seen, [{"method": "GET", "path": "/api/telemetry"}])
        self.assertEqual(telemetry["state"], 1)
        self.assertEqual(telemetry["message_index"], 3)
        self.assertEqual(telemetry["display_mode"], "cipher")
        self.assertEqual(telemetry["reseed_count"], 7)
        self.assertEqual(telemetry["simulation"], MOCK_SIMULATION)
        self.assertIs(telemetry["simulation"]["measurement_performed"], False)

    def test_post_uses_exact_set_chain_envelope_and_explicit_gate_objects(self):
        chain = [build_gate("H", 0), build_gate("CNOT")]
        response = self.client.set_chain(chain)
        self.assertEqual(
            self.server.seen,
            [{"method": "POST", "path": "/api/control", "body": {"action": "set_chain", "chain": chain}}],
        )
        self.assertEqual(response["chain"], chain)
        self.assertEqual(response["simulation"], MOCK_SIMULATION)

    def test_all_supported_single_qubit_targets_are_explicit_and_exact(self):
        self.assertEqual(build_gate("X", 1), {"gate": "X", "target": 1})
        for invalid in (None, True, 1.0, "1", 2):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                build_gate("H", invalid)

    def test_cnot_orientation_and_schema_are_exact(self):
        self.assertEqual(build_gate("CNOT"), {"gate": "CNOT", "control": 0, "target": 1})
        with self.assertRaisesRegex(ValueError, "Only CNOT"):
            validate_chain([{"gate": "CNOT", "control": 1, "target": 0}])
        with self.assertRaisesRegex(ValueError, "only gate, control, and target"):
            validate_chain([{"gate": "CNOT", "control": 0, "target": 1, "simulated_key": "never-send"}])
        with self.assertRaisesRegex(ValueError, "one-qubit operation"):
            validate_chain([{"gate": "H", "target": 0, "pairing_pin": "never-send"}])

    def test_telemetry_rejects_secret_or_unknown_fields(self):
        with self.assertRaisesRegex(EspApiError, "outside the established"):
            parse_telemetry({**MOCK_TELEMETRY, "demo_message_key": "must-not-be-here"})
        with self.assertRaisesRegex(EspApiError, "boot_id"):
            parse_telemetry({**MOCK_TELEMETRY, "boot_id": "malformed"})
        with self.assertRaisesRegex(EspApiError, "provision_id"):
            parse_telemetry({**MOCK_TELEMETRY, "provision_id": "malformed"})

    def test_missing_telemetry_fields_are_preserved_for_not_reported_ui_labels(self):
        partial = {"state": 0}
        self.assertEqual(parse_telemetry(partial), partial)
        self.assertEqual(parse_telemetry({}), {})

    def test_timeout_non_2xx_and_invalid_json_are_reported_as_distinct_failures(self):
        self.server.get_mode = "timeout"
        short_timeout_client = EspApiClient(
            self.base_url, timeout_seconds=0.03, allow_loopback_for_tests=True
        )
        with self.assertRaises(EspApiError) as timeout:
            short_timeout_client.get_telemetry()
        self.assertEqual(timeout.exception.kind, "timeout")

        self.server.get_mode = "http_error"
        with self.assertRaises(EspApiError) as http_error:
            self.client.get_telemetry()
        self.assertEqual(http_error.exception.kind, "http")
        self.assertEqual(http_error.exception.status_code, 503)

        self.server.get_mode = "invalid_json"
        with self.assertRaises(EspApiError) as invalid_json:
            self.client.get_telemetry()
        self.assertEqual(invalid_json.exception.kind, "invalid_response")

    def test_control_rejects_non_2xx_and_extra_payload_before_transmission(self):
        self.server.post_mode = "http_error"
        with self.assertRaises(EspApiError) as http_error:
            self.client.set_chain([build_gate("H", 0)])
        self.assertEqual(http_error.exception.kind, "http")
        self.assertEqual(http_error.exception.status_code, 503)

        self.server.seen.clear()
        for extra_field, canary in (
            ("demo_message", "LOCAL_MESSAGE_CANARY"),
            ("pairing_pin", "LOCAL_PIN_CANARY"),
            ("simulated_key", "LOCAL_KEY_CANARY"),
            ("simulated_bits", "LOCAL_BITS_CANARY"),
        ):
            with self.subTest(extra_field=extra_field), self.assertRaisesRegex(
                RuntimeError, "accepts only action=set_chain and chain"
            ):
                self.client._request_json(
                    "POST", "/api/control",
                    {"action": "set_chain", "chain": [], extra_field: canary},
                )
        self.assertEqual(self.server.seen, [])

    def test_local_message_canary_is_not_in_any_esp_request(self):
        local_log = append_local_message([], "LOCAL_MESSAGE_CANARY")
        self.assertEqual(local_log[0]["sent_message"], "LOCAL_MESSAGE_CANARY")
        self.client.set_chain([build_gate("X", 1)])
        request = self.server.seen[-1]
        self.assertEqual(request["path"], "/api/control")
        self.assertEqual(set(request["body"]), {"action", "chain"})
        self.assertEqual(request["body"], {"action": "set_chain", "chain": [{"gate": "X", "target": 1}]})
        self.assertNotIn("LOCAL_MESSAGE_CANARY", json.dumps(request))

    def test_control_client_cannot_use_unapproved_endpoint(self):
        with self.assertRaisesRegex(RuntimeError, "Only the documented"):
            self.client._request_json("POST", "/api/key", {"key": "never-send"})
        self.assertEqual(self.server.seen, [])

    def test_empty_chain_is_valid(self):
        result = self.client.set_chain([])
        self.assertEqual(result["chain"], [])
        self.assertEqual(self.server.seen[0]["path"], "/api/control")

    def test_message_frame_has_exact_schema_and_crc32_iso_hdlc_uses_only_utf8_message_bytes(self):
        self.assertEqual(compute_message_crc32("123456789"), "cbf43926")
        text = "QKD café"
        frame = build_message_frame("id_01-A", 7, text)
        decoded = json.loads(frame.serialized.decode("utf-8"))
        self.assertEqual(set(decoded), {"message_id", "sequence", "message", "crc32"})
        self.assertEqual(decoded, {
            "message_id": "id_01-A",
            "sequence": 7,
            "message": text,
            "crc32": f"{zlib.crc32(text.encode('utf-8')) & 0xffffffff:08x}",
        })
        self.assertEqual(frame.crc32, compute_message_crc32(text))
        self.assertNotEqual(frame.crc32, f"{zlib.crc32(frame.serialized) & 0xffffffff:08x}")
        self.assertLessEqual(len(frame.serialized), MAX_MESSAGE_BODY_BYTES)

    def test_message_schema_uint32_and_utf8_byte_boundaries(self):
        exact_boundary = "😀" * 64
        self.assertEqual(message_utf8_byte_length(exact_boundary), MAX_MESSAGE_UTF8_BYTES)
        frame = build_message_frame("A" * 32, 1, exact_boundary)
        self.assertLessEqual(len(frame.serialized), MAX_MESSAGE_BODY_BYTES)
        self.assertEqual(json.loads(frame.serialized)["message"], exact_boundary)
        self.assertEqual(message_utf8_byte_length("é" * 128), MAX_MESSAGE_UTF8_BYTES)

        for invalid_id in ("", "x" * 33, "has space", "ümlaut", "!bad"):
            with self.subTest(invalid_id=invalid_id), self.assertRaises(ValueError):
                build_message_frame(invalid_id, 1, "text")
        for invalid_sequence in (0, -1, True, 1.0, UINT32_MAX + 1):
            with self.subTest(invalid_sequence=invalid_sequence), self.assertRaises(ValueError):
                build_message_frame("valid", invalid_sequence, "text")
        with self.assertRaisesRegex(ValueError, "256 UTF-8 bytes"):
            build_message_frame("valid", UINT32_MAX, "😀" * 65)

    def test_json_body_limit_is_checked_independently_of_message_utf8_limit(self):
        # NUL is one UTF-8 byte but expands to six ASCII bytes in JSON escaping.
        exact_body = build_message_frame("id", 1, "\x00" * 160)
        self.assertEqual(len(exact_body.serialized), MAX_MESSAGE_BODY_BYTES)
        accepted = self.client.send_message(exact_body)
        self.assertEqual(accepted.response["status"], "accepted")
        self.assertEqual(self.server.message_frames[0], exact_body.serialized)

        with self.assertRaisesRegex(ValueError, "JSON request body may contain at most 1024 bytes"):
            build_message_frame("id", 1, "\x00" * 161)
        body_limited_frame = build_message_frame("id", 1, "\x00" * 150)
        self.assertLessEqual(len(body_limited_frame.serialized), MAX_MESSAGE_BODY_BYTES)
        self.assertEqual(message_utf8_byte_length(body_limited_frame.message), 150)

    def test_protocol_mock_rejects_invalid_json_fields_and_oversized_bodies(self):
        for raw_body, expected_status in (
            (b"not-json", 400),
            (b'{"message_id":"x","sequence":1,"message":"x","crc32":"12345678","extra":true}', 400),
            (b"x" * (MAX_MESSAGE_BODY_BYTES + 1), 413),
        ):
            with self.subTest(expected_status=expected_status, body_len=len(raw_body)):
                response = requests.post(
                    f"{self.base_url}/api/message",
                    data=raw_body,
                    timeout=1,
                    headers={"Content-Type": "application/json"},
                    allow_redirects=False,
                )
                payload = response.json()
                self.assertEqual(response.status_code, expected_status)
                self.assertIs(payload["ack"], False)
                self.assertEqual(payload["integrity"], "not_checked")
                self.assertNotIn("reply_message", payload)

    def test_message_client_posts_exact_frame_and_validates_esp_ack(self):
        frame = build_message_frame("ack-check", 42, "sent once")
        delivery = self.client.send_message(frame)
        response = delivery.response
        self.assertEqual(self.server.message_frames, [frame.serialized])
        self.assertEqual(self.server.seen[0]["path"], "/api/message")
        self.assertEqual(response["device"], "esp32-qkd-teaching")
        self.assertEqual(response["message_id"], frame.message_id)
        self.assertEqual(response["sequence"], frame.sequence)
        self.assertIs(response["ack"], True)
        self.assertEqual(response["status"], "accepted")
        self.assertEqual(response["esp_sequence"], 1)
        self.assertEqual(response["received_message"], frame.message)
        self.assertEqual(response["reply_message"], "ESP32 received: sent once")
        self.assertEqual(response["request_crc32"], frame.crc32)
        self.assertEqual(response["computed_crc32"], frame.crc32)
        self.assertEqual(response["integrity"], "valid")
        self.assertIs(response["duplicate"], False)
        self.assertEqual(delivery.attempts, ({"attempt": 1, "status": "ESP ACK received", "http_status": 200},))

    def test_message_http_400_409_413_422_errors_preserve_esp_ack_false_and_integrity(self):
        frame = build_message_frame("error-case", 5, "crc text")
        for status, mode, status_name, integrity in (
            (400, "force_400", "bad_request", "not_checked"),
            (409, "force_409", "id_conflict", "not_checked"),
            (413, "force_413", "too_large", "not_checked"),
            (422, "force_422", "crc_mismatch", "invalid"),
        ):
            with self.subTest(http_status=status):
                self.server.message_mode = mode
                self.server.message_frames.clear()
                with self.assertRaises(EspApiError) as caught:
                    self.client.send_message(frame)
                error = caught.exception
                self.assertEqual(error.status_code, status)
                self.assertEqual(len(error.attempts), 1)
                self.assertEqual(error.response_payload["device"], "esp32-qkd-teaching")
                self.assertIs(error.response_payload["ack"], False)
                self.assertEqual(error.response_payload["status"], status_name)
                self.assertEqual(error.response_payload["integrity"], integrity)
                self.assertNotIn("reply_message", error.response_payload)
                if status == 422:
                    self.assertEqual(error.response_payload["computed_crc32"], frame.crc32)
                self.assertEqual(len(self.server.message_frames), 1)

    def test_protocol_mock_returns_422_for_bad_request_crc_with_computed_message_crc(self):
        frame = build_message_frame("bad-crc", 6, "message only")
        bad_body = json.loads(frame.serialized)
        bad_body["crc32"] = "00000000" if frame.crc32 != "00000000" else "ffffffff"
        response = requests.post(
            f"{self.base_url}/api/message",
            data=json.dumps(bad_body, separators=(",", ":")).encode("utf-8"),
            timeout=1,
            headers={"Content-Type": "application/json"},
            allow_redirects=False,
        )
        payload = response.json()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(payload["status"], "crc_mismatch")
        self.assertIs(payload["ack"], False)
        self.assertEqual(payload["integrity"], "invalid")
        self.assertEqual(payload["computed_crc32"], frame.crc32)
        self.assertNotIn("reply_message", payload)

    def test_no_retry_for_4xx_redirect_ack_false_or_bad_integrity(self):
        frame = build_message_frame("no-retry", 9, "one attempt")
        expected_kinds = {
            "force_400": "http",
            "force_409": "http",
            "force_413": "http",
            "force_422": "http",
            "redirect": "redirect",
            "ack_false": "ack_rejected",
            "bad_integrity": "integrity",
        }
        for mode, kind in expected_kinds.items():
            with self.subTest(mode=mode):
                self.server.message_mode = mode
                self.server.message_frames.clear()
                with self.assertRaises(EspApiError) as caught:
                    self.client.send_message(frame)
                self.assertEqual(caught.exception.kind, kind)
                self.assertEqual(len(caught.exception.attempts), 1)
                self.assertEqual(len(self.server.message_frames), 1)

    def test_message_timeout_uses_two_seconds_and_at_most_two_retries_for_5xx(self):
        self.assertEqual(MESSAGE_TIMEOUT_SECONDS, 2.0)
        self.assertEqual(MAX_MESSAGE_RETRIES, 2)
        self.assertEqual(self.client.message_timeout_seconds, 2.0)
        self.assertEqual(self.client.message_max_retries, 2)
        frame = build_message_frame("server-errors", 10, "retry cap")
        self.server.message_mode = "server_5xx"
        with self.assertRaises(EspApiError) as caught:
            self.client.send_message(frame)
        self.assertEqual(caught.exception.kind, "delivery_unknown")
        self.assertEqual(len(caught.exception.attempts), MAX_MESSAGE_RETRIES + 1)
        self.assertEqual(len(self.server.message_frames), MAX_MESSAGE_RETRIES + 1)
        self.assertEqual(
            [attempt["http_status"] for attempt in caught.exception.attempts],
            [503, 503, 503],
        )

    def test_message_timeout_enforces_the_two_second_upper_bound(self):
        exact_limit = EspApiClient(
            self.base_url, allow_loopback_for_tests=True,
            message_timeout_seconds=2.0,
        )
        self.assertEqual(exact_limit.message_timeout_seconds, 2.0)
        with self.assertRaisesRegex(ValueError, "at most 2 seconds"):
            EspApiClient(
                self.base_url, allow_loopback_for_tests=True,
                message_timeout_seconds=2.000001,
            )

    def test_message_timeout_rejects_invalid_values(self):
        for invalid_timeout in (
            0, -0.001, True, False, "1", None, complex(1, 0),
            float("nan"), float("inf"), float("-inf"), 10**309,
        ):
            with self.subTest(invalid_timeout=repr(invalid_timeout)), self.assertRaisesRegex(
                ValueError, "finite number greater than 0 and at most 2 seconds"
            ):
                EspApiClient(
                    self.base_url, allow_loopback_for_tests=True,
                    message_timeout_seconds=invalid_timeout,
                )

    def test_message_timeout_accepts_lower_values_and_the_default(self):
        lower_timeout = EspApiClient(
            self.base_url, allow_loopback_for_tests=True,
            message_timeout_seconds=0.001,
        )
        default_timeout = EspApiClient(self.base_url, allow_loopback_for_tests=True)
        self.assertEqual(lower_timeout.message_timeout_seconds, 0.001)
        self.assertEqual(default_timeout.message_timeout_seconds, MESSAGE_TIMEOUT_SECONDS)

    def test_timeout_and_connection_errors_are_retried_only_twice(self):
        frame = build_message_frame("network-errors", 11, "same bytes")
        for failure in (requests.Timeout, requests.ConnectionError):
            with self.subTest(failure=failure.__name__), patch(
                "esp_api.requests.Session.post", side_effect=failure("mock network failure")
            ) as post:
                with self.assertRaises(EspApiError) as caught:
                    self.client.send_message(frame)
                self.assertEqual(caught.exception.kind, "delivery_unknown")
                self.assertEqual(len(caught.exception.attempts), 3)
                self.assertEqual(post.call_count, 3)
                self.assertTrue(all(call.kwargs["data"] == frame.serialized for call in post.call_args_list))
                self.assertTrue(all(call.kwargs["timeout"] == 2.0 for call in post.call_args_list))
                self.assertTrue(all(call.kwargs["allow_redirects"] is False for call in post.call_args_list))

    def test_lost_response_retries_exact_frame_and_gets_duplicate_without_second_acceptance(self):
        frame = build_message_frame("lost-reply", 12, "accepted before disconnect")
        self.server.message_drop_first_reply = True
        client = EspApiClient(
            self.base_url, allow_loopback_for_tests=True,
            message_timeout_seconds=0.04, message_max_retries=2,
        )
        delivery = client.send_message(frame)
        self.assertEqual(self.server.message_frames, [frame.serialized, frame.serialized])
        self.assertEqual(delivery.response["status"], "duplicate")
        self.assertIs(delivery.response["duplicate"], True)
        self.assertEqual(delivery.response["esp_sequence"], 1)
        self.assertEqual(delivery.response["reply_message"], "ESP32 received: accepted before disconnect")
        self.assertEqual(self.server.message_accepted_count, 1)
        self.assertEqual([attempt["status"] for attempt in delivery.attempts], ["timeout", "ESP ACK received"])

    def test_changed_cached_id_sequence_or_text_conflicts_without_accepting_again(self):
        original = build_message_frame("conflict-id", 20, "first text")
        first = self.client.send_message(original).response
        changed_sequence = build_message_frame("conflict-id", 21, "first text")
        changed_text = build_message_frame("conflict-id", 20, "changed text")
        for altered in (changed_sequence, changed_text):
            with self.subTest(sequence=altered.sequence, message=altered.message):
                with self.assertRaises(EspApiError) as caught:
                    self.client.send_message(altered)
                self.assertEqual(caught.exception.status_code, 409)
                self.assertEqual(caught.exception.response_payload["status"], "id_conflict")
                self.assertIs(caught.exception.response_payload["ack"], False)
                self.assertEqual(len(caught.exception.attempts), 1)
        self.assertEqual(self.server.message_accepted_count, 1)
        self.assertEqual(first["reply_message"], "ESP32 received: first text")

    def test_changed_cached_crc_alone_is_id_conflict(self):
        original = build_message_frame("crc-conflict", 31, "unchanged text")
        self.client.send_message(original)
        changed = json.loads(original.serialized)
        changed["crc32"] = "ffffffff" if original.crc32 != "ffffffff" else "00000000"
        response = requests.post(
            f"{self.base_url}/api/message",
            data=json.dumps(changed, separators=(",", ":")).encode("utf-8"),
            timeout=1,
            headers={"Content-Type": "application/json"},
            allow_redirects=False,
        )
        payload = response.json()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(payload["status"], "id_conflict")
        self.assertIs(payload["ack"], False)
        self.assertEqual(self.server.message_accepted_count, 1)

    def test_last_eight_id_dedupe_window_replays_original_sequence_then_eviction_accepts_again(self):
        original = build_message_frame("oldest", 1, "oldest text")
        original_response = self.client.send_message(original).response
        for index in range(2, 9):
            self.client.send_message(build_message_frame(f"id{index}", index, f"message {index}"))
        self.assertEqual(self.server.message_accepted_count, 8)

        replay_inside_window = self.client.send_message(original).response
        self.assertEqual(replay_inside_window["status"], "duplicate")
        self.assertIs(replay_inside_window["duplicate"], True)
        self.assertEqual(replay_inside_window["reply_message"], original_response["reply_message"])
        self.assertEqual(replay_inside_window["esp_sequence"], original_response["esp_sequence"])
        self.assertEqual(self.server.message_accepted_count, 8)

        for index in range(9, 17):
            self.client.send_message(build_message_frame(f"id{index}", index, f"message {index}"))
        self.assertEqual(len(self.server.message_cache), 8)
        self.assertNotIn("oldest", self.server.message_cache)
        replay_after_eviction = self.client.send_message(original).response
        self.assertEqual(replay_after_eviction["status"], "accepted")
        self.assertIs(replay_after_eviction["duplicate"], False)
        self.assertEqual(replay_after_eviction["esp_sequence"], 17)
        self.assertEqual(replay_after_eviction["reply_message"], original_response["reply_message"])
        self.assertEqual(self.server.message_accepted_count, 17)

    def test_manual_retry_uses_the_same_frame_after_unknown_delivery(self):
        frame = build_message_frame("manual-same-frame", 100, "unknown until retried")
        self.server.message_mode = "server_5xx"
        with self.assertRaises(EspApiError) as caught:
            self.client.send_message(frame)
        self.assertEqual(caught.exception.kind, "delivery_unknown")
        first_attempt_frames = list(self.server.message_frames)
        self.server.message_mode = "success"
        delivery = self.client.send_message(frame)  # UI's manual action reuses this exact immutable frame.
        self.assertEqual(self.server.message_frames, [*first_attempt_frames, frame.serialized])
        self.assertEqual(delivery.response["message_id"], frame.message_id)
        self.assertEqual(delivery.response["sequence"], frame.sequence)
        self.assertEqual(delivery.response["request_crc32"], frame.crc32)

    def test_esp_message_history_is_bounded_to_ten_entries(self):
        history = []
        for index in range(MAX_ESP_MESSAGE_HISTORY + 3):
            history = append_esp_message_history(history, {"sequence": index + 1})
        self.assertEqual(len(history), MAX_ESP_MESSAGE_HISTORY)
        self.assertEqual([item["sequence"] for item in history], list(range(4, 14)))

    def test_message_frame_validation_rejects_corrupt_serialized_bytes_before_network(self):
        frame = build_message_frame("immutable", 8, "fixed")
        corrupted = MessageFrame(frame.message_id, frame.sequence, frame.message, frame.crc32, frame.serialized + b" ")
        with self.assertRaisesRegex(ValueError, "do not match"):
            self.client.send_message(corrupted)
        self.assertEqual(self.server.message_frames, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
