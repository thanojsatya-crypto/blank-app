from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import os_csprng_key
from os_csprng_key import KEY_BITS, KEY_BYTES, generate_os_csprng_key
from os_csprng_key_ui import (
    OS_CSPRNG_KEY_STATE,
    OS_CSPRNG_MODE_LABEL,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_DIR / "key_generator.py"


class OsCSPRngKeyUnitTests(unittest.TestCase):
    def test_requests_exactly_32_bytes_from_secrets_and_returns_them_unchanged(self):
        expected = bytes(range(KEY_BYTES))
        with patch("os_csprng_key.secrets.token_bytes", return_value=expected) as token_bytes:
            key = generate_os_csprng_key()

        token_bytes.assert_called_once_with(32)
        self.assertEqual(KEY_BITS, 256)
        self.assertIs(key, expected)
        self.assertEqual(len(key), KEY_BYTES)
        self.assertEqual(key.hex(), expected.hex())

    def test_rejects_unexpected_provider_result(self):
        for invalid in (b"short", bytearray(KEY_BYTES)):
            with self.subTest(invalid_type=type(invalid).__name__), patch(
                "os_csprng_key.secrets.token_bytes", return_value=invalid
            ), self.assertRaises(RuntimeError):
                generate_os_csprng_key()

    def test_generator_uses_secrets_only_and_has_no_custom_random_or_io_path(self):
        source = inspect.getsource(os_csprng_key)
        tree = ast.parse(source)
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertIn("secrets", imported)
        self.assertNotIn("random", imported)
        for forbidden in ("requests.", "urllib.request", "open(", "Path(", "print(", "logging."):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class OsCSPRngKeyAppTests(unittest.TestCase):
    def make_app(self) -> AppTest:
        app = AppTest.from_file(str(APP_PATH))
        app.run()
        return app

    def select_mode(self, app: AppTest) -> None:
        mode_radio = next(widget for widget in app.radio if widget.label == "Key Generator mode")
        mode_radio.set_value(OS_CSPRNG_MODE_LABEL).run()

    def test_mode_is_additive_and_does_not_generate_until_clicked(self):
        app = self.make_app()
        mode_radio = next(widget for widget in app.radio if widget.label == "Key Generator mode")
        self.assertEqual(mode_radio.value, "BB84 simulator")
        self.assertIn(OS_CSPRNG_MODE_LABEL, mode_radio.options)
        self.assertIsNone(app.session_state[OS_CSPRNG_KEY_STATE])

        self.select_mode(app)
        self.assertEqual(len(app.exception), 0, [item.value for item in app.exception])
        self.assertIsNone(app.session_state[OS_CSPRNG_KEY_STATE])
        self.assertIn("OS CSPRNG/DRBG pseudorandom output", " ".join(item.value for item in app.warning))
        self.assertIn("not true randomness", " ".join(item.value for item in app.warning))
        self.assertIn("no AOS provisioning path", " ".join(item.value for item in app.info))

    def test_generation_displays_exactly_the_returned_32_bytes_as_hex(self):
        expected = bytes(range(KEY_BYTES))
        with patch("os_csprng_key_ui.generate_os_csprng_key", return_value=expected) as generate:
            app = self.make_app()
            self.select_mode(app)
            next(button for button in app.button if button.label == "Generate 256-bit OS-CSPRNG key").click().run()

        generate.assert_called_once_with()
        self.assertEqual(len(app.exception), 0, [item.value for item in app.exception])
        self.assertEqual(app.session_state[OS_CSPRNG_KEY_STATE], expected)
        self.assertEqual([item.value for item in app.code], [expected.hex()])
        self.assertIn("Generated one 256-bit OS-CSPRNG key.", " ".join(item.value for item in app.success))

    def test_clear_removes_key_from_session_and_output(self):
        expected = bytes(range(KEY_BYTES))
        with patch("os_csprng_key_ui.generate_os_csprng_key", return_value=expected):
            app = self.make_app()
            self.select_mode(app)
            next(button for button in app.button if button.label == "Generate 256-bit OS-CSPRNG key").click().run()
            next(button for button in app.button if button.label == "Clear OS-CSPRNG key").click().run()

        self.assertIsNone(app.session_state[OS_CSPRNG_KEY_STATE])
        self.assertEqual(app.code, [])

    def test_failure_discards_old_key_and_does_not_expose_provider_exception(self):
        expected = bytes(range(KEY_BYTES))
        with patch(
            "os_csprng_key_ui.generate_os_csprng_key",
            side_effect=[expected, RuntimeError("private provider detail")],
        ):
            app = self.make_app()
            self.select_mode(app)
            next(button for button in app.button if button.label == "Generate 256-bit OS-CSPRNG key").click().run()
            next(button for button in app.button if button.label == "Generate 256-bit OS-CSPRNG key").click().run()

        self.assertIsNone(app.session_state[OS_CSPRNG_KEY_STATE])
        self.assertEqual(app.code, [])
        errors = " ".join(item.value for item in app.error)
        self.assertIn("Key generation failed", errors)
        self.assertNotIn("private provider detail", errors)

    def test_ui_module_has_no_api_client_or_transfer_adapter(self):
        source = inspect.getsource(__import__("os_csprng_key_ui"))
        self.assertNotIn("EspApiClient", source)
        self.assertNotIn("AOSKeyTransferAdapter", source)
        self.assertNotIn("requests.", source)
        self.assertNotIn("urllib.request", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
