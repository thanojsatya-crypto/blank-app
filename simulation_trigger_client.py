"""Private-LAN-only, read-only client for the approved PB4 trigger counter."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from urllib.parse import urlsplit

import requests

from esp_api import EspApiError, normalize_base_url

TRIGGER_PATH = "/api/simulation-trigger"
TRIGGER_DEVICE = "esp32-bb84-sim-trigger"
UINT32_MAX = (1 << 32) - 1


@dataclass(frozen=True)
class TriggerSnapshot:
    device: str
    trigger_count: int


def _validate_count(value: object) -> bool:
    return type(value) is int and 0 <= value <= UINT32_MAX


def parse_trigger_snapshot(payload: object) -> TriggerSnapshot:
    """Enforce the exact two-field firmware response and uint32 counter."""
    if not isinstance(payload, dict) or set(payload) != {"device", "trigger_count"}:
        raise EspApiError("invalid_response", "Simulation-trigger response must contain exactly device and trigger_count")
    if payload["device"] != TRIGGER_DEVICE:
        raise EspApiError("invalid_response", "Simulation-trigger device identity did not match the approved firmware")
    if not _validate_count(payload["trigger_count"]):
        raise EspApiError("invalid_response", "Simulation-trigger trigger_count must be an unsigned 32-bit integer")
    return TriggerSnapshot(device=TRIGGER_DEVICE, trigger_count=payload["trigger_count"])


def trigger_count_changed(previous: int | None, current: int) -> bool:
    """Compare observations without delta arithmetic, safe across uint32 reset/wrap.

    Callers should store ``current`` as the new baseline before running the
    simulator. A first successful observation is only a baseline, never an event.
    Any later difference means one event; delta size is intentionally ignored.
    """
    if not _validate_count(current):
        raise ValueError("current trigger count must be uint32")
    if previous is None:
        return False
    if not _validate_count(previous):
        raise ValueError("previous trigger count must be uint32 or None")
    return current != previous


class TriggerEventTracker:
    """Track successful counter observations; failures never advance the baseline."""

    def __init__(self, baseline: int | None = None):
        if baseline is not None and not _validate_count(baseline):
            raise ValueError("baseline trigger count must be uint32 or None")
        self.baseline = baseline

    def record_failure(self) -> None:
        """A failed poll is not an observation and therefore changes no state."""

    def observe_success(self, current: int) -> bool:
        """Commit one valid count and return whether this observation is one event."""
        changed = trigger_count_changed(self.baseline, current)
        self.baseline = current
        return changed


class SimulationTriggerClient:
    """Client whose only possible request is GET /api/simulation-trigger."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 2.0,
        *,
        allow_loopback_for_tests: bool = False,
    ):
        self.base_url = normalize_base_url(base_url)
        address = ipaddress.IPv4Address(urlsplit(self.base_url).hostname)
        if address.is_loopback and not allow_loopback_for_tests:
            raise ValueError("PB4 polling must target an ESP32 private LAN IPv4 address")
        self.timeout_seconds = timeout_seconds

    def get_snapshot(self) -> TriggerSnapshot:
        session = requests.Session()
        session.trust_env = False
        try:
            try:
                response = session.get(
                    f"{self.base_url}{TRIGGER_PATH}",
                    timeout=self.timeout_seconds,
                    headers={"Accept": "application/json"},
                    allow_redirects=False,
                )
            except requests.Timeout as exc:
                raise EspApiError("timeout", "Timed out reading the PB4 simulation-trigger counter") from exc
            except requests.ConnectionError as exc:
                raise EspApiError("disconnected", "Could not reach the ESP simulation-trigger endpoint") from exc
            except requests.RequestException as exc:
                raise EspApiError("network", "The simulation-trigger request failed") from exc
            if not response.ok:
                raise EspApiError("http", f"Simulation-trigger endpoint returned HTTP {response.status_code}", response.status_code)
            try:
                payload = response.json()
            except ValueError as exc:
                raise EspApiError("invalid_response", "Simulation-trigger response was not valid JSON", response.status_code) from exc
            return parse_trigger_snapshot(payload)
        finally:
            session.close()
