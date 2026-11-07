from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import requests
from streamlit.testing.v1 import AppTest
from streamlit.runtime.state.safe_session_state import SafeSessionState

if not hasattr(SafeSessionState, "get"):
    SafeSessionState.get = lambda self, key, default=None: self[key] if key in self else default
SafeSessionState.keys = lambda self: self._state._keys()
if hasattr(SafeSessionState, "__iter__"):
    try:
        delattr(SafeSessionState, "__iter__")
    except Exception:
        pass

from aos_key_transfer_adapter import (
    AOS_PRIMARY_HEADER,
    AOS_SPI,
    build_baseline_aad,
    encode_aos_message_field,
)
from esp_api import EspApiClient, EspApiError

APP_PATH = Path(__file__).resolve().parents[1] / "communication_base_station.py"
PASSWORD = "AbCd_0123456789-" * 2
KEY = bytes(range(32))
MESSAGE = "Synthetic preview message"
IV = bytes.fromhex("00112233445566778899aabb")
BOOT_ID = "0123456789abcdef0123456789abcdef"
PROVISION_ID = "11111111111111111111111111111111"
FRESH_PROVISION_ID = "22222222222222222222222222222222"


def valid_downlink_payload(key: bytes = KEY, provision_id: str = PROVISION_ID) -> dict[str, str]:
    aad = build_baseline_aad(AOS_PRIMARY_HEADER, AOS_SPI)
    sealed = AESGCM(key).encrypt(IV, encode_aos_message_field(MESSAGE), aad)
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
    fields["boot_id"] = BOOT_ID
    fields["provision_id"] = provision_id
    return fields


class FakeResponse:
    def __init__(self, payload=None, status=200, content_type="application/json"):
        self.status_code = status
        self.headers = {"Content-Type": content_type}
        self._payload = payload

    def json(self):
        return self._payload


def gate_app() -> AppTest:
    return AppTest.from_file(str(APP_PATH)).run()


def fill_synthetic_gate_inputs(app: AppTest, *, ip="192.168.1.42", password=PASSWORD) -> None:
    # AppTest does not commit form widgets until submission; set their transient session values.
    app.session_state["esp_gate_ip"] = ip
    app.session_state["esp_gate_password"] = password


def visible_text(app: AppTest) -> str:
    return " ".join(
        str(item.value)
        for collection in (app.title, app.header, app.subheader, app.markdown, app.caption, app.code,
                           app.success, app.error, app.warning, app.info)
        for item in collection
    )


