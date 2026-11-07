from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from aos_key_transfer_adapter import AOS_PRIMARY_HEADER, AOS_SPI, build_baseline_aad, encode_aos_message_field
from esp_api import EspApiClient, EspApiError, MessageDelivery
from streamlit.testing.v1 import AppTest

APP_PATH = Path(__file__).resolve().parents[1] / "communication_base_station.py"
PASSWORD = "P4ss_" * 6 + "xy"
KEY = bytes(range(32))
MESSAGE = "Hello from ESP 🌍"
IV = bytes.fromhex("00112233445566778899aabb")
BOOT_ID = "0123456789abcdef0123456789abcdef"
PROVISION_ID = "11111111111111111111111111111111"


def accepted_response(frame, *, status="accepted", esp_sequence=3):
    return {
        "device": "esp32-qkd-teaching",
        "message_id": frame.message_id,
        "sequence": frame.sequence,
        "ack": True,
        "status": status,
        "esp_sequence": esp_sequence,
        "received_message": frame.message,
        "reply_message": "ESP32 received: " + frame.message,
        "request_crc32": frame.crc32,
        "computed_crc32": frame.crc32,
        "integrity": "valid",
        "duplicate": status == "duplicate",
    }


def aos_downlink_payload(message=MESSAGE, key=KEY):
    aad = build_baseline_aad(AOS_PRIMARY_HEADER, AOS_SPI)
    sealed = AESGCM(key).encrypt(IV, encode_aos_message_field(message), aad)
    security = AOS_SPI.to_bytes(2, "big") + IV
    frame = AOS_PRIMARY_HEADER + security + sealed
    return {
        "primary_header_hex": AOS_PRIMARY_HEADER.hex(),
        "security_header_hex": security.hex(),
        "ciphertext_hex": sealed[:-16].hex(),
        "tag_hex": sealed[-16:].hex(),
        "frame_hex": frame.hex(),
        "key_hex": key.hex(),
        "boot_id": BOOT_ID,
        "provision_id": PROVISION_ID,
    }


def response(payload=None, status=200):
    class FakeResponse:
        status_code = status
        headers = {"Content-Type": "application/json"}

        def json(self):
            return payload
    return FakeResponse()


