from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from unittest.mock import patch

from aos_key_demo import (
    AOS_KEY_RETAINED_BITS,
    AOS_KEY_ROUND_CAP,
    AOS_KEY_SAMPLE_BITS,
    AOSKeyDemoResult,
    generate_aos_demo_key,
)
from aos_key_transfer_adapter import AOSKeyTransferAdapter
from qkd_simulator import BB84Result, RoundRecord
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "key_generator.py"
PASSWORD = "Aa-_" * 8
KEY_BITS = "01" * 128
MESSAGE = "AOS 🌍"


def simulated_result(
    *, round_count: int = 400, matched_count: int = 380, sample_count: int = 64,
    sample_errors: int = 7, other_error_positions: tuple[int, ...] = (),
) -> BB84Result:
    sample_positions = tuple(range(sample_count))
    matched_positions = tuple(range(matched_count))
    rounds = []
    sample_error_set = set(sample_positions[:sample_errors])
    other_errors = set(other_error_positions)
    for position in range(round_count):
        matched = position in matched_positions
        alice_bit = position % 2
        bob_measurement = alice_bit ^ int(position in sample_error_set or position in other_errors)
        rounds.append(RoundRecord(
            index=position + 1,
            alice_bit=alice_bit,
            alice_basis="Z",
            bob_basis="Z" if matched else "X",
            bob_measurement=bob_measurement,
            bases_match=matched,
            sifted=matched,
            sampled_for_qber=position in sample_positions,
        ))
    qber = sample_errors / sample_count if sample_count else None
    return BB84Result(
        rounds=tuple(rounds), sifted_positions=matched_positions,
        sample_positions=sample_positions, sample_error_count=sample_errors,
        sample_qber=qber, post_sample_alice_bits="", post_sample_bob_bits="", demo_bits=None,
    )


def successful_key_result() -> AOSKeyDemoResult:
    return AOSKeyDemoResult(
        rounds_used=512,
        round_cap=1024,
        matched_sifted_count=400,
        sample_positions=tuple(range(64)),
        sample_alice_bits="0" * 64,
        sample_bob_bits="0" * 64,
        sample_error_count=7,
        sample_qber=7 / 64,
        post_sample_candidate_count=336,
        retained_positions=tuple(range(64, 320)),
        retained_bits=KEY_BITS,
        success=True,
        status_message="Simulated success.",
    )


class AOSKeyDemoPipelineTests(unittest.TestCase):
    def test_success_retains_exactly_256_unreused_post_sample_positions(self):
        source = simulated_result(sample_errors=7)
        with patch("aos_key_demo.simulate_bb84", return_value=source) as simulator:
            result = generate_aos_demo_key()
        simulator.assert_called_once_with(round_count=1024, disturbance_percent=0, sample_size=64)
        self.assertTrue(result.success)
        self.assertEqual(result.rounds_used, 400)
        self.assertEqual(result.round_cap, AOS_KEY_ROUND_CAP)
        self.assertEqual(result.matched_sifted_count, 380)
        self.assertEqual(len(result.sample_positions), AOS_KEY_SAMPLE_BITS)
        self.assertEqual(result.sample_error_count, 7)
        self.assertEqual(result.sample_qber, 7 / 64)
        self.assertEqual(result.post_sample_candidate_count, 316)
        self.assertEqual(result.retained_count, AOS_KEY_RETAINED_BITS)
        self.assertEqual(len(result.retained_bits or ""), AOS_KEY_RETAINED_BITS)
        self.assertEqual(len(result.retained_positions), AOS_KEY_RETAINED_BITS)
        self.assertEqual(len(set(result.retained_positions)), AOS_KEY_RETAINED_BITS)
        self.assertTrue(set(result.retained_positions).isdisjoint(result.sample_positions))
        self.assertTrue(set(result.retained_positions).issubset(set(source.sifted_positions)))
        self.assertEqual(result.retained_bits, "".join(str(source.rounds[i].alice_bit) for i in result.retained_positions))
        self.assertIn("exactly 256", result.status_message)

    def test_short_post_sample_pool_aborts_after_one_bounded_call_with_no_output(self):
        short_result = simulated_result(matched_count=200, sample_count=64, sample_errors=0)
        with patch("aos_key_demo.simulate_bb84", return_value=short_result) as simulator:
            result = generate_aos_demo_key(round_cap=AOS_KEY_ROUND_CAP)
        simulator.assert_called_once_with(round_count=1024, disturbance_percent=0, sample_size=64)
        self.assertFalse(result.success)
        self.assertEqual(result.post_sample_candidate_count, 136)
        self.assertIsNone(result.retained_bits)
        self.assertEqual(result.retained_count, 0)
        self.assertEqual(result.retained_positions, ())
        self.assertIn("ABORT", result.status_message)
        self.assertIn("no key was retained", result.status_message)

    def test_qber_is_recomputed_from_disclosed_sample_and_high_qber_aborts(self):
        with patch("aos_key_demo.simulate_bb84", return_value=simulated_result(sample_errors=8)):
            result = generate_aos_demo_key()
        self.assertEqual(result.sample_error_count, 8)
        self.assertEqual(result.sample_qber, 8 / 64)
        self.assertFalse(result.success)
        self.assertIsNone(result.retained_bits)
        self.assertIn("12.5%", result.status_message)

    def test_incomplete_64_bit_sample_aborts_even_when_partial_qber_is_low(self):
        with patch("aos_key_demo.simulate_bb84", return_value=simulated_result(matched_count=30, sample_count=30, sample_errors=0)):
            result = generate_aos_demo_key()
        self.assertEqual(len(result.sample_positions), 30)
        self.assertEqual(result.sample_qber, 0.0)
        self.assertFalse(result.success)
        self.assertIsNone(result.retained_bits)
        self.assertIn("30 of the required 64", result.status_message)

    def test_unsampled_disagreement_aborts_instead_of_retaining_mismatched_key(self):
        with patch("aos_key_demo.simulate_bb84", return_value=simulated_result(sample_errors=0, other_error_positions=tuple(range(64, 380)))):
            result = generate_aos_demo_key()
        self.assertFalse(result.success)
        self.assertIsNone(result.retained_bits)
        self.assertEqual(result.retained_count, 0)
        self.assertIn("selected retained bits disagree", result.status_message)

    def test_round_bound_and_input_validation_are_strict(self):
        for round_cap in (0, AOS_KEY_ROUND_CAP + 1, True):
            with self.subTest(round_cap=round_cap), self.assertRaises(ValueError):
                generate_aos_demo_key(round_cap=round_cap)
        with patch("aos_key_demo.simulate_bb84") as simulator:
            with self.assertRaises(ValueError):
                generate_aos_demo_key(disturbance_percent=True)
            simulator.assert_not_called()


