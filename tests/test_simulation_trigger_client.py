from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest

from esp_api import EspApiError
from simulation_trigger_client import (
    SimulationTriggerClient,
    TriggerEventTracker,
    UINT32_MAX,
    parse_trigger_snapshot,
    trigger_count_changed,
)


class TriggerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler):
        super().__init__(address, handler)
        self.paths = []
        self.payload = {"device": "esp32-bb84-sim-trigger", "trigger_count": 12}
        self.status = 200


class TriggerHandler(BaseHTTPRequestHandler):
    server: TriggerServer

    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        self.server.paths.append(self.path)
        payload = self.server.payload if self.server.status == 200 else {"error": "unavailable"}
        body = json.dumps(payload).encode()
        self.send_response(self.server.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class SimulationTriggerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = TriggerServer(("127.0.0.1", 0), TriggerHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.client = SimulationTriggerClient(
            f"http://127.0.0.1:{cls.server.server_port}",
            timeout_seconds=1,
            allow_loopback_for_tests=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.server.paths.clear()
        self.server.payload = {"device": "esp32-bb84-sim-trigger", "trigger_count": 12}
        self.server.status = 200

    def test_client_uses_only_exact_read_only_route_and_schema(self):
        snapshot = self.client.get_snapshot()
        self.assertEqual(snapshot.device, "esp32-bb84-sim-trigger")
        self.assertEqual(snapshot.trigger_count, 12)
        self.assertEqual(self.server.paths, ["/api/simulation-trigger"])

    def test_response_schema_is_exact_and_count_is_uint32_not_bool(self):
        self.assertEqual(parse_trigger_snapshot({"device": "esp32-bb84-sim-trigger", "trigger_count": UINT32_MAX}).trigger_count, UINT32_MAX)
        invalid = (
            {},
            {"device": "other", "trigger_count": 1},
            {"device": "esp32-bb84-sim-trigger", "trigger_count": True},
            {"device": "esp32-bb84-sim-trigger", "trigger_count": -1},
            {"device": "esp32-bb84-sim-trigger", "trigger_count": UINT32_MAX + 1},
            {"device": "esp32-bb84-sim-trigger", "trigger_count": 1, "simulated_key": "forbidden"},
        )
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(EspApiError):
                parse_trigger_snapshot(payload)

    def test_first_poll_is_baseline_then_any_difference_is_exactly_one_event(self):
        self.assertFalse(trigger_count_changed(None, 30))
        baseline = 30
        self.assertTrue(trigger_count_changed(baseline, 31))
        baseline = 31
        self.assertFalse(trigger_count_changed(baseline, 31))
        # Counter jump means one observed event, not one run per missed count.
        self.assertTrue(trigger_count_changed(baseline, 40))
        baseline = 40
        self.assertFalse(trigger_count_changed(baseline, 40))

    def test_counter_reset_and_uint32_wrap_do_not_create_delta_bursts(self):
        self.assertTrue(trigger_count_changed(55, 0))
        self.assertFalse(trigger_count_changed(0, 0))
        self.assertTrue(trigger_count_changed(UINT32_MAX, 0))
        self.assertFalse(trigger_count_changed(0, 0))

    def test_tracker_first_success_failure_increment_reset_wrap_and_no_storms(self):
        tracker = TriggerEventTracker()
        tracker.record_failure()
        self.assertIsNone(tracker.baseline)
        self.assertFalse(tracker.observe_success(12))  # First success is baseline only.
        self.assertEqual(tracker.baseline, 12)
        self.assertFalse(tracker.observe_success(12))
        self.assertTrue(tracker.observe_success(15))  # Any difference is one event, not delta=3.
        self.assertEqual(tracker.baseline, 15)
        self.assertFalse(tracker.observe_success(15))  # Committed baseline prevents a repeat storm.
        self.assertTrue(tracker.observe_success(0))  # Reboot reset is one observed change.
        self.assertEqual(tracker.baseline, 0)
        tracker = TriggerEventTracker(UINT32_MAX)
        self.assertTrue(tracker.observe_success(0))  # uint32 wrap is one observed change.
        self.assertFalse(tracker.observe_success(0))

    def test_failed_http_poll_does_not_advance_the_event_baseline(self):
        tracker = TriggerEventTracker(12)
        self.server.status = 503
        with self.assertRaises(EspApiError) as failure:
            self.client.get_snapshot()
        self.assertEqual(failure.exception.kind, "http")
        tracker.record_failure()
        self.assertEqual(tracker.baseline, 12)

        self.server.status = 200
        self.server.payload = {"device": "esp32-bb84-sim-trigger", "trigger_count": 19}
        snapshot = self.client.get_snapshot()
        self.assertTrue(tracker.observe_success(snapshot.trigger_count))
        self.assertEqual(tracker.baseline, 19)

    def test_live_client_rejects_loopback_without_test_opt_in(self):
        with self.assertRaisesRegex(ValueError, "private LAN IPv4"):
            SimulationTriggerClient(f"http://127.0.0.1:{self.server.server_port}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