class CommunicationBaseStationAppTests(unittest.TestCase):
    def setUp(self):
        self.telemetry_patcher = patch.object(
            EspApiClient, "get_telemetry", return_value={"boot_id": BOOT_ID, "provision_id": PROVISION_ID}
        )
        self.telemetry_patcher.start()
        self.addCleanup(self.telemetry_patcher.stop)

    def make_app(self, section="ESP telemetry and gates"):
        app = AppTest.from_file(str(APP_PATH)).run()
        app.session_state["esp_gate_ip"] = "192.168.1.42"
        app.session_state["esp_gate_password"] = PASSWORD
        with patch(
            "aos_key_transfer_adapter.requests.post",
            return_value=response(aos_downlink_payload()),
        ):
            app.button[0].click().run()
        self.assertEqual(len(app.exception), 0, [item.value for item in app.exception])
        self.assertTrue(app.session_state["esp_connection_authenticated"])
        self.assertEqual(app.session_state["esp_gate_password"], "")
        if section != "ESP telemetry and gates":
            app.radio[0].set_value(section).run()
        self.assertEqual(len(app.exception), 0, [item.value for item in app.exception])
        return app

    def test_sidebar_navigation_keeps_the_five_existing_sections_and_default_is_read_only(self):
        with patch.object(
            EspApiClient, "get_telemetry", return_value={"boot_id": BOOT_ID, "provision_id": PROVISION_ID}
        ) as get_telemetry:
            app = self.make_app()
        self.assertEqual(app.radio[0].options, [
            "ESP telemetry and gates", "Real ESP message send", "Local send/receive demo",
            "Demo-only pairing and AES-GCM", "CCSDS learning simulation",
        ])
        get_telemetry.assert_called_once_with()

    def test_manual_retry_displays_unknown_then_uses_same_frame_and_esp_ack(self):
        timeout = EspApiError("delivery_unknown", "Delivery unknown after timeout; use manual retry with the same frame.",
                              attempts=({"attempt": 1, "status": "timeout"},))
        frame_box = []

        def send_side_effect(frame):
            frame_box.append(frame)
            if len(frame_box) == 1:
                raise timeout
            return MessageDelivery(accepted_response(frame, status="duplicate", esp_sequence=3),
                                   ({"attempt": 1, "status": "ESP ACK received", "http_status": 200},))

        with patch.object(EspApiClient, "send_message", side_effect=send_side_effect) as send:
            app = self.make_app("Real ESP message send")
            next(item for item in app.text_area if item.label.startswith("Text to send")).set_value("retry same frame").run()
            next(item for item in app.button if item.label == "Send message to ESP32").click().run()
            history = app.session_state["esp_message_history"]
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["send_status"], "delivery unknown")
            saved_frame = history[0]["frame"]
            self.assertIn("delivery unknown", " ".join(item.value for item in app.warning).lower())
            next(item for item in app.button if item.label == "Manual retry with the same frame").click().run()
        self.assertEqual(send.call_count, 2)
        self.assertEqual(frame_box[0].serialized, frame_box[1].serialized)
        self.assertEqual(frame_box[0], frame_box[1])
        self.assertEqual(history[0]["frame"], saved_frame)
        self.assertEqual(history[0]["send_status"], "ESP ACK received — duplicate")
        self.assertEqual(history[0]["response"]["ack"], True)
        self.assertEqual(history[0]["response"]["esp_sequence"], 3)
        self.assertEqual(history[0]["response"]["reply_message"], "ESP32 received: retry same frame")
        self.assertEqual(len(history[0]["attempts"]), 2)

    def test_unsent_message_draft_survives_navigation_without_sending(self):
        with patch.object(EspApiClient, "send_message") as send:
            app = self.make_app("Real ESP message send")
            draft = "draft stays local until explicit send"
            next(item for item in app.text_area if item.label.startswith("Text to send")).set_value(draft).run()
            self.assertEqual(app.session_state["esp_message_draft"], draft)
            app.radio[0].set_value("Local send/receive demo").run()
            self.assertNotIn("esp_message_input", app.session_state)
            app.radio[0].set_value("Real ESP message send").run()
            restored = next(item for item in app.text_area if item.label.startswith("Text to send"))
            self.assertEqual(restored.value, draft)
            self.assertEqual(app.session_state["esp_message_draft"], draft)
            self.assertEqual(app.session_state["esp_message_history"], [])
            send.assert_not_called()

    def test_local_echo_button_never_calls_real_esp_message_client(self):
        with patch.object(EspApiClient, "send_message") as send:
            app = self.make_app("Local send/receive demo")
            next(item for item in app.text_input if item.label == "Short local demo message").set_value("LOCAL_ONLY_CANARY").run()
            next(item for item in app.button if item.label == "Send and receive locally").click().run()
            self.assertEqual(app.session_state["local_exchange_log"][0]["sent_message"], "LOCAL_ONLY_CANARY")
            self.assertEqual(app.session_state["local_exchange_log"][0]["received_message"], "LOCAL_ONLY_CANARY")
            send.assert_not_called()

    def test_authenticated_aos_view_shows_verified_message_without_password_or_key(self):
        app = self.make_app("Demo-only pairing and AES-GCM")
        verification = app.session_state["base_demo_downlink"]
        self.assertTrue(verification.tag_verified)
        self.assertTrue(verification.fixture_valid)
        self.assertEqual(verification.message_text, MESSAGE)
        visible = " ".join(
            str(item.value)
            for collection in (app.markdown, app.caption, app.code, app.success, app.error)
            for item in collection
        )
        self.assertIn(MESSAGE, visible)
        self.assertIn("PASS", visible)
        self.assertNotIn(KEY.hex(), visible)
        self.assertNotIn(PASSWORD, visible)
        self.assertFalse(any("pairing password" in item.label.lower() for item in app.text_input))


if __name__ == "__main__":
    unittest.main(verbosity=2)
