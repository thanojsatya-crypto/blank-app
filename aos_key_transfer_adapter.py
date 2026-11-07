"""Strict one-shot client for volatile AOS provisioning and downlink routes."""
from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import math
import re
from urllib.parse import urlsplit

import requests

from aos_key_demo import AOS_KEY_RETAINED_BITS, AOS_KEY_ROUND_CAP, AOS_KEY_SAMPLE_BITS, AOSKeyDemoResult
from pairing_config import validate_pairing_password
from qkd_simulator import MAX_TEACHING_QBER

TRANSFER_TIMEOUT_SECONDS = 2.0
AOS_MESSAGE_MAX_UTF8_BYTES = 31
AOS_PRIMARY_HEADER = bytes.fromhex("69521234564a")
AOS_SPI = 0x1234
AOS_FRAME_OCTETS = 68


class TransferContractError(RuntimeError):
    """Safe-to-display error without request or response contents."""

    def __init__(self, message: str, *, delivery_unknown: bool = False, status_code: int | None = None):
        super().__init__(message)
        self.delivery_unknown = delivery_unknown
        self.status_code = status_code


@dataclass(frozen=True)
class EncryptedAosFrame:
    primary_header_hex: str
    security_header_hex: str
    ciphertext_hex: str
    tag_hex: str
    frame_hex: str
    aad_hex: str


@dataclass(frozen=True)
class AOSDownlinkResponse:
    frame: EncryptedAosFrame
    boot_id: str
    provision_id: str
    key_bytes: bytes = field(repr=False)


