from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[1]
SKETCH_DIR = ROOT / "arduino" / "esp32-qkd-teaching-aos-demo"
SPI = 0x1234
PRIMARY_HEADER = bytes.fromhex("69521234564a")
AAD = bytes.fromhex("0012000000001234000000000000000000000000")
KEY = bytes(range(32))
IV = bytes.fromhex("00112233445566778899aabb")


def encode_message_field(message: str) -> bytes:
    encoded = message.encode("utf-8", errors="strict")
    if not 1 <= len(encoded) <= 31:
        raise ValueError("message must fit in 31 UTF-8 octets")
    return bytes([len(encoded)]) + encoded + bytes(31 - len(encoded))


class AOSFrameContractTests(unittest.TestCase):
    def test_message_encoding_uses_exact_utf8_octet_length_and_rejects_oversize(self):
        message = "Hello 🌍"
        field = encode_message_field(message)
        encoded = message.encode("utf-8")
        self.assertEqual(len(field), 32)
        self.assertEqual(field[0], len(encoded))
        self.assertEqual(field[1:1 + len(encoded)], encoded)
        self.assertEqual(field[1 + len(encoded):], bytes(31 - len(encoded)))
        self.assertEqual(encode_message_field("é" * 15)[0], 30)
        for invalid in ("", "A" * 32, "é" * 16):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                encode_message_field(invalid)

    def test_selected_profile_gcm_frame_round_trip_is_exactly_68_octets(self):
        field = encode_message_field("AOS lesson")
        sealed = AESGCM(KEY).encrypt(IV, field, AAD)
        frame = PRIMARY_HEADER + SPI.to_bytes(2, "big") + IV + sealed
        self.assertEqual(len(frame), 68)
        self.assertEqual(frame[:6], PRIMARY_HEADER)
        self.assertEqual(frame[6:8], bytes.fromhex("1234"))
        self.assertEqual(frame[8:20], IV)
        opened = AESGCM(KEY).decrypt(IV, frame[20:], AAD)
        self.assertEqual(opened, field)
        self.assertEqual(opened[1:1 + opened[0]].decode("utf-8"), "AOS lesson")

    def test_nist_aes256_gcm_known_answer_and_tampering_fail(self):
        known_answer = AESGCM(bytes(32)).encrypt(bytes(12), bytes(16), None)
        self.assertEqual(known_answer[:-16].hex(), "cea7403d4d606b6e074ec5d3baf39d18")
        self.assertEqual(known_answer[-16:].hex(), "d0d1c8a799996bf0265b98b5d48ab919")
        field = encode_message_field("authenticated")
        sealed = AESGCM(KEY).encrypt(IV, field, AAD)
        changed = bytes([sealed[0] ^ 1]) + sealed[1:]
        with self.assertRaises(InvalidTag):
            AESGCM(KEY).decrypt(IV, changed, AAD)

    def test_shared_profile_header_copies_and_firmware_sketch_are_identical(self):
        self.assertEqual((ROOT / "aos_demo_profile.h").read_bytes(), (SKETCH_DIR / "aos_demo_profile.h").read_bytes())
        self.assertEqual((ROOT / "esp32-qkd-teaching-aos-demo.cpp").read_bytes(),
                         (SKETCH_DIR / "esp32-qkd-teaching-aos-demo.ino").read_bytes())

    def test_static_contract_script_passes(self):
        result = subprocess.run(["python3", str(ROOT / "check_static.py")], cwd=ROOT,
                                capture_output=True, text=True, check=True)
        self.assertIn("six exact routes", result.stdout)
        self.assertIn("no Arduino compile", result.stdout)


class SharedProfileHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("g++")
        if compiler is None:
            raise unittest.SkipTest("g++ is required to exercise the shared C++ profile validator")
        cls._temporary_directory = tempfile.TemporaryDirectory()
        temporary_path = Path(cls._temporary_directory.name)
        cls._runner = temporary_path / "profile_validator"
        harness = temporary_path / "profile_validator.cpp"
        harness.write_text(r'''#include "aos_demo_profile.h"
#include <cstdint>
#include <cstdlib>
#include <iostream>

int main(int argc, char **argv) {
  if (argc != 2) return 2;
  char *end = nullptr;
  const unsigned long spi = std::strtoul(argv[1], &end, 10);
  if (end == argv[1] || *end != '\0' || spi > 0xffffffffUL) return 2;
  const char *error = aos_demo_profile::validateFixedProfile(
      static_cast<uint32_t>(spi), aos_demo_profile::kRequiredPrimaryHeader);
  std::cout << (error == nullptr ? "ok" : error);
  return 0;
}
''', encoding="utf-8")
        subprocess.run([compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror", "-I", str(SKETCH_DIR),
                        str(harness), "-o", str(cls._runner)], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "_temporary_directory"):
            cls._temporary_directory.cleanup()

    def validate(self, spi):
        result = subprocess.run([str(self._runner), str(spi)], check=True, capture_output=True, text=True)
        return result.stdout

    def test_exact_fixed_spi_and_primary_header_pass(self):
        self.assertEqual(self.validate(SPI), "ok")

    def test_reserved_and_wrong_spi_fail(self):
        self.assertEqual(self.validate(0), "spi_must_not_be_reserved")
        self.assertEqual(self.validate(0xffff), "spi_must_not_be_reserved")
        self.assertEqual(self.validate(0x1235), "spi_must_match_fixed_profile_0x1234")


if __name__ == "__main__":
    unittest.main(verbosity=2)
