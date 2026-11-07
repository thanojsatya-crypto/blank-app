from __future__ import annotations

import unittest

from aos_device_model import AOSDeviceError, VolatileAOSDevice
from aos_downlink import verify_firmware_telemetry
from aos_key_transfer_adapter import encode_aos_message_field
from pairing_config import generate_pairing_password, validate_pairing_password


PASSWORD = "A" * 32
OTHER_PASSWORD = "B" * 32
KEY = bytes(range(32))
OTHER_KEY = bytes(reversed(range(32)))


class VolatileProvisioningTests(unittest.TestCase):
    def make_device(self) -> VolatileAOSDevice:
        prefixes = iter((b"12345678", b"abcdefgh"))
        return VolatileAOSDevice(random_bytes=lambda size: next(prefixes))

    def test_pairing_password_is_independent_os_csprng_material(self):
        first = generate_pairing_password()
        second = generate_pairing_password()
        self.assertEqual(len(first), 32)
        self.assertTrue(validate_pairing_password(first))
        self.assertTrue(validate_pairing_password(second))
        self.assertNotEqual(first, second)
        self.assertFalse(validate_pairing_password("DEMO-ONLY-PAIRING"))
        self.assertFalse(validate_pairing_password("x" * 31))

    def test_fresh_provision_message_round_trip_and_password_only_downlink(self):
        device = self.make_device()
        message = "Hello 🌍"
        receipt = device.provision(PASSWORD, KEY, message)
        self.assertEqual(receipt, {"accepted": True, "provisioned": True})
        response = device.downlink(PASSWORD)
        self.assertEqual(set(response), {
            "primary_header_hex", "security_header_hex", "ciphertext_hex", "tag_hex", "frame_hex", "key_hex",
            "boot_id", "provision_id",
        })
        self.assertRegex(response["boot_id"], r"\A[0-9a-f]{32}\Z")
        self.assertRegex(response["provision_id"], r"\A[0-9a-f]{32}\Z")
        self.assertEqual(response["key_hex"], KEY.hex())
        verified = verify_firmware_telemetry(response)
        self.assertTrue(verified.tag_verified)
        self.assertTrue(verified.fixture_valid)
        self.assertEqual(verified.message_text, message)
        self.assertEqual(verified.plaintext, encode_aos_message_field(message))
        self.assertEqual(len(bytes.fromhex(verified.frame.frame_hex)), 68)

    def test_wrong_pairing_password_is_rejected_before_downlink(self):
        device = self.make_device()
        device.provision(PASSWORD, KEY, "not sent in request")
        with self.assertRaises(AOSDeviceError) as caught:
            device.downlink(OTHER_PASSWORD)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.code, "demo_pairing_rejected")

    def test_hardware_reset_or_reboot_clears_password_key_and_message_and_stale_session_fails(self):
        device = self.make_device()
        device.provision(PASSWORD, KEY, "volatile only")
        self.assertTrue(device.has_provision)
        previous_session = device.downlink(PASSWORD)
        device.reset_or_reboot()
        self.assertFalse(device.has_provision)
        self.assertNotEqual(device._boot_id, previous_session["boot_id"])
        self.assertIsNone(device._provision_id)
        self.assertEqual(device._password, bytearray())
        self.assertEqual(device._key, bytearray(32))
        self.assertEqual(device._data_field, bytearray(32))
        with self.assertRaises(AOSDeviceError) as caught:
            device.downlink(PASSWORD)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.code, "demo_provision_required")

    def test_fresh_password_and_key_are_required_to_reprovision_after_reset(self):
        device = self.make_device()
        device.provision(PASSWORD, KEY, "old session")
        previous_provision_id = device.downlink(PASSWORD)["provision_id"]
        device.reset_or_reboot()
        device.provision(OTHER_PASSWORD, OTHER_KEY, "new session")
        response = device.downlink(OTHER_PASSWORD)
        self.assertNotEqual(response["provision_id"], previous_provision_id)
        self.assertEqual(response["key_hex"], OTHER_KEY.hex())
        self.assertEqual(verify_firmware_telemetry(response).message_text, "new session")
        with self.assertRaises(AOSDeviceError) as caught:
            device.downlink(PASSWORD)
        self.assertEqual(caught.exception.status_code, 403)

    def test_changed_returned_key_or_tampered_frame_never_releases_plaintext(self):
        device = self.make_device()
        device.provision(PASSWORD, KEY, "verify before release")
        valid = device.downlink(PASSWORD)
        wrong_key = dict(valid)
        wrong_key["key_hex"] = OTHER_KEY.hex()
        result = verify_firmware_telemetry(wrong_key)
        self.assertFalse(result.tag_verified)
        self.assertIsNone(result.plaintext)
        self.assertIsNone(result.message_text)

        tampered = dict(valid)
        tampered["ciphertext_hex"] = ("00" if tampered["ciphertext_hex"][:2] != "00" else "01") + tampered["ciphertext_hex"][2:]
        tampered["frame_hex"] = "".join(tampered[name] for name in (
            "primary_header_hex", "security_header_hex", "ciphertext_hex", "tag_hex"
        ))
        result = verify_firmware_telemetry(tampered)
        self.assertFalse(result.tag_verified)
        self.assertIsNone(result.plaintext)
        self.assertIsNone(result.message_text)

    def test_oversize_utf8_message_is_rejected_without_truncation_or_replacing_existing_provision(self):
        device = self.make_device()
        device.provision(PASSWORD, KEY, "keep current")
        with self.assertRaises(AOSDeviceError) as caught:
            device.provision(OTHER_PASSWORD, OTHER_KEY, "é" * 16)
        self.assertEqual(caught.exception.status_code, 422)
        result = verify_firmware_telemetry(device.downlink(PASSWORD))
        self.assertEqual(result.message_text, "keep current")


if __name__ == "__main__":
    unittest.main(verbosity=2)
