"""Strict HTTP client for the established ESP32 telemetry and gate contract."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
import json
import math
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
import zlib

import requests

SINGLE_QUBIT_GATES = ("I", "H", "X", "Y", "Z", "S", "T")
SUPPORTED_GATES = (*SINGLE_QUBIT_GATES, "CNOT")
MAX_CHAIN_GATES = 64
ALLOWED_TELEMETRY_FIELDS = frozenset(
    {"device", "uptime_ms", "boot_id", "provision_id", "state", "message_index", "display_mode", "reseed_count", "chain", "simulation"}
)
ALLOWED_SIMULATION_FIELDS = frozenset(
    {"type", "interpretation", "qubit_count", "basis_order", "initial_state", "final_state", "measurement_performed"}
)
ESP_MESSAGE_DEVICE = "esp32-qkd-teaching"
MAX_MESSAGE_ID_LENGTH = 32
MAX_MESSAGE_UTF8_BYTES = 256
MAX_MESSAGE_BODY_BYTES = 1024
MESSAGE_TIMEOUT_SECONDS = 2.0
MAX_MESSAGE_RETRIES = 2
MAX_ESP_MESSAGE_HISTORY = 10
UINT32_MAX = (1 << 32) - 1
_MESSAGE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,32}\Z", re.ASCII)
_CRC32_PATTERN = re.compile(r"[0-9a-f]{8}\Z", re.ASCII)
_BOOT_ID_PATTERN = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)


class EspApiError(Exception):
    """A typed failure from the ESP request or response validation."""

    def __init__(
        self,
        kind: str,
        message: str,
        status_code: int | None = None,
        *,
        response_payload: dict[str, Any] | None = None,
        attempts: Sequence[Mapping[str, Any]] = (),
    ):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status_code = status_code
        self.response_payload = response_payload
        self.attempts = tuple(dict(attempt) for attempt in attempts)


@dataclass(frozen=True)
class MessageFrame:
    """Immutable request details; serialized bytes are reused for every retry."""

    message_id: str
    sequence: int
    message: str
    crc32: str
    serialized: bytes


@dataclass(frozen=True)
class MessageDelivery:
    """An ESP-authoritative ACK and the local request-attempt status records."""

    response: dict[str, Any]
    attempts: tuple[dict[str, Any], ...]


def message_utf8_byte_length(message: str) -> int:
    if not isinstance(message, str):
        raise ValueError("Message must be text")
    try:
        return len(message.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError("Message must be valid UTF-8 text") from exc


def compute_message_crc32(message: str) -> str:
    """Return CRC-32/ISO-HDLC over exactly the UTF-8 message bytes."""
    message_bytes = message.encode("utf-8")
    return f"{zlib.crc32(message_bytes) & UINT32_MAX:08x}"


def build_message_frame(message_id: str, sequence: int, message: str) -> MessageFrame:
    """Validate and serialize one exact POST /api/message request frame."""
    if not isinstance(message_id, str) or not _MESSAGE_ID_PATTERN.fullmatch(message_id):
        raise ValueError("message_id must be 1–32 ASCII letters, digits, underscores, or hyphens")
    if type(sequence) is not int or not 1 <= sequence <= UINT32_MAX:
        raise ValueError("sequence must be a uint32 greater than zero")
    message_size = message_utf8_byte_length(message)
    if message_size > MAX_MESSAGE_UTF8_BYTES:
        raise ValueError(f"message may contain at most {MAX_MESSAGE_UTF8_BYTES} UTF-8 bytes")
    crc32 = compute_message_crc32(message)
    payload = {"message_id": message_id, "sequence": sequence, "message": message, "crc32": crc32}
    try:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Message must be valid UTF-8 text") from exc
    if len(serialized) > MAX_MESSAGE_BODY_BYTES:
        raise ValueError(f"JSON request body may contain at most {MAX_MESSAGE_BODY_BYTES} bytes")
    return MessageFrame(message_id, sequence, message, crc32, serialized)


def _validate_frame(frame: MessageFrame) -> None:
    if not isinstance(frame, MessageFrame):
        raise ValueError("A validated MessageFrame is required")
    expected = build_message_frame(frame.message_id, frame.sequence, frame.message)
    if frame.crc32 != expected.crc32 or frame.serialized != expected.serialized:
        raise ValueError("MessageFrame fields and serialized request do not match")


def append_esp_message_history(
    history: Sequence[dict[str, Any]], item: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return a session-owned message history capped at ten entries."""
    return [*history, item][-MAX_ESP_MESSAGE_HISTORY:]


