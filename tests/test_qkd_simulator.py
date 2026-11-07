from __future__ import annotations

import unittest

from qkd_simulator import SIMULATED_LABEL, simulate_bb84


class QKDSimulatorTests(unittest.TestCase):
    def test_aer_runs_measurement_and_reports_all_bb84_steps(self):
        result = simulate_bb84(round_count=96, disturbance_percent=0, sample_size=8)
        self.assertEqual(len(result.rounds), 96)
        self.assertIn("simulated quantum measurement—not a real QRNG/QKD", SIMULATED_LABEL)
        self.assertTrue(all(record.alice_basis in ("X", "Z") for record in result.rounds))
        self.assertTrue(all(record.bob_basis in ("X", "Z") for record in result.rounds))
        self.assertEqual(
            tuple(i for i, record in enumerate(result.rounds) if record.bases_match),
            result.sifted_positions,
        )
        self.assertGreater(len(result.sifted_positions), 0)
        self.assertEqual(len(result.sample_positions), 8)
        self.assertEqual(len(set(result.sample_positions)), len(result.sample_positions))
        self.assertEqual(result.sample_qber, 0.0)
        for position in result.sifted_positions:
            record = result.rounds[position]
            self.assertEqual(record.alice_bit, record.bob_measurement)
        self.assertTrue(all(result.rounds[i].sampled_for_qber for i in result.sample_positions))
        self.assertIsNotNone(result.demo_bits)
        self.assertEqual(result.post_sample_alice_bits, result.post_sample_bob_bits)
        self.assertTrue(set(result.demo_bits).issubset({"0", "1"}))

    def test_classical_disturbance_changes_sample_qber_and_suppresses_demo_bits(self):
        result = simulate_bb84(round_count=96, disturbance_percent=100, sample_size=8)
        self.assertEqual(len(result.sample_positions), 8)
        self.assertEqual(result.sample_qber, 1.0)
        self.assertIsNone(result.demo_bits)

    def test_bounds_are_checked(self):
        for kwargs in (
            {"round_count": 0},
            {"round_count": True},
            {"round_count": 1025},
            {"disturbance_percent": -1},
            {"disturbance_percent": 101},
            {"sample_size": -1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                simulate_bb84(**kwargs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