class CommunicationGateTests(unittest.TestCase):
    def setUp(self):
        self.telemetry_patcher = patch.object(
            EspApiClient, "get_telemetry", return_value={"boot_id": BOOT_ID, "provision_id": PROVISION_ID}
        )
        self.mock_telemetry = self.telemetry_patcher.start()
        self.addCleanup(self.telemetry_patcher.stop)

    def make_authenticated_app(self) -> AppTest:
        app = gate_app()
        fill_synthetic_gate_inputs(app)
        with patch(
            "aos_key_transfer_adapter.requests.post",
            return_value=FakeResponse(valid_downlink_payload()),
        ):
            app.button[0].click().run()
        self.assertTrue(app.session_state["esp_connection_authenticated"])
        app.radio[0].set_value("Demo-only pairing and AES-GCM").run()
        self.assertEqual(app.session_state["base_demo_downlink"].message_text, MESSAGE)
        self.assertEqual(app.session_state["esp_provision_id"], PROVISION_ID)
        return app

    def test_first_render_is_gate_only_and_makes_no_network_call(self):
        with patch("aos_key_transfer_adapter.requests.post") as post:
            app = gate_app()
        post.assert_not_called()
        self.assertEqual(len(app.exception), 0, [item.value for item in app.exception])
        self.assertEqual([item.value for item in app.title], ["Connect to ESP"])
        self.assertEqual([item.label for item in app.text_input], [
            "ESP Node API / URL (or IP address)", "ESP pairing password (not the AES key)"
        ])
        self.assertFalse(app.radio)
        self.assertEqual([item.label for item in app.button], ["Connect to ESP"])
        self.assertFalse(app.session_state.get("esp_connection_authenticated", False))
        self.assertIn("not secure authentication", visible_text(app).lower())
        self.assertIn("trusted, isolated LAN", visible_text(app))

    def test_success_sends_only_password_to_esp_and_opens_dashboard_after_gcm(self):
        app = gate_app()
        fill_synthetic_gate_inputs(app)
        with patch(
            "aos_key_transfer_adapter.requests.post",
            return_value=FakeResponse(valid_downlink_payload()),
        ) as post:
            app.button[0].click().run()
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "http://192.168.1.42/api/aos-demo/downlink")
        self.assertEqual(kwargs["json"], {"password": PASSWORD})
        self.assertEqual(set(kwargs["json"]), {"password"})
        self.assertFalse(kwargs["allow_redirects"])
        self.assertNotIn(PASSWORD, args[0])
        self.assertNotIn(KEY.hex(), args[0])
        self.assertNotIn("/api/aos-demo/provision", args[0])
        self.assertTrue(app.session_state["esp_connection_authenticated"])
        self.assertEqual(app.session_state["esp_boot_id"], BOOT_ID)
        self.assertEqual(app.session_state["esp_provision_id"], PROVISION_ID)
        self.assertEqual(app.session_state["esp_gate_password"], "")
        self.assertNotIn(PASSWORD, repr(dict(app.session_state)))
        self.assertIsNone(app.session_state.get("base_demo_aes_key"))
        app.radio[0].set_value("Demo-only pairing and AES-GCM").run()
        self.assertEqual([item.value for item in app.title], ["Communication / Base Station"])
        self.assertTrue(app.radio)
        verified = app.session_state["base_demo_downlink"]
        self.assertTrue(verified.tag_verified)
        self.assertTrue(verified.fixture_valid)
        self.assertEqual(verified.message_text, MESSAGE)
        page = visible_text(app)
        self.assertIn(MESSAGE, page)
        self.assertNotIn(PASSWORD, page)
        self.assertNotIn(KEY.hex(), page)
        self.assertIn("not secure authentication", page.lower())

    def test_wrong_password_stays_locked_clears_input_and_allows_retry(self):
        app = gate_app()
        fill_synthetic_gate_inputs(app)
        with patch(
            "aos_key_transfer_adapter.requests.post",
            side_effect=[
                FakeResponse({"error": "demo_pairing_rejected"}, status=403),
                FakeResponse(valid_downlink_payload()),
            ],
        ) as post:
            app.button[0].click().run()
            self.assertFalse(app.session_state.get("esp_connection_authenticated", False))
            self.assertEqual([item.value for item in app.title], ["Connect to ESP"])
            self.assertFalse(app.radio)
            self.assertEqual(app.session_state["esp_gate_password"], "")
            self.assertIn("rejected the pairing password", " ".join(item.value for item in app.error))
            self.assertNotIn(PASSWORD, visible_text(app))
            app.session_state["esp_gate_password"] = PASSWORD
            app.button[0].click().run()
        self.assertEqual(post.call_count, 2)
        self.assertTrue(app.session_state["esp_connection_authenticated"])
        self.assertEqual(app.session_state["esp_gate_password"], "")
        self.assertTrue(app.radio)

    def test_esp_reset_409_keeps_dashboard_inaccessible_until_fresh_provision(self):
        app = gate_app()
        fill_synthetic_gate_inputs(app)
        with patch(
            "aos_key_transfer_adapter.requests.post",
            return_value=FakeResponse({"error": "demo_provision_required"}, status=409),
        ) as post:
            app.button[0].click().run()
        post.assert_called_once()
        self.assertFalse(app.session_state.get("esp_connection_authenticated", False))
        self.assertFalse(app.radio)
        self.assertEqual(app.session_state["esp_gate_password"], "")
        self.assertIn("no current password/key/message provision in RAM", " ".join(item.value for item in app.error))
        self.assertIn("provision it to ESP", " ".join(item.value for item in app.error))
        self.assertNotIn(PASSWORD, visible_text(app))

    def test_no_route_or_network_error_stays_locked_and_shows_retryable_error(self):
        app = gate_app()
        fill_synthetic_gate_inputs(app)
        with patch("aos_key_transfer_adapter.requests.post", side_effect=requests.ConnectionError("secret detail")) as post:
            app.button[0].click().run()
        post.assert_called_once()
        self.assertFalse(app.session_state.get("esp_connection_authenticated", False))
        self.assertFalse(app.radio)
        self.assertEqual([item.label for item in app.button], ["Connect to ESP"])
        self.assertEqual(app.session_state["esp_gate_password"], "")
        self.assertIn("Could not reach ESP", " ".join(item.value for item in app.error))
        self.assertNotIn("secret detail", visible_text(app))
        self.assertNotIn(PASSWORD, visible_text(app))

    def test_invalid_url_or_public_target_is_rejected_before_any_esp_request(self):
        for ip in ("http://192.168.1.42", "192.168.1.42/api", "8.8.8.8", "127.0.0.1"):
            with self.subTest(ip=ip):
                app = gate_app()
                fill_synthetic_gate_inputs(app, ip=ip)
                with patch("aos_key_transfer_adapter.requests.post") as post:
                    app.button[0].click().run()
                post.assert_not_called()
                self.assertFalse(app.session_state.get("esp_connection_authenticated", False))
                self.assertFalse(app.radio)
                self.assertNotIn(PASSWORD, visible_text(app))

    def test_wrong_key_or_tampered_frame_fails_closed_before_dashboard(self):
        for mode in ("wrong_key", "tampered_frame"):
            with self.subTest(mode=mode):
                payload = valid_downlink_payload()
                if mode == "wrong_key":
                    payload["key_hex"] = bytes(reversed(KEY)).hex()
                else:
                    payload["ciphertext_hex"] = ("00" if payload["ciphertext_hex"][:2] != "00" else "01") + payload["ciphertext_hex"][2:]
                    payload["frame_hex"] = "".join(payload[name] for name in (
                        "primary_header_hex", "security_header_hex", "ciphertext_hex", "tag_hex"
                    ))
                app = gate_app()
                fill_synthetic_gate_inputs(app)
                with patch("aos_key_transfer_adapter.requests.post", return_value=FakeResponse(payload)) as post:
                    app.button[0].click().run()
                post.assert_called_once()
                self.assertFalse(app.session_state.get("esp_connection_authenticated", False))
                self.assertFalse(app.radio)
                self.assertIn("AES-GCM and message validation", " ".join(item.value for item in app.error))
                self.assertNotIn(MESSAGE, visible_text(app))
                self.assertNotIn(PASSWORD, visible_text(app))

    def test_communication_page_has_no_provisioning_or_site_to_site_call(self):
        source = APP_PATH.read_text(encoding="utf-8")
        adapter_source = (APP_PATH.parent / "aos_key_transfer_adapter.py").read_text(encoding="utf-8")
        self.assertIn("/api/aos-demo/downlink", adapter_source)
        self.assertNotIn("/api/aos-demo/provision", source)
        self.assertNotIn("requests.post", source)
        self.assertNotIn("http://127.0.0.1:850", source)
        self.assertIn("fetch_downlink(origin, password)", source)
        self.assertIn("type=\"password\"", source)
        self.assertIn("finally:", source)

    def test_boot_id_change_relocks_and_clears_frame_plaintext_and_cached_telemetry(self):
        app = self.make_authenticated_app()
        self.mock_telemetry.return_value = {
            "boot_id": "fedcba9876543210fedcba9876543210", "provision_id": PROVISION_ID
        }

        app.radio[0].set_value("ESP telemetry and gates").run()

        self.assertFalse(app.session_state.get("esp_connection_authenticated", False))
        self.assertEqual([item.value for item in app.title], ["Connect to ESP"])
        self.assertFalse(app.radio)
        self.assertIsNone(app.session_state.get("base_demo_downlink"))
        self.assertIsNone(app.session_state.get("telemetry"))
        self.assertIsNone(app.session_state.get("esp_boot_id"))
        self.assertEqual(app.session_state.get("esp_base_origin"), "")
        self.assertIn("boot or provision session changed", " ".join(item.value for item in app.error).lower())
        self.assertNotIn(MESSAGE, visible_text(app))
        self.assertNotIn(KEY.hex(), repr(dict(app.session_state)))

    def test_id_mismatch_relocks_and_keeps_old_provision_id_rejected(self):
        mismatch_telemetry = (
            {"boot_id": "fedcba9876543210fedcba9876543210", "provision_id": PROVISION_ID},
            {"boot_id": BOOT_ID, "provision_id": FRESH_PROVISION_ID},
        )
        for telemetry in mismatch_telemetry:
            with self.subTest(telemetry=telemetry):
                self.mock_telemetry.return_value = {"boot_id": BOOT_ID, "provision_id": PROVISION_ID}
                app = self.make_authenticated_app()
                self.mock_telemetry.return_value = telemetry
                app.radio[0].set_value("ESP telemetry and gates").run()

                self.assertFalse(app.session_state.get("esp_connection_authenticated", False))
                self.assertIsNone(app.session_state.get("base_demo_downlink"))
                self.assertEqual(app.session_state.get("esp_required_new_provision_id"), PROVISION_ID)

                fill_synthetic_gate_inputs(app)
                with patch(
                    "aos_key_transfer_adapter.requests.post",
                    return_value=FakeResponse(valid_downlink_payload(provision_id=PROVISION_ID)),
                ) as post:
                    app.button[0].click().run()
                post.assert_called_once()
                self.assertFalse(app.session_state.get("esp_connection_authenticated", False))
                self.assertEqual(app.session_state.get("esp_required_new_provision_id"), PROVISION_ID)
                self.assertIn("previous RAM provision", " ".join(item.value for item in app.error))

    def test_network_failure_relocks_and_clears_decoded_aos_state(self):
        app = self.make_authenticated_app()
        self.mock_telemetry.side_effect = EspApiError("disconnected", "synthetic network outage")

        app.radio[0].set_value("ESP telemetry and gates").run()

        self.assertFalse(app.session_state.get("esp_connection_authenticated", False))
        self.assertEqual([item.value for item in app.title], ["Connect to ESP"])
        self.assertFalse(app.radio)
        self.assertIsNone(app.session_state.get("base_demo_downlink"))
        self.assertIsNone(app.session_state.get("telemetry"))
        self.assertEqual(app.session_state.get("esp_required_new_provision_id"), PROVISION_ID)
        self.assertIn("revalidate the esp session", " ".join(item.value for item in app.error).lower())
        self.assertNotIn("synthetic network outage", visible_text(app))
        self.assertNotIn(MESSAGE, visible_text(app))

    def test_network_failure_blocks_old_provision_until_key_generator_provisions_fresh_material(self):
        app = self.make_authenticated_app()
        self.mock_telemetry.side_effect = EspApiError("disconnected", "synthetic network outage")
        app.radio[0].set_value("ESP telemetry and gates").run()
        self.assertEqual(app.session_state.get("esp_required_new_provision_id"), PROVISION_ID)

        self.mock_telemetry.side_effect = None
        self.mock_telemetry.return_value = {"boot_id": BOOT_ID, "provision_id": PROVISION_ID}
        fill_synthetic_gate_inputs(app, password=PASSWORD)
        with patch(
            "aos_key_transfer_adapter.requests.post", return_value=FakeResponse(valid_downlink_payload())
        ) as post:
            app.button[0].click().run()
        post.assert_called_once()
        self.assertFalse(app.session_state.get("esp_connection_authenticated", False))
        self.assertIn("previous RAM provision", " ".join(item.value for item in app.error))
        self.assertEqual(app.session_state.get("esp_required_new_provision_id"), PROVISION_ID)

        fresh_password = PASSWORD.replace("AbCd", "ZxYw")
        self.mock_telemetry.return_value = {"boot_id": BOOT_ID, "provision_id": FRESH_PROVISION_ID}
        fill_synthetic_gate_inputs(app, password=fresh_password)
        with patch(
            "aos_key_transfer_adapter.requests.post",
            return_value=FakeResponse(valid_downlink_payload(key=bytes(reversed(KEY)), provision_id=FRESH_PROVISION_ID)),
        ) as fresh_post:
            app.button[0].click().run()
        fresh_post.assert_called_once()
        self.assertTrue(app.session_state["esp_connection_authenticated"])
        self.assertEqual(app.session_state["esp_provision_id"], FRESH_PROVISION_ID)
        self.assertIsNone(app.session_state.get("esp_required_new_provision_id"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