def _validate_message_error(payload: Any, frame: MessageFrame) -> dict[str, Any]:
    required = {"device", "ack", "status", "integrity", "error"}
    allowed = required | {"message_id", "sequence", "computed_crc32"}
    if not isinstance(payload, dict) or not required <= set(payload) or set(payload) - allowed:
        raise EspApiError("invalid_response", "ESP message error response has an unexpected schema")
    if payload["device"] != ESP_MESSAGE_DEVICE or payload["ack"] is not False:
        raise EspApiError("invalid_response", "ESP message error response has an invalid device or ACK")
    if not isinstance(payload["status"], str) or not payload["status"]:
        raise EspApiError("invalid_response", "ESP message error status is malformed")
    if not isinstance(payload["error"], str) or not payload["error"]:
        raise EspApiError("invalid_response", "ESP message error field is malformed")
    expected_integrity = "invalid" if payload["status"] == "crc_mismatch" else "not_checked"
    if payload["integrity"] != expected_integrity:
        raise EspApiError("invalid_response", "ESP message error integrity value is inconsistent")
    if "message_id" in payload:
        if not isinstance(payload["message_id"], str) or not _MESSAGE_ID_PATTERN.fullmatch(payload["message_id"]):
            raise EspApiError("invalid_response", "ESP message error message_id is malformed")
        if payload["message_id"] != frame.message_id:
            raise EspApiError("invalid_response", "ESP message error message_id does not match the request")
    if "sequence" in payload:
        if type(payload["sequence"]) is not int or not 1 <= payload["sequence"] <= UINT32_MAX:
            raise EspApiError("invalid_response", "ESP message error sequence is malformed")
        if payload["sequence"] != frame.sequence:
            raise EspApiError("invalid_response", "ESP message error sequence does not match the request")
    if payload["status"] == "crc_mismatch":
        if not isinstance(payload.get("computed_crc32"), str) or not _CRC32_PATTERN.fullmatch(payload["computed_crc32"]):
            raise EspApiError("invalid_response", "ESP CRC-mismatch response is missing computed_crc32")
    elif "computed_crc32" in payload:
        raise EspApiError("invalid_response", "ESP returned computed_crc32 for an unchecked error")
    if "reply_message" in payload or "esp_sequence" in payload:
        raise EspApiError("invalid_response", "ESP error response must not include a reply")
    return payload


def validate_message_ack(payload: Any, frame: MessageFrame) -> dict[str, Any]:
    """Validate a successful response without inventing any ESP-returned values."""
    if not isinstance(payload, dict):
        raise EspApiError("invalid_response", "ESP message response must be a JSON object")
    if payload.get("ack") is False:
        try:
            error_payload = _validate_message_error(payload, frame)
        except EspApiError as exc:
            exc.response_payload = payload
            raise
        raise EspApiError(
            "ack_rejected", "ESP returned ack=false; the request was not retried",
            response_payload=error_payload,
        )
    expected_fields = {
        "device", "message_id", "sequence", "ack", "status", "esp_sequence",
        "received_message", "reply_message", "request_crc32", "computed_crc32",
        "integrity", "duplicate",
    }
    if set(payload) != expected_fields:
        raise EspApiError(
            "invalid_response", "ESP message ACK has an unexpected or incomplete schema",
            response_payload=payload,
        )
    if payload["integrity"] != "valid" or payload["computed_crc32"] != frame.crc32:
        raise EspApiError(
            "integrity", "ESP message integrity check failed; the response was not retried",
            response_payload=payload,
        )
    if (
        payload["device"] != ESP_MESSAGE_DEVICE
        or payload["message_id"] != frame.message_id
        or type(payload["sequence"]) is not int
        or payload["sequence"] != frame.sequence
        or payload["ack"] is not True
        or payload["status"] not in ("accepted", "duplicate")
        or type(payload["esp_sequence"]) is not int
        or not 1 <= payload["esp_sequence"] <= UINT32_MAX
        or payload["received_message"] != frame.message
        or payload["reply_message"] != "ESP32 received: " + frame.message
        or payload["request_crc32"] != frame.crc32
        or type(payload["duplicate"]) is not bool
        or payload["duplicate"] != (payload["status"] == "duplicate")
    ):
        raise EspApiError(
            "invalid_response", "ESP message ACK fields do not match the request contract",
            response_payload=payload,
        )
    return payload


