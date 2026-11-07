from __future__ import annotations

import inspect
import re
import unittest
from pathlib import Path

import demo_crypto
import esp_api
import local_exchange
import qkd_simulator
import simulation_trigger_client
from aos_key_transfer_adapter import normalize_private_rfc1918_http_origin
from pairing_config import generate_pairing_password, validate_pairing_password
from qkd_simulator import SIMULATED_LABEL
from esp_api import normalize_base_url

ROOT = Path(__file__).resolve().parents[1]


class SecurityBoundaryTests(unittest.TestCase):
    def test_ordinary_esp_target_validation_remains_strict(self):
        for url in ("http://127.0.0.1", "http://192.168.1.42", "http://10.0.0.8:8080", "http://172.31.2.3"):
            with self.subTest(url=url):
                self.assertTrue(normalize_base_url(url).startswith("http://"))
        for url in (
            "https://192.168.1.42", "http://8.8.8.8", "http://169.254.1.2", "http://224.0.0.1",
            "http://esp32.local", "http://192.168.1.42/api/telemetry", "http://192.168.1.42/?key=simulated",
            "http://user:password@192.168.1.42", "http://[::1]",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_base_url(url)
        for url in ("http://192.168.1.42", "http://10.0.0.8:8080", "http://172.31.2.3"):
            self.assertTrue(normalize_private_rfc1918_http_origin(url).startswith("http://"))
        for url in ("http://127.0.0.1", "http://esp32.local", "https://192.168.1.42"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_private_rfc1918_http_origin(url)

    def test_crypto_and_simulator_modules_have_no_network_or_persistence_helpers(self):
        for module in (demo_crypto, qkd_simulator):
            source = inspect.getsource(module)
            for forbidden in ("requests.", "urllib.request", "logging.", "open(", "Path(", "print("):
                with self.subTest(module=module.__name__, forbidden=forbidden):
                    self.assertNotIn(forbidden, source)

    def test_esp_client_and_ordinary_message_contract_have_no_aos_key_arguments(self):
        self.assertEqual(tuple(inspect.signature(esp_api.EspApiClient.set_chain).parameters), ("self", "chain"))
        self.assertEqual(tuple(inspect.signature(esp_api.EspApiClient.get_telemetry).parameters), ("self",))
        self.assertEqual(tuple(inspect.signature(esp_api.EspApiClient.send_message).parameters), ("self", "frame"))
        self.assertNotIn("simulated_bits", inspect.signature(esp_api.EspApiClient.set_chain).parameters)
        self.assertNotIn("pairing_pin", inspect.signature(esp_api.EspApiClient.set_chain).parameters)
        esp_source = inspect.getsource(esp_api)
        self.assertNotIn("AOSKeyTransferAdapter", esp_source)
        self.assertNotIn("aos_key_demo", esp_source)
        self.assertIn("/api/message", esp_source)

    def test_key_generator_alone_invokes_provision_and_base_station_only_downlinks(self):
        generator_source = (ROOT / "aos_key_demo_ui.py").read_text(encoding="utf-8")
        base_source = (ROOT / "communication_base_station.py").read_text(encoding="utf-8")
        self.assertIn("AOSKeyTransferAdapter().provision", generator_source)
        self.assertNotIn("AOSKeyTransferAdapter().provision", base_source)
        self.assertNotIn("/api/aos-demo/provision", base_source)
        self.assertIn("fetch_downlink", base_source)
        self.assertIn('json={"password": password}', (ROOT / "aos_key_transfer_adapter.py").read_text(encoding="utf-8"))
        self.assertIn("not a website login", base_source.lower())
        self.assertNotIn("DEMO-ONLY-PAIRING", generator_source + base_source)
        self.assertNotIn("http://127.0.0.1:850", base_source + generator_source)

    def test_pairing_password_is_fresh_fixed_length_url_safe_and_not_a_fixture_default(self):
        first = generate_pairing_password()
        second = generate_pairing_password()
        self.assertEqual(len(first), 32)
        self.assertNotEqual(first, second)
        self.assertTrue(validate_pairing_password(first))
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]{32}", first))
        self.assertFalse(validate_pairing_password("DEMO-ONLY-PAIRING"))
        source = (ROOT / "pairing_config.py").read_text(encoding="utf-8")
        self.assertIn("secrets.token_urlsafe", source)

    def test_firmware_registers_only_new_aos_routes_and_no_storage_or_logging_path(self):
        source = (ROOT / "firmware/esp32-qkd-teaching-aos-demo.cpp").read_text(encoding="utf-8")
        expected_routes = (
            'server.on("/api/aos-demo/provision", HTTP_POST, handlePostAosDemoProvision);',
            'server.on("/api/aos-demo/downlink", HTTP_POST, handlePostAosDemoDownlink);',
        )
        for route in expected_routes:
            self.assertIn(route, source)
        for removed in (
            "/api/pair", "/api/demo-key", "/api/aos-demo/encrypt", "/api/aos-demo/telemetry",
            "DEMO-ONLY-PAIRING", "Preferences", "EEPROM", "Serial.", "Serial.", "log(",
        ):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, source)
        self.assertIn("secureWipe(demoPairingPassword", source)
        self.assertIn("secureWipe(demoKey", source)
        self.assertIn("secureWipe(demoAosDataField", source)
        self.assertIn("clearDemoProvisioningRam();", source)
        self.assertIn("demoProvisioned = true", source)
        self.assertIn("response[\"key_hex\"]", source)
        self.assertLess(source.index("if (!matchesDemoPairingPassword"), source.index("encryptAndRespondAosFrame(aos_demo_profile::kRequiredPrimaryHeader"))

    def test_user_message_is_explicitly_length_prefixed_and_never_silently_truncated(self):
        source = (ROOT / "firmware/esp32-qkd-teaching-aos-demo.cpp").read_text(encoding="utf-8")
        self.assertIn("messageLength > DEMO_AOS_DATA_BYTES - 1", source)
        self.assertIn("candidateDataField[0] = static_cast<uint8_t>(messageLength)", source)
        self.assertIn("memcpy(candidateDataField + 1, messageBytes, messageLength)", source)
        self.assertIn("message_exceeds_31_utf8_octets_no_truncation", source)
        self.assertNotIn("kRequiredFrameData", source)

    def test_local_echo_and_trigger_boundaries_remain_separate(self):
        message_log = local_exchange.append_local_message([], "LOCAL_MESSAGE_CANARY")
        self.assertEqual(message_log[0]["sent_message"], "LOCAL_MESSAGE_CANARY")
        self.assertIn("Sent (local simulation)", local_exchange.SENT_STATUS)
        self.assertIn("Received (local simulation)", local_exchange.RECEIVED_STATUS)
        exchange_source = inspect.getsource(local_exchange)
        for forbidden in ("requests.", "urllib.request", "open(", "logging."):
            self.assertNotIn(forbidden, exchange_source)
        source = inspect.getsource(simulation_trigger_client)
        for forbidden in ("requests.post", "requests.put", "requests.patch", "simulated_bits", "pairing_pin", "open(", "print("):
            self.assertNotIn(forbidden, source)
        self.assertIn('TRIGGER_PATH = "/api/simulation-trigger"', source)
        self.assertIn("allow_redirects=False", source)

    def test_key_generator_keeps_simulation_disclosure(self):
        source = (ROOT / "key_generator.py").read_text(encoding="utf-8")
        self.assertEqual(SIMULATED_LABEL, "simulated quantum measurement—not a real QRNG/QKD")
        self.assertIn("st.warning(SIMULATED_LABEL)", source)
        self.assertIn("No quantum channel exists", source)
        self.assertNotIn("EspApiClient", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
