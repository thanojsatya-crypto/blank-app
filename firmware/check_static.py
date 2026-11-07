#!/usr/bin/env python3
"""Static source-contract checks only; not an Arduino compile or hardware test."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
SKETCH_DIR = ROOT / "arduino" / "esp32-qkd-teaching-aos-demo"
INO = SKETCH_DIR / "esp32-qkd-teaching-aos-demo.ino"
PROFILE_HEADER = SKETCH_DIR / "aos_demo_profile.h"
CPP_PROFILE_HEADER = ROOT / "aos_demo_profile.h"
CPP = ROOT / "esp32-qkd-teaching-aos-demo.cpp"

BASELINE_FUNCTION_SHA256 = {
    "handlePostMessage": "f38f7b16ef66a3a1568c961814f3b3b2ff379b4247423712f5c300bd55fe93cc",
    "sendMessageError": "6862889c707eb0c460024b6d7709ebfa0e5484c515c7d96969e2b59dd7d681fe",
    "sendCachedMessageReply": "9a5ddad7754a48f89e699e8df5d9ed86c25d8aedaec0039aace761b69782b515",
    "calculateMessageCrc32": "a2d2595b4db698fd0a3d505c0abd483506e16dc76988c1e8144daff6a7026739",
    "handleButtonPress": "96438fecd3623821ffa8dd5badf20faae0f564fbf1ed6e61cabc8a5fc2ec9a89",
}


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def function_body(source: str, name: str) -> str:
    match = re.search(rf"\b(?:void|bool|uint32_t|int)\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", source)
    if not match:
        fail(f"missing function {name}")
    opening = source.find("{", match.start())
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1:index]
    fail(f"unclosed function {name}")


try:
    entries = sorted(path.name for path in SKETCH_DIR.iterdir())
    ino_bytes = INO.read_bytes()
    cpp_bytes = CPP.read_bytes()
    profile_header = PROFILE_HEADER.read_text(encoding="utf-8")
    profile_header_bytes = PROFILE_HEADER.read_bytes()
    cpp_profile_header_bytes = CPP_PROFILE_HEADER.read_bytes()
except OSError as exc:
    fail(f"cannot inspect staged files: {exc}")
if entries != sorted([INO.name, PROFILE_HEADER.name]):
    fail(f"Arduino sketch directory must contain only .ino and shared profile header; found {entries}")
if SKETCH_DIR in CPP.parents or ino_bytes != cpp_bytes:
    fail(".cpp reference must remain outside sketch folder and be byte-identical to .ino")
if profile_header_bytes != cpp_profile_header_bytes:
    fail("shared profile header copies must remain byte-identical")
source = ino_bytes.decode("utf-8")

expected_routes = {
    ("/api/telemetry", "HTTP_GET", "handleGetTelemetry"),
    ("/api/control", "HTTP_POST", "handlePostControl"),
    ("/api/simulation-trigger", "HTTP_GET", "handleGetSimulationTrigger"),
    ("/api/message", "HTTP_POST", "handlePostMessage"),
    ("/api/aos-demo/provision", "HTTP_POST", "handlePostAosDemoProvision"),
    ("/api/aos-demo/downlink", "HTTP_POST", "handlePostAosDemoDownlink"),
}
registered_routes = set(re.findall(r'server\s*\.\s*on\s*\(\s*"([^"]+)"\s*,\s*(HTTP_[A-Z]+)\s*,\s*(\w+)\s*\)', source))
if registered_routes != expected_routes or len(registered_routes) != 6:
    fail(f"route set differs from the four existing and two AOS routes: {sorted(registered_routes)}")
if len(re.findall(r"\bserver\s*\.\s*on\s*\(", source)) != 6:
    fail("found unparsed or additional server.on() registration")

for name, expected_hash in BASELINE_FUNCTION_SHA256.items():
    actual_hash = hashlib.sha256(function_body(source, name).encode()).hexdigest()
    if actual_hash != expected_hash:
        fail(f"baseline function changed: {name}")

# Existing hardware roles and PB4's sole action remain unchanged.
expected_pins = {
    "PB1_H_PIN": 18, "PB2_X_PIN": 19, "PB3_SLOT_PIN": 21,
    "PB4_SIMULATION_PIN": 22, "PB5_DISPLAY_PIN": 25, "PB6_RESET_PIN": 27,
}
for symbol, gpio in expected_pins.items():
    if not re.search(rf"\b{symbol}\s*=\s*{gpio}\s*;", source):
        fail(f"pin mapping changed: {symbol} must remain GPIO{gpio}")
button_array = re.search(r"BUTTON_PINS\[\]\s*=\s*\{([^}]+)\}", source, re.S)
if not button_array or re.findall(r"\b[A-Z][A-Z0-9_]+_PIN\b", button_array.group(1)) != list(expected_pins):
    fail("button pin array/order changed")
if not re.search(r"pinMode\s*\(\s*BUTTON_PINS\[i\]\s*,\s*INPUT_PULLUP\s*\)", source):
    fail("buttons are no longer configured active-low")
if not re.search(r"pinMode\s*\(\s*STATUS_LED_PIN\s*,\s*OUTPUT\s*\)", source) or re.search(r"digitalRead\s*\(\s*STATUS_LED_PIN\s*\)", source):
    fail("GPIO2 status LED is not output-only")
pb4 = function_body(source, "handleButtonPress")
pb4_case = re.search(r"case\s+3\s*:(.*?)(?=\bcase\s+4\s*:)", pb4, re.S)
if not pb4_case:
    fail("PB4 handler missing")
pb4_code = re.sub(r"//[^\n]*|/\*.*?\*/", "", pb4_case.group(1), flags=re.S).strip()
if not re.fullmatch(r"\+\+simulationTriggerCount\s*;\s*break\s*;", pb4_code):
    fail("PB4 must remain only the simulation-request counter increment")
if not re.search(r"volatile\s+uint32_t\s+simulationTriggerCount\s*=\s*0\s*;", source):
    fail("PB4 counter is not volatile RAM-only uint32 state")

# Strict provisioning contract and validate-before-commit ordering.
provision = function_body(source, "handlePostAosDemoProvision")
for required in (
    'object.size() != 3', '"password"', '"key_hex"', '"message"',
    'isValidPairingPassword(password.c_str(), password.size())',
    'keyHex.size() != DEMO_KEY_HEX_CHARS', 'decodeExactHex(keyHex.c_str()',
    'isValidUtf8Text(messageBytes, messageLength)',
    'messageLength > DEMO_AOS_DATA_BYTES - 1',
    'candidateDataField[0] = static_cast<uint8_t>(messageLength)',
    'memcpy(candidateDataField + 1, messageBytes, messageLength)',
    'clearDemoProvisioningRam()', 'demoProvisioned = true',
):
    if required not in provision:
        fail(f"AOS provision contract missing: {required}")
if not (
    provision.index('isValidPairingPassword(password.c_str()')
    < provision.index('decodeExactHex(keyHex.c_str()')
    < provision.index('isValidUtf8Text(messageBytes')
    < provision.index('messageLength > DEMO_AOS_DATA_BYTES - 1')
    < provision.index('clearDemoProvisioningRam()')
    < provision.index('demoProvisioned = true')
):
    fail("provision must validate password/key/message before replacing the current volatile state")
if re.search(r'response\s*\[\s*"(?:password|key_hex|message)"', provision):
    fail("provision response must not echo password, key, or plaintext")
provision_success_keys = set(re.findall(r'response\s*\[\s*"([^"]+)"\s*\]\s*=', provision))
if provision_success_keys != {"accepted", "provisioned"}:
    fail(f"provision success response changed: {sorted(provision_success_keys)}")
if "esp_fill_random(provisionSessionId, sizeof(provisionSessionId))" not in provision:
    fail("each accepted provision must create a fresh non-secret volatile provision_id")

# Downlink is a separate password-only request and checks RAM state and pairing before encryption.
downlink = function_body(source, "handlePostAosDemoDownlink")
for required in (
    'object.size() != 1', '"password"', '!demoProvisioned',
    'demo_provision_required_after_reset_or_reboot',
    '!matchesDemoPairingPassword(password.c_str(), password.size())',
    'demo_pairing_rejected', 'encryptAndRespondAosFrame',
):
    if required not in downlink:
        fail(f"password-gated downlink contract missing: {required}")
if not (downlink.index('!demoProvisioned') < downlink.index('!matchesDemoPairingPassword') < downlink.index('encryptAndRespondAosFrame')):
    fail("downlink must require a current provision and matching password before encryption")

# Shared frame creation returns frame + matching key only after the protected route calls it.
encrypt_helper = function_body(source, "encryptAndRespondAosFrame")
for required in (
    "DEMO_AOS_DATA_BYTES", "mbedtls_gcm_setkey(&gcm, MBEDTLS_CIPHER_ID_AES, demoKey, 256)",
    "mbedtls_gcm_crypt_and_tag", "buildAosBaselineAad(primaryHeader, securityHeader, aad)",
    'response["frame_hex"] = frameOut', 'response["key_hex"] = keyOut',
    'response["boot_id"] = bootSessionIdHex', 'response["provision_id"] = provisionSessionIdHex',
):
    if required not in encrypt_helper:
        fail(f"AES-GCM downlink construction missing: {required}")
frame_success_keys = set(re.findall(r'response\s*\[\s*"([^"]+)"\s*\]\s*=', encrypt_helper))
if frame_success_keys != {"primary_header_hex", "security_header_hex", "ciphertext_hex", "tag_hex", "frame_hex", "key_hex", "boot_id", "provision_id"}:
    fail(f"downlink response must contain exact frame fields, matching key, and session IDs: {sorted(frame_success_keys)}")
if re.search(r'response\s*\[\s*"(?:password|message|plaintext|frame_data_hex)"', encrypt_helper):
    fail("downlink response leaks password or plaintext")
if not (encrypt_helper.index('sendJsonResponse(200, response)') < encrypt_helper.index('secureWipe(keyOut, sizeof(keyOut))')):
    fail("temporary response key must remain intact until JSON serialization completes")

# Fixed header/SPI profile; the 32-byte Data Field is variable and length-prefixed.
for required in (
    "kRequiredSpi = 0x1234", "0x69, 0x52, 0x12, 0x34, 0x56, 0x4a",
    "validateFixedProfile(uint32_t spi, const uint8_t *primaryHeader)",
    "spi_must_not_be_reserved", "spi_must_match_fixed_profile_0x1234",
    "primary_header_must_match_fixed_profile_69521234564a",
):
    if required not in profile_header:
        fail(f"shared AOS profile validator missing: {required}")
if "kRequiredFrameData" in profile_header or "kRequiredFrameData" in source:
    fail("fixed sample Data Field remains in source")
expected_frame_constants = {
    "DEMO_AOS_PRIMARY_HEADER_BYTES": 6, "DEMO_AOS_SECURITY_HEADER_BYTES": 14,
    "DEMO_AOS_DATA_BYTES": 32, "DEMO_AOS_TAG_BYTES": 16,
}
for symbol, value in expected_frame_constants.items():
    if not re.search(rf"\b{symbol}\s*=\s*{value}\s*;", source):
        fail(f"AOS frame field size changed: {symbol} must be {value}")
if "static_assert(DEMO_AOS_FRAME_BYTES == 68" not in source:
    fail("AOS profile must assert the exact 68-octet total")

# Annex E3 masked AAD, IV split, nonce non-wrap, and active-radio hardware RNG.
aad_helper = function_body(source, "buildAosBaselineAad")
for required in (
    "memset(aad, 0,", "primaryHeader[1] & 0x3f",
    "aad[DEMO_AOS_PRIMARY_HEADER_BYTES] = securityHeader[0]",
    "aad[DEMO_AOS_PRIMARY_HEADER_BYTES + 1] = securityHeader[1]",
):
    if required not in aad_helper:
        fail(f"Annex E3 teaching AAD mapping missing: {required}")
if "securityHeader + 2, 12, aad, sizeof(aad)" not in encrypt_helper:
    fail("96-bit inline IV must be nonce and masked prefix passed as AAD")
if "securityHeader[0] = static_cast<uint8_t>(spiValue >> 8)" not in encrypt_helper:
    fail("SPI is not serialized MSB-first")
setup = function_body(source, "setup")
if "clearDemoProvisioningRam();" not in setup:
    fail("setup must clear all provisioned RAM state after hardware reset/reboot")
if "esp_fill_random(bootSessionId, sizeof(bootSessionId))" not in setup:
    fail("missing non-secret ESP hardware-RNG per-boot session identifier")
if "esp_fill_random(demoNoncePrefix, sizeof(demoNoncePrefix))" not in setup:
    fail("missing ESP hardware RNG nonce prefix")
if not (setup.index("while (WiFi.status() != WL_CONNECTED)") < setup.index("esp_fill_random(bootSessionId") < setup.index("esp_fill_random(demoNoncePrefix") < setup.index('server.on("/api/aos-demo/provision"')):
    fail("boot ID and nonce prefix must be initialized only after RF/Wi-Fi is active")
telemetry = function_body(source, "addTelemetry")
for required in ('telemetry["boot_id"] = bootSessionIdHex', 'telemetry["provision_id"] = provisionSessionIdHex'):
    if required not in telemetry:
        fail(f"GET /api/telemetry must expose non-secret session metadata: {required}")
nonce_allocator = function_body(source, "allocateDemoIv")
if "demoNonceCounter == UINT32_MAX" not in nonce_allocator or "++demoNonceCounter" not in nonce_allocator:
    fail("nonce counter must not wrap")

# Volatile-only secret lifecycle and absence of persistence/console logging APIs.
clear = function_body(source, "clearDemoProvisioningRam")
for required in (
    "secureWipe(demoPairingPassword", "demoPairingPasswordLength = 0",
    "secureWipe(demoKey", "secureWipe(demoAosDataField", "secureWipe(provisionSessionId", "demoProvisioned = false",
):
    if required not in clear:
        fail(f"RAM reset clear missing: {required}")
for forbidden in (r"\b(?:Preferences|EEPROM|SPIFFS|LittleFS|FFat)\b", r"\bSerial\w*\b", r"\bESP_LOG[EWIDV]\b"):
    if re.search(forbidden, source):
        fail(f"persistent storage or logging API found: {forbidden}")
if '"DEMO-ONLY-PAIRING"' in source or "demoPairingId" in source or "demoKeyId" in source:
    fail("fixed credential or persistent session ID remains")

print("PASS: isolated sketch layout, shared profile header, and byte-identical .cpp/.ino")
print("PASS: six exact routes; existing /api/message/helper and PB4 role hashes unchanged")
print("PASS: Key Generator provision schema; volatile password/key/message wipe; stale reboot fails closed")
print("PASS: password-only Base Station downlink; exact key/frame plus non-secret boot/provision identifiers")
print("PASS: length-prefixed UTF-8 Data Field rejects oversize input; no fixed sample or silent truncation")
print("PASS: AES-256-GCM teaching profile, Annex E3 AAD, ESP RNG nonce prefix, and counter checks")
print("NOTE: static source checks only; no Arduino compile, flash, execution, or hardware validation")