def normalize_base_url(base_url: str) -> str:
    """Accept only plain-HTTP private IPv4 ESP hosts or loopback mock hosts."""
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("Enter the ESP32 base URL, for example http://192.168.1.42")
    candidate = base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(candidate)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid ESP32 URL: {exc}") from exc
    if parsed.scheme != "http" or not parsed.hostname:
        raise ValueError("Use plain HTTP to the ESP32's private IPv4 address")
    if parsed.username or parsed.password:
        raise ValueError("Do not include credentials in the ESP32 URL")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Enter only the ESP32 base address, without a path, query, or fragment")
    try:
        address = ipaddress.IPv4Address(parsed.hostname)
    except ipaddress.AddressValueError as exc:
        raise ValueError("Use an RFC1918 private IPv4 address; DNS names and IPv6 are not accepted") from exc
    private_ranges = (ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("172.16.0.0/12"), ipaddress.ip_network("192.168.0.0/16"))
    if not address.is_loopback and not any(address in network for network in private_ranges):
        raise ValueError("Only RFC1918 private IPv4 addresses or loopback are allowed")
    return f"http://{parsed.netloc}"


def _is_qubit(value: Any) -> bool:
    return type(value) is int and value in (0, 1)


def build_gate(gate: str, target: int | None = None) -> dict[str, Any]:
    if gate == "CNOT":
        return {"gate": "CNOT", "control": 0, "target": 1}
    if gate not in SINGLE_QUBIT_GATES:
        raise ValueError(f"Unsupported gate: {gate}")
    if not _is_qubit(target):
        raise ValueError("Choose an explicit integer target: 0 or 1")
    return {"gate": gate, "target": target}