class AOSKeyTransferBoundaryTests(unittest.TestCase):
    def test_only_key_generator_owns_provision_and_base_station_has_no_key_generation(self):
        adapter_source = Path(AOSKeyTransferAdapter.__module__.replace(".", "/") + ".py")
        import aos_key_transfer_adapter
        adapter_source = Path(aos_key_transfer_adapter.__file__).read_text(encoding="utf-8")
        self.assertIn("/api/aos-demo/provision", adapter_source)
        self.assertIn("/api/aos-demo/downlink", adapter_source)
        self.assertNotIn("/api/message", adapter_source)
        comm_source = (ROOT / "communication_base_station.py").read_text(encoding="utf-8")
        self.assertNotIn("generate_aos_demo_key", comm_source)
        self.assertNotIn("/api/aos-demo/provision", comm_source)
        self.assertIn("fetch_downlink(origin, password)", comm_source)
        self.assertIn('json={"password": password}', adapter_source)
        self.assertNotIn("DEMO-ONLY-PAIRING", comm_source)

    def test_aos_mode_is_separate_from_ordinary_esp_message_api(self):
        esp_source = (ROOT / "esp_api.py").read_text(encoding="utf-8")
        comm_source = (ROOT / "communication_base_station.py").read_text(encoding="utf-8")
        self.assertIn("/api/message", esp_source)
        self.assertNotIn("AOSKeyTransferAdapter", esp_source)
        self.assertNotIn("aos_key_demo", esp_source)
        self.assertIn("AOSKeyTransferAdapter", comm_source)
        self.assertIn("/api/message", comm_source)


class FakeResponse:
    status_code = 200
    headers = {"Content-Type": "application/json"}

    @staticmethod
    def json():
        return {"accepted": True, "provisioned": True}


