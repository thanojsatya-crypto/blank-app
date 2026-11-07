from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from qkd_simulator import BB84Result, RoundRecord
from simulation_trigger_client import SimulationTriggerClient, TriggerSnapshot
from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "key_generator.py"
TRIGGER_URL = "http://192.168.1.42"
TRIGGER_DEVICE = "esp32-bb84-sim-trigger"


def successful_result(demo_bits: str | None = None) -> BB84Result:
    record = RoundRecord(
        index=1,
        alice_bit=0,
        alice_basis="Z",
        bob_basis="Z",
        bob_measurement=0,
        bases_match=True,
        sifted=True,
        sampled_for_qber=False,
    )
    return BB84Result(
        rounds=(record,),
        sifted_positions=(0,),
        sample_positions=(),
        sample_error_count=0,
        sample_qber=None,
        post_sample_alice_bits="0",
        post_sample_bob_bits="0",
        demo_bits=demo_bits,
    )


class KeyGeneratorPendingFailureAppTests(unittest.TestCase):
    def make_app(self, baseline: int = 12) -> AppTest:
        app = AppTest.from_file(str(APP_PATH))
        # Match the app's default host so its host-change reset does not discard this baseline.
        app.session_state["trigger_host"] = TRIGGER_URL
        app.session_state["trigger_baseline"] = baseline
        app.run()
        return app

    def enable_polling(self, app: AppTest) -> None:
        polling_toggle = next(
            widget for widget in app.toggle
            if widget.label == "Enable automatic read-only PB4 polling"
        )
        polling_toggle.set_value(True).run()

    @staticmethod
    def error_text(app: AppTest) -> str:
        return " ".join(str(element.value) for element in app.error)

    @staticmethod
    def snapshot(count: int) -> TriggerSnapshot:
        return TriggerSnapshot(device=TRIGGER_DEVICE, trigger_count=count)

    def test_failure_is_visible_and_unchanged_polls_do_not_repeat_simulation(self):
        with (
            patch.object(SimulationTriggerClient, "get_snapshot", return_value=self.snapshot(13)),
            patch("qkd_simulator.simulate_bb84", side_effect=RuntimeError("Aer unavailable")) as simulate,
        ):
            app = self.make_app()
            self.enable_polling(app)

            self.assertEqual(simulate.call_count, 1)
            self.assertEqual(app.session_state["trigger_baseline"], 13)
            self.assertEqual(app.session_state["trigger_pending_failed_count"], 13)
            self.assertEqual(app.session_state["trigger_pending_failed_error"], "Aer unavailable")
            self.assertIn("PB4 simulation failed", self.error_text(app))
            self.assertIn("trigger_count=13", self.error_text(app))
            self.assertIn("Aer unavailable", self.error_text(app))
            self.assertIn("Retry failed PB4 simulation", [button.label for button in app.button])
            self.assertIn("Generate simulated rounds", [button.label for button in app.button])

            app.run()  # Another successful poll observes the same count.
            self.assertEqual(simulate.call_count, 1)
            self.assertEqual(app.session_state["trigger_pending_failed_count"], 13)
            self.assertIn("unchanged polls will not retry it", self.error_text(app))

    def test_manual_retry_success_clears_pending_failure_state(self):
        result = successful_result()
        with (
            patch.object(SimulationTriggerClient, "get_snapshot", return_value=self.snapshot(13)),
            patch(
                "qkd_simulator.simulate_bb84",
                side_effect=[RuntimeError("temporary Aer fault"), result],
            ) as simulate,
        ):
            app = self.make_app()
            self.enable_polling(app)
            self.assertEqual(simulate.call_count, 1)
            self.assertEqual(app.session_state["trigger_pending_failed_count"], 13)

            retry = next(button for button in app.button if button.label == "Retry failed PB4 simulation")
            retry.click().run()

            self.assertEqual(simulate.call_count, 2)
            self.assertIsNone(app.session_state["trigger_pending_failed_count"])
            self.assertIsNone(app.session_state["trigger_pending_failed_error"])
            self.assertIs(app.session_state["bb84_result"], result)
            self.assertIn("Retry succeeded for failed PB4 simulation", " ".join(item.value for item in app.success))
            self.assertNotIn("Retry failed PB4 simulation", [button.label for button in app.button])
            self.assertIn("Generate simulated rounds", [button.label for button in app.button])

    def test_new_counter_change_replaces_pending_count_and_attempts_once(self):
        current_count = [13]
        result_error = ["first Aer failure", "newest Aer failure"]

        def fail_with_latest_error(*_args, **_kwargs):
            raise RuntimeError(result_error.pop(0))

        with (
            patch.object(
                SimulationTriggerClient,
                "get_snapshot",
                side_effect=lambda: self.snapshot(current_count[0]),
            ),
            patch("qkd_simulator.simulate_bb84", side_effect=fail_with_latest_error) as simulate,
        ):
            app = self.make_app()
            self.enable_polling(app)
            self.assertEqual(simulate.call_count, 1)
            self.assertEqual(app.session_state["trigger_pending_failed_count"], 13)

            current_count[0] = 14
            app.run()

            self.assertEqual(simulate.call_count, 2)
            self.assertEqual(app.session_state["trigger_baseline"], 14)
            self.assertEqual(app.session_state["trigger_pending_failed_count"], 14)
            self.assertEqual(app.session_state["trigger_pending_failed_error"], "newest Aer failure")
            self.assertIn("trigger_count=14", self.error_text(app))


class KeyGeneratorLocalOnlyStatusAppTests(unittest.TestCase):
    def test_simulated_key_status_is_visible_and_explicitly_not_provisioned(self):
        app = AppTest.from_file(str(APP_PATH))
        app.session_state["bb84_result"] = successful_result("0")
        app.run()
        self.assertEqual(len(app.exception), 0, [item.value for item in app.exception])
        info_text = "\n".join(item.value for item in app.info)
        caption_text = "\n".join(item.value for item in app.caption)
        self.assertIn("simulated key generated; not provisioned to ESP", info_text)
        self.assertIn("local-only", caption_text)
        self.assertIn("no ESP key receipt, fingerprint, or transfer endpoint", caption_text)
        self.assertIn("Manual copy is only to the separate local demo app", caption_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