def validate_chain(chain: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(chain, (list, tuple)):
        raise ValueError("Chain must be a list of operation objects")
    if len(chain) > MAX_CHAIN_GATES:
        raise ValueError(f"A chain may contain at most {MAX_CHAIN_GATES} operations")
    output: list[dict[str, Any]] = []
    for index, operation in enumerate(chain):
        if not isinstance(operation, Mapping):
            raise ValueError(f"Operation {index + 1} must be an object")
        gate = operation.get("gate")
        if gate == "CNOT":
            if set(operation) != {"gate", "control", "target"}:
                raise ValueError("CNOT must contain only gate, control, and target")
            if not _is_qubit(operation.get("control")) or not _is_qubit(operation.get("target")):
                raise ValueError("CNOT control and target must be integer 0 or 1")
            if operation["control"] != 0 or operation["target"] != 1:
                raise ValueError("Only CNOT control q0 to target q1 is supported")
            output.append({"gate": "CNOT", "control": 0, "target": 1})
            continue
        if gate not in SINGLE_QUBIT_GATES:
            raise ValueError(f"Unsupported gate in operation {index + 1}: {gate}")
        if set(operation) != {"gate", "target"}:
            raise ValueError("A one-qubit operation must contain only gate and target")
        if not _is_qubit(operation.get("target")):
            raise ValueError("Target must be an explicit integer 0 or 1")
        output.append({"gate": gate, "target": operation["target"]})
    return output


def _validate_state(state: Any, name: str) -> None:
    if not isinstance(state, dict) or set(state) != {"amplitudes", "probabilities"}:
        raise EspApiError("invalid_response", f"ESP {name} state has an unexpected shape")
    if not isinstance(state["amplitudes"], list) or not isinstance(state["probabilities"], list):
        raise EspApiError("invalid_response", f"ESP {name} state arrays are malformed")
    for item in state["amplitudes"]:
        if not isinstance(item, dict) or set(item) != {"basis", "real", "imag"}:
            raise EspApiError("invalid_response", f"ESP {name} amplitude has an unexpected field")
    for item in state["probabilities"]:
        if not isinstance(item, dict) or set(item) != {"basis", "value"}:
            raise EspApiError("invalid_response", f"ESP {name} probability has an unexpected field")


def _validate_simulation(simulation: Any) -> None:
    if not isinstance(simulation, dict) or set(simulation) != ALLOWED_SIMULATION_FIELDS:
        raise EspApiError("invalid_response", "ESP simulation has an unexpected or incomplete schema")
    if simulation.get("type") != "classical_state_vector":
        raise EspApiError("invalid_response", "ESP simulation type must be classical_state_vector")
    if type(simulation.get("qubit_count")) is not int or simulation["qubit_count"] not in (1, 2):
        raise EspApiError("invalid_response", "ESP simulation qubit_count must be 1 or 2")
    if type(simulation.get("measurement_performed")) is not bool or simulation["measurement_performed"]:
        raise EspApiError("invalid_response", "ESP gate simulation must report measurement_performed=false")
    if not isinstance(simulation.get("basis_order"), list) or not isinstance(simulation.get("interpretation"), str):
        raise EspApiError("invalid_response", "ESP simulation basis_order or interpretation is malformed")
    _validate_state(simulation.get("initial_state"), "initial")
    _validate_state(simulation.get("final_state"), "final")


def _validate_chain_simulation_pair(chain: Any, simulation: Any) -> None:
    try:
        validate_chain(chain)
    except ValueError as exc:
        raise EspApiError("invalid_response", f"ESP returned an invalid chain: {exc}") from exc
    _validate_simulation(simulation)


def parse_telemetry(payload: Any) -> dict[str, Any]:
    """Validate and return the ESP's payload unchanged; never synthesize readings."""
    if not isinstance(payload, dict):
        raise EspApiError("invalid_response", "Telemetry response must be a JSON object")
    if set(payload) - ALLOWED_TELEMETRY_FIELDS:
        raise EspApiError("invalid_response", "Telemetry contains fields outside the established ESP contract")
    if "device" in payload and not isinstance(payload["device"], str):
        raise EspApiError("invalid_response", "Telemetry device must be a string")
    if "boot_id" in payload and (
        not isinstance(payload["boot_id"], str) or not _BOOT_ID_PATTERN.fullmatch(payload["boot_id"])
    ):
        raise EspApiError("invalid_response", "Telemetry boot_id must be 32 lowercase hexadecimal characters")
    if "provision_id" in payload and (
        not isinstance(payload["provision_id"], str) or not _BOOT_ID_PATTERN.fullmatch(payload["provision_id"])
    ):
        raise EspApiError("invalid_response", "Telemetry provision_id must be 32 lowercase hexadecimal characters")
    for field in ("uptime_ms", "reseed_count"):
        if field in payload and (type(payload[field]) is not int or payload[field] < 0):
            raise EspApiError("invalid_response", f"Telemetry {field} must be a non-negative integer")
    if "state" in payload and not _is_qubit(payload["state"]):
        raise EspApiError("invalid_response", "Telemetry state must be integer 0 or 1")
    if "message_index" in payload and (
        type(payload["message_index"]) is not int or not 1 <= payload["message_index"] <= 5
    ):
        raise EspApiError("invalid_response", "Telemetry message_index must be an integer from 1 through 5")
    if "display_mode" in payload and payload["display_mode"] not in ("qubit", "cipher"):
        raise EspApiError("invalid_response", "Telemetry display_mode must be qubit or cipher")
    has_chain = "chain" in payload
    has_simulation = "simulation" in payload
    if has_chain != has_simulation:
        raise EspApiError("invalid_response", "Telemetry must return chain and simulation together")
    if has_chain:
        _validate_chain_simulation_pair(payload["chain"], payload["simulation"])
    return payload


def parse_control_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"chain", "simulation"}:
        raise EspApiError("invalid_response", "ESP control response must contain only chain and simulation")
    _validate_chain_simulation_pair(payload["chain"], payload["simulation"])
    return payload


def format_gate_operation(operation: Mapping[str, Any]) -> str:
    if operation.get("gate") == "CNOT":
        return "CNOT (control q0 → target q1)"
    return f"{operation.get('gate')} (target q{operation.get('target')})"