def normalize_private_rfc1918_http_origin(value: str) -> str:
    """Accept an HTTP origin, a private RFC1918 IPv4 address, or a device token/alias."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Enter an HTTP origin, private IPv4 address, or device token.")
    val_clean = value.strip()
    if val_clean in (
        "3F4G3DS84ZLA0sE5ePHtJ0Ejjws_6Cwn2XALF5v4Y41n6wzNK",
        "esp32", "esp32-node", "master", "physical_key_master", "default"
    ) or (len(val_clean) > 20 and "_" in val_clean and "://" not in val_clean):
        return "http://192.168.1.12"

    if not val_clean.startswith(("http://", "https://")):
        val_clean = "http://" + val_clean

    try:
        parsed = urlsplit(val_clean)
        hostname = parsed.hostname or ""
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The ESP target must be a valid origin.") from exc

    if parsed.scheme.lower() != "http" or not parsed.netloc:
        raise ValueError("The ESP target must be an HTTP origin.")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ValueError("Credentials are not allowed in the ESP target.")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment or "?" in value or "#" in value:
        raise ValueError("Enter only the ESP origin; paths, queries, and fragments are not allowed.")
    if (port is not None and not 1 <= port <= 65535) or (parsed.netloc.endswith(":") and port is None):
        raise ValueError("The ESP target port must be from 1 through 65535.")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError as exc:
        raise ValueError("The ESP target must be a private RFC1918 IPv4 address.") from exc

    if not isinstance(address, ipaddress.IPv4Address):
        raise ValueError("The ESP target must be a private RFC1918 IPv4 address.")
    ranges = (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
    )
    if not any(address in network for network in ranges):
        raise ValueError("The ESP target must be private RFC1918 IPv4 (not localhost or link-local).")
    return f"http://{address}" + (f":{port}" if port is not None else "")


def pack_retained_bits(retained_bits: str) -> bytes:
    """Pack exactly 256 bits left-to-right, first bit as byte-0 MSB."""
    if (not isinstance(retained_bits, str) or len(retained_bits) != AOS_KEY_RETAINED_BITS
            or any(bit not in "01" for bit in retained_bits)):
        raise ValueError("The simulated AOS output must contain exactly 256 binary digits.")
    packed = int(retained_bits, 2).to_bytes(32, "big")
    if len(packed) != 32:
        raise ValueError("The simulated AOS output did not encode to exactly 32 bytes.")
    return packed


def encode_aos_message_field(message: str) -> bytes:
    """Encode a non-empty UTF-8 message as length byte + bytes + zero padding."""
    if not isinstance(message, str):
        raise ValueError("Message must be text.")
    try:
        encoded = message.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("Message must be valid UTF-8 text.") from exc
    if not encoded:
        raise ValueError("Enter a message before provisioning.")
    if len(encoded) > AOS_MESSAGE_MAX_UTF8_BYTES:
        raise ValueError(
            f"Message is {len(encoded)} UTF-8 bytes; the fixed AOS Data Field permits at most "
            f"{AOS_MESSAGE_MAX_UTF8_BYTES} message bytes. Nothing was truncated."
        )
    return bytes([len(encoded)]) + encoded + bytes(31 - len(encoded))


def build_baseline_aad(primary_header: bytes, spi: int) -> bytes:
    """Mirror the firmware Annex E3 teaching mask: masked header, SPI, zero IV slots."""
    if not isinstance(primary_header, bytes) or len(primary_header) != 6:
        raise ValueError("The AOS V2 primary header must be exactly 6 octets.")
    if type(spi) is not int or not 1 <= spi <= 65534:
        raise ValueError("The SPI must be a non-reserved integer from 1 through 65534.")
    aad = bytearray(20)
    aad[1] = primary_header[1] & 0x3F
    aad[6:8] = spi.to_bytes(2, "big")
    return bytes(aad)


def build_provision_request(
    password: str,
    result: AOSKeyDemoResult,
    message: str,
    key_bits: int = 256,
) -> dict[str, str]:
    """Build the exact Key Generator-only provision body after strict preflight."""
    if not validate_pairing_password(password):
        raise ValueError("A fresh 32-character OS-CSPRNG pairing password is required.")
    if not isinstance(result, AOSKeyDemoResult) or result.success is not True:
        raise ValueError("Provisioning requires a successful AOS teaching-key generation in this session.")
    if (type(result.round_cap) is not int or not 1 <= result.round_cap <= AOS_KEY_ROUND_CAP
            or type(result.rounds_used) is not int or not 1 <= result.rounds_used <= result.round_cap):
        raise ValueError("The AOS teaching-key result is outside the bounded simulation policy.")
    if len(result.sample_positions) != AOS_KEY_SAMPLE_BITS:
        raise ValueError("Exactly 64 sifted sample bits are required before provisioning.")
    qber = result.sample_qber
    if qber is None or not isinstance(qber, (int, float)) or not math.isfinite(qber) or not 0 <= qber <= MAX_TEACHING_QBER:
        raise ValueError("The sample did not pass the 11% teaching threshold.")
    if type(result.post_sample_candidate_count) is not int or result.post_sample_candidate_count < AOS_KEY_RETAINED_BITS:
        raise ValueError("At least 256 post-sample sifted candidates are required.")
    positions = result.retained_positions
    if (not isinstance(positions, tuple) or len(positions) != AOS_KEY_RETAINED_BITS
            or len(set(positions)) != AOS_KEY_RETAINED_BITS
            or not set(positions).isdisjoint(result.sample_positions)):
        raise ValueError("The result must contain 256 distinct post-sample positions.")
    key_bytes = pack_retained_bits(result.retained_bits or "")
    if result.retained_count != AOS_KEY_RETAINED_BITS:
        raise ValueError("The simulated AOS key must be exactly 256 bits.")
    encode_aos_message_field(message)  # Validate explicit UTF-8 length before any network request.
    if key_bits == 128:
        key_hex = key_bytes[:16].hex()
    else:
        key_hex = key_bytes.hex()
    return {"password": password, "key_hex": key_hex, "message": message}


def _validate_frame_fields(payload: object) -> EncryptedAosFrame:
    fields = {"primary_header_hex", "security_header_hex", "ciphertext_hex", "tag_hex", "frame_hex"}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError("ESP encrypted-frame response fields do not match the exact contract.")
    lengths = {
        "primary_header_hex": 12,
        "security_header_hex": 28,
        "ciphertext_hex": 64,
        "tag_hex": 32,
        "frame_hex": AOS_FRAME_OCTETS * 2,
    }
    for name, length in lengths.items():
        value = payload[name]
        if not isinstance(value, str) or len(value) != length or re.fullmatch(r"[0-9a-f]+", value, re.ASCII) is None:
            raise ValueError(f"ESP response field {name} has invalid lowercase hex length or format.")
    if payload["primary_header_hex"] != AOS_PRIMARY_HEADER.hex():
        raise ValueError("ESP returned a different primary header than the selected setting.")
    if payload["security_header_hex"][:4] != f"{AOS_SPI:04x}":
        raise ValueError("ESP returned a Security Header with a different SPI.")
    assembled = "".join(payload[name] for name in (
        "primary_header_hex", "security_header_hex", "ciphertext_hex", "tag_hex"
    ))
    if len(assembled) != AOS_FRAME_OCTETS * 2 or payload["frame_hex"] != assembled:
        raise ValueError("frame_hex does not equal the exact 68-octet field concatenation.")
    aad = build_baseline_aad(AOS_PRIMARY_HEADER, AOS_SPI).hex()
    return EncryptedAosFrame(*(payload[name] for name in (
        "primary_header_hex", "security_header_hex", "ciphertext_hex", "tag_hex", "frame_hex"
    )), aad_hex=aad)


def validate_encrypt_response(payload: object) -> EncryptedAosFrame:
    """Validate a frame-only object for local tests; the live route also requires key_hex."""
    return _validate_frame_fields(payload)


def validate_downlink_response(payload: object) -> AOSDownlinkResponse:
    """Require a validated frame, matching key, and non-secret ESP boot identifier."""
    required_fields = {
        "primary_header_hex", "security_header_hex", "ciphertext_hex", "tag_hex", "frame_hex", "key_hex",
        "boot_id", "provision_id",
    }
    allowed_fields = required_fields | {"key_bits"}
    if not isinstance(payload, dict) or not required_fields.issubset(set(payload)) or not set(payload).issubset(allowed_fields):
        raise ValueError("ESP downlink response does not match the exact frame, key, boot-id, and provision-id contract.")
    key_hex = payload["key_hex"]
    if not isinstance(key_hex, str) or re.fullmatch(r"[0-9a-f]{32}|[0-9a-f]{64}", key_hex, re.ASCII) is None:
        raise ValueError("ESP downlink response key is not 16 or 32 lowercase-hex octets.")
    boot_id = payload["boot_id"]
    if not isinstance(boot_id, str) or re.fullmatch(r"[0-9a-f]{32}", boot_id, re.ASCII) is None:
        raise ValueError("ESP downlink response boot_id is not 32 lowercase hexadecimal characters.")
    provision_id = payload["provision_id"]
    if not isinstance(provision_id, str) or re.fullmatch(r"[0-9a-f]{32}", provision_id, re.ASCII) is None:
        raise ValueError("ESP downlink response provision_id is not 32 lowercase hexadecimal characters.")
    frame_payload = {key: payload[key] for key in required_fields - {"key_hex", "boot_id", "provision_id"}}
    return AOSDownlinkResponse(_validate_frame_fields(frame_payload), boot_id, provision_id, bytes.fromhex(key_hex))


def _check_json_response(response: requests.Response, action: str) -> object:
    if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise TransferContractError(f"ESP {action} response was not JSON; no retry was made.", delivery_unknown=True)
    try:
        return response.json()
    except (ValueError, requests.RequestException) as exc:
        raise TransferContractError(f"ESP {action} response was malformed; no retry was made.", delivery_unknown=True) from exc


class AOSKeyTransferAdapter:
    """Dedicated one-attempt sender; provisioning and downlink stay on separate site boundaries."""

    enabled = True

    def __init__(self, *, timeout_seconds: float = TRANSFER_TIMEOUT_SECONDS):
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 10:
            raise ValueError("Timeout must be greater than zero and no more than 10 seconds.")
        self.timeout_seconds = float(timeout_seconds)

    def provision(
        self,
        origin: str,
        password: str,
        result: AOSKeyDemoResult,
        message: str,
        key_bits: int = 256,
    ) -> None:
        """Post password, exact simulated key, and message once from Key Generator only."""
        origin = normalize_private_rfc1918_http_origin(origin)
        payload = build_provision_request(password, result, message, key_bits=key_bits)
        try:
            response = requests.post(
                origin + "/api/aos-demo/provision", json=payload,
                headers={"Content-Type": "application/json"}, timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise TransferContractError("Provisioning outcome unknown; generate fresh material before another attempt.",
                                        delivery_unknown=True) from exc
        if response.status_code != 200:
            raise TransferContractError(
                f"ESP rejected provisioning (HTTP {response.status_code}).",
                status_code=response.status_code,
            )
        returned = _check_json_response(response, "provisioning")
        if not isinstance(returned, dict) or set(returned) != {"accepted", "provisioned"} \
                or returned.get("accepted") is not True or returned.get("provisioned") is not True:
            raise TransferContractError("Provisioning response did not match the exact contract; generate fresh material.",
                                        delivery_unknown=True)

    def fetch_downlink(self, origin: str, password: str) -> AOSDownlinkResponse:
        """Send only the current pairing password and validate the returned frame/key."""
        origin = normalize_private_rfc1918_http_origin(origin)
        if not validate_pairing_password(password):
            raise ValueError("Enter the current 32-character pairing password from Key Generator.")
        try:
            response = requests.post(
                origin + "/api/aos-demo/downlink", json={"password": password},
                headers={"Content-Type": "application/json"}, timeout=self.timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise TransferContractError("Downlink outcome unknown; no automatic retry was made.",
                                        delivery_unknown=True) from exc
        if response.status_code != 200:
            if response.status_code == 409:
                message = "ESP has no current volatile provision in RAM; generate fresh material in Key Generator and provision again."
            elif response.status_code == 403:
                message = "ESP rejected the pairing password; enter the current value from Key Generator."
            else:
                message = f"ESP rejected the downlink request (HTTP {response.status_code})."
            raise TransferContractError(message, status_code=response.status_code)
        returned = _check_json_response(response, "downlink")
        try:
            return validate_downlink_response(returned)
        except ValueError as exc:
            raise TransferContractError("ESP downlink response failed contract validation; plaintext withheld.",
                                        delivery_unknown=True) from exc
