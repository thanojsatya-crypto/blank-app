from __future__ import annotations

import inspect
import unittest

from demo_crypto import (
    decrypt_demo_message,
    derive_demo_message_key,
    encrypt_demo_message,
    generate_demo_pairing_pin,
    validate_simulated_bits,
)


class DemoCryptoTests(unittest.TestCase):
    def test_pin_is_demo_only_six_digits_and_not_an_encryption_argument(self):
        pin = generate_demo_pairing_pin()
        self.assertRegex(pin, r"^\d{6}$")
        self.assertNotIn("pin", inspect.signature(derive_demo_message_key).parameters)
        self.assertNotIn("pin", inspect.signature(encrypt_demo_message).parameters)
        self.assertNotIn("pin", inspect.signature(decrypt_demo_message).parameters)

    def test_distinct_message_key_context_is_derived_only_from_simulated_bits(self):
        bits = "01011010100101101010110100101101"
        key_before_pin = derive_demo_message_key(bits)
        _pin = generate_demo_pairing_pin()
        key_after_pin = derive_demo_message_key(bits)
        self.assertEqual(key_before_pin, key_after_pin)
        self.assertEqual(len(key_before_pin), 32)
        self.assertNotEqual(key_before_pin, derive_demo_message_key("1" + bits[1:]))

    def test_transient_demo_aes_gcm_round_trip_and_authentication(self):
        bits = "00110101011010100101101011001010"
        encrypted = encrypt_demo_message(bits, "hello teaching demo")
        self.assertEqual(set(encrypted), {"nonce_b64", "ciphertext_b64"})
        self.assertEqual(decrypt_demo_message(bits, **encrypted), "hello teaching demo")
        with self.assertRaisesRegex(ValueError, "decryption failed"):
            decrypt_demo_message("1" + bits[1:], **encrypted)

    def test_only_simulated_bits_are_accepted(self):
        self.assertEqual(validate_simulated_bits(" 0101 1010 0101 1010 "), "0101101001011010")
        for value in ("0101", "0123456789012345", "not a key value at all", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_simulated_bits(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