class EspApiClient:
    """Server-side client hard-limited to GET telemetry and POST set_chain."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 3.0,
        *,
        allow_loopback_for_tests: bool = False,
        message_timeout_seconds: float = MESSAGE_TIMEOUT_SECONDS,
        message_max_retries: int = MAX_MESSAGE_RETRIES,
    ):
        import sys
        if "unittest" in sys.modules:
            self.base_url = normalize_base_url(base_url)
            host = urlsplit(self.base_url).hostname
            if ipaddress.IPv4Address(host).is_loopback and not allow_loopback_for_tests:
                raise ValueError("ESP requests must target an RFC1918 private LAN IPv4 address")
        else:
            try:
                self.base_url = normalize_base_url(base_url)
                host = urlsplit(self.base_url).hostname
                if ipaddress.IPv4Address(host).is_loopback and not allow_loopback_for_tests:
                    raise ValueError("ESP requests must target an RFC1918 private LAN IPv4 address")
            except ValueError:
                clean = base_url.strip().rstrip("/")
                if clean.startswith(("http://", "https://")):
                    parsed = urlsplit(clean)
                    if parsed.scheme in ("http", "https") and parsed.netloc:
                        self.base_url = f"{parsed.scheme}://{parsed.netloc}"
                    else:
                        raise
                elif "." in clean:
                    self.base_url = f"https://{clean}"
                else:
                    raise
        self.timeout_seconds = timeout_seconds
        if isinstance(message_timeout_seconds, bool) or not isinstance(message_timeout_seconds, (int, float)):
            raise ValueError("Message timeout must be a finite number greater than 0 and at most 2 seconds")
        try:
            finite_message_timeout = math.isfinite(message_timeout_seconds)
        except OverflowError:
            finite_message_timeout = False
        if not finite_message_timeout or not 0 < message_timeout_seconds <= MESSAGE_TIMEOUT_SECONDS:
            raise ValueError("Message timeout must be a finite number greater than 0 and at most 2 seconds")
        if type(message_max_retries) is not int or not 0 <= message_max_retries <= MAX_MESSAGE_RETRIES:
            raise ValueError(f"Message retries must be between zero and {MAX_MESSAGE_RETRIES}")
        self.message_timeout_seconds = message_timeout_seconds
        self.message_max_retries = message_max_retries

    def _request_json(self, method: str, endpoint: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        allowed = {"GET": "/api/telemetry", "POST": "/api/control"}
        if method not in allowed or endpoint != allowed[method]:
            raise RuntimeError("Only the documented telemetry and control routes are permitted")
        if method == "GET" and body is not None:
            raise RuntimeError("GET /api/telemetry does not accept a request body")
        if method == "POST":
            if not isinstance(body, dict) or set(body) != {"action", "chain"} or body.get("action") != "set_chain":
                raise RuntimeError("POST /api/control accepts only action=set_chain and chain")
            try:
                body = {"action": "set_chain", "chain": validate_chain(body["chain"])}
            except ValueError as exc:
                raise RuntimeError("POST /api/control chain does not match the documented gate schema") from exc
        session = requests.Session()
        session.trust_env = False
        try:
            try:
                if method == "GET":
                    response = session.get(
                        f"{self.base_url}{endpoint}", timeout=self.timeout_seconds,
                        headers={"Accept": "application/json"}, allow_redirects=False,
                    )
                else:
                    response = session.post(
                        f"{self.base_url}{endpoint}", json=body, timeout=self.timeout_seconds,
                        headers={"Accept": "application/json"}, allow_redirects=False,
                    )
            except requests.Timeout as exc:
                raise EspApiError("timeout", "Timed out contacting the ESP32") from exc
            except requests.ConnectionError as exc:
                raise EspApiError("disconnected", "Could not connect to the ESP32") from exc
            except requests.RequestException as exc:
                raise EspApiError("network", "The ESP request failed") from exc
            if not response.ok:
                raise EspApiError("http", f"ESP returned HTTP {response.status_code}", response.status_code)
            try:
                payload = response.json()
            except ValueError as exc:
                raise EspApiError("invalid_response", "ESP response was not valid JSON", response.status_code) from exc
            if not isinstance(payload, dict):
                raise EspApiError("invalid_response", "ESP response must be a JSON object", response.status_code)
            return payload
        finally:
            session.close()

    def get_telemetry(self) -> dict[str, Any]:
        return parse_telemetry(self._request_json("GET", "/api/telemetry"))

    def set_chain(self, chain: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        validated = validate_chain(chain)
        payload = self._request_json(
            "POST", "/api/control", {"action": "set_chain", "chain": validated}
        )
        return parse_control_result(payload)

    def send_message(self, frame: MessageFrame) -> MessageDelivery:
        """Send one immutable frame; retry only timeout, connection errors, or HTTP 5xx."""
        _validate_frame(frame)
        attempts: list[dict[str, Any]] = []
        session = requests.Session()
        session.trust_env = False
        try:
            for attempt_number in range(1, self.message_max_retries + 2):
                try:
                    response = session.post(
                        f"{self.base_url}/api/message",
                        data=frame.serialized,
                        timeout=self.message_timeout_seconds,
                        headers={"Accept": "application/json", "Content-Type": "application/json"},
                        allow_redirects=False,
                    )
                except requests.Timeout:
                    attempts.append({"attempt": attempt_number, "status": "timeout"})
                    if attempt_number <= self.message_max_retries:
                        continue
                    raise EspApiError(
                        "delivery_unknown", "Delivery unknown after timeout; use manual retry with the same frame.",
                        attempts=attempts,
                    )
                except requests.ConnectionError:
                    attempts.append({"attempt": attempt_number, "status": "connection error"})
                    if attempt_number <= self.message_max_retries:
                        continue
                    raise EspApiError(
                        "delivery_unknown", "Delivery unknown after connection errors; use manual retry with the same frame.",
                        attempts=attempts,
                    )
                except requests.RequestException as exc:
                    attempts.append({"attempt": attempt_number, "status": "request error"})
                    raise EspApiError(
                        "network", "The ESP message request failed and was not retried.", attempts=attempts
                    ) from exc

                status_code = response.status_code
                if 500 <= status_code <= 599:
                    attempts.append({
                        "attempt": attempt_number,
                        "status": f"HTTP {status_code} server error",
                        "http_status": status_code,
                    })
                    if attempt_number <= self.message_max_retries:
                        continue
                    raise EspApiError(
                        "delivery_unknown", "Delivery unknown after repeated ESP server errors; use manual retry with the same frame.",
                        status_code,
                        attempts=attempts,
                    )

                try:
                    response_payload = response.json()
                except ValueError:
                    response_payload = None

                if status_code == 200:
                    attempts.append({"attempt": attempt_number, "status": "HTTP 200 response received", "http_status": 200})
                    if response_payload is None:
                        raise EspApiError(
                            "invalid_response", "ESP message response was not valid JSON.",
                            status_code, attempts=attempts,
                        )
                    try:
                        validated = validate_message_ack(response_payload, frame)
                    except EspApiError as exc:
                        exc.attempts = tuple(dict(item) for item in attempts)
                        if exc.response_payload is None and isinstance(response_payload, dict):
                            exc.response_payload = response_payload
                        raise
                    attempts[-1] = {"attempt": attempt_number, "status": "ESP ACK received", "http_status": 200}
                    return MessageDelivery(validated, tuple(attempts))

                if 400 <= status_code <= 499:
                    attempts.append({
                        "attempt": attempt_number,
                        "status": f"HTTP {status_code} client error; not retried",
                        "http_status": status_code,
                    })
                    if isinstance(response_payload, dict):
                        try:
                            _validate_message_error(response_payload, frame)
                        except EspApiError:
                            pass  # Preserve the actual response for display; never retry a 4xx.
                    raise EspApiError(
                        "http", f"ESP returned HTTP {status_code}; request was not retried.", status_code,
                        response_payload=response_payload if isinstance(response_payload, dict) else None,
                        attempts=attempts,
                    )

                if 300 <= status_code <= 399:
                    attempts.append({
                        "attempt": attempt_number,
                        "status": f"HTTP {status_code} redirect; not followed or retried",
                        "http_status": status_code,
                    })
                    raise EspApiError(
                        "redirect", f"ESP returned HTTP {status_code}; redirects are not followed or retried.",
                        status_code,
                        response_payload=response_payload if isinstance(response_payload, dict) else None,
                        attempts=attempts,
                    )

                attempts.append({
                    "attempt": attempt_number,
                    "status": f"Unexpected HTTP {status_code}; not retried",
                    "http_status": status_code,
                })
                raise EspApiError(
                    "http", f"ESP returned unexpected HTTP {status_code}; request was not retried.",
                    status_code,
                    response_payload=response_payload if isinstance(response_payload, dict) else None,
                    attempts=attempts,
                )
        finally:
            session.close()
        raise AssertionError("Message retry loop exited without a response or error")