class AOSKeyGeneratorUITests(unittest.TestCase):
    def make_app(self) -> AppTest:
        app = AppTest.from_file(str(APP_PATH), default_timeout=10).run()
        self.assertEqual(len(app.exception), 0, [item.value for item in app.exception])
        return app

    def select_aos_mode(self, app: AppTest) -> AppTest:
        next(widget for widget in app.radio if widget.label == "Key Generator mode").set_value(
            "CCSDS 355.0-B-2 AOS AES-256-GCM demo"
        )
        app.run()
        self.assertEqual(len(app.exception), 0, [item.value for item in app.exception])
        return app

    def test_default_mode_and_aos_mode_make_no_request_until_explicit_provision_click(self):
        with (
            patch("aos_key_transfer_adapter.requests.post") as post,
            patch("simulation_trigger_client.SimulationTriggerClient.get_snapshot") as poll,
        ):
            app = self.make_app()
            self.assertEqual(app.session_state["key_generator_mode"], "BB84 simulator")
            self.assertNotIn("Provision password + key + message to ESP once", [item.label for item in app.button])
            app = self.select_aos_mode(app)
            post.assert_not_called()
            poll.assert_not_called()
            self.assertIn("PLAIN-HTTP LAN EXPOSURE", " ".join(item.value for item in app.error))

    def test_explicit_generation_and_one_shot_provision_to_esp(self):
        from aos_key_demo_ui import AOS_KEY_STATE, PAIRING_PASSWORD_STATE, PROVISION_ATTEMPTED_STATE
        with (
            patch("aos_key_demo_ui.generate_aos_demo_key", return_value=successful_key_result()) as generate,
            patch("aos_key_demo_ui.generate_pairing_password", return_value=PASSWORD),
            patch("aos_key_transfer_adapter.requests.post", return_value=FakeResponse()) as post,
            patch("simulation_trigger_client.SimulationTriggerClient.get_snapshot") as poll,
        ):
            app = self.select_aos_mode(self.make_app())
            generate_button = next(item for item in app.button if item.label == "Generate fresh 256-bit AOS key + pairing password")
            generate_button.click().run()
            generate.assert_called_once()
            self.assertTrue(app.session_state[AOS_KEY_STATE].success)
            self.assertEqual(app.session_state[PAIRING_PASSWORD_STATE], PASSWORD)
            self.assertTrue(any(PASSWORD in str(item.value) for item in app.code))
            post.assert_not_called()

            next(item for item in app.text_area if item.label == "Message to encode and encrypt (UTF-8)").set_value(MESSAGE).run()
            next(item for item in app.checkbox if item.label.startswith("I understand that plain HTTP")).set_value(True).run()
            provision_button = next(item for item in app.button if item.label == "Provision password + key + message to ESP once")
            self.assertFalse(provision_button.disabled)
            provision_button.click().run()
            post.assert_called_once()
            self.assertEqual(post.call_args.args[0], "http://192.168.1.42/api/aos-demo/provision")
            self.assertEqual(set(post.call_args.kwargs["json"]), {"password", "key_hex", "message"})
            self.assertEqual(post.call_args.kwargs["json"]["password"], PASSWORD)
            self.assertEqual(post.call_args.kwargs["json"]["message"], MESSAGE)
            self.assertEqual(len(bytes.fromhex(post.call_args.kwargs["json"]["key_hex"])), 32)
            self.assertTrue(app.session_state[PROVISION_ATTEMPTED_STATE])
            self.assertTrue(next(item for item in app.button if item.label == "Provision password + key + message to ESP once").disabled)
            self.assertIn("accepted this password", " ".join(item.value for item in app.success))
            post.assert_called_once()
            poll.assert_not_called()

    def test_oversize_utf8_message_is_rejected_and_never_posted(self):
        with patch("aos_key_transfer_adapter.requests.post") as post:
            app = self.select_aos_mode(self.make_app())
            with patch("aos_key_demo_ui.generate_aos_demo_key", return_value=successful_key_result()), \
                 patch("aos_key_demo_ui.generate_pairing_password", return_value=PASSWORD):
                next(item for item in app.button if item.label == "Generate fresh 256-bit AOS key + pairing password").click().run()
            next(item for item in app.text_area if item.label == "Message to encode and encrypt (UTF-8)").set_value("é" * 16).run()
            self.assertTrue(next(item for item in app.button if item.label == "Provision password + key + message to ESP once").disabled)
            self.assertIn("Nothing was truncated", " ".join(item.value for item in app.error))
            post.assert_not_called()

    def test_profile_facts_and_volatile_reset_contract_are_visible(self):
        app = self.select_aos_mode(self.make_app())
        visible = " ".join(
            [item.value for item in app.caption]
            + [item.value for item in app.markdown]
            + [item.value for item in app.metric]
            + [item.value for item in app.warning]
            + [item.value for item in app.error]
        )
        for fact in (
            "256 bits / 32 octets", "96 bits / 12 octets", "128 bits / 16 octets",
            "69521234564a", "0x1234", "31 UTF-8 message octets", "hardware reset/reboot", "No NVS",
            "CCSDS-compliant satellite software", "trusted isolated lab network",
        ):
            with self.subTest(fact=fact):
                self.assertIn(fact, visible)


if __name__ == "__main__":
    unittest.main(verbosity=2)
