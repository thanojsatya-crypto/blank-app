"""Bounded software-only simulator for a 256-bit AOS teaching-key exercise.

This module is local simulation only. It performs no network, logging, or
persistence operations and makes no QKD, security, or compliance claim.
"""
from __future__ import annotations

from dataclasses import dataclass
import secrets

from qkd_simulator import MAX_TEACHING_QBER, simulate_bb84

AOS_KEY_ROUND_CAP = 1024
AOS_KEY_SAMPLE_BITS = 64
AOS_KEY_RETAINED_BITS = 256
AOS_KEY_SIMULATION_LABEL = "Software PRNG output — Simulation—not QKD"


@dataclass(frozen=True)
class AOSKeyDemoResult:
    """Transient accounting for one bounded AOS teaching-key attempt."""

    rounds_used: int
    round_cap: int
    matched_sifted_count: int
    sample_positions: tuple[int, ...]
    sample_alice_bits: str
    sample_bob_bits: str
    sample_error_count: int
    sample_qber: float | None
    post_sample_candidate_count: int
    retained_positions: tuple[int, ...]
    retained_bits: str | None
    success: bool
    status_message: str

    @property
    def retained_count(self) -> int:
        """Return the accepted output count; failed candidates are never retained."""
        return len(self.retained_bits or "")


def generate_aos_demo_key(
    *,
    round_cap: int = AOS_KEY_ROUND_CAP,
    disturbance_percent: int = 0,
) -> AOSKeyDemoResult:
    """Run at most ``round_cap`` rounds and retain exactly 256 bits or abort.

    Exactly 64 basis-matched positions are disclosed for the sample check. If
    the sample passes, exactly 256 positions are selected uniformly without
    replacement from the remaining matched positions before the output string
    is constructed. Excess candidates are not sliced into a key, padded, or
    reused; if the candidate pool is short, the attempt aborts without output.
    """
    if type(round_cap) is not int or not 1 <= round_cap <= AOS_KEY_ROUND_CAP:
        raise ValueError(f"round_cap must be an integer from 1 through {AOS_KEY_ROUND_CAP}")
    if type(disturbance_percent) is not int or not 0 <= disturbance_percent <= 100:
        raise ValueError("disturbance_percent must be an integer from 0 through 100")

    simulation = simulate_bb84(
        round_count=round_cap,
        disturbance_percent=disturbance_percent,
        sample_size=AOS_KEY_SAMPLE_BITS,
    )
    rounds_used = len(simulation.rounds)
    if rounds_used > round_cap:
        raise ValueError("simulator returned more rounds than the configured cap")

    matched_positions = tuple(simulation.sifted_positions)
    sample_positions = tuple(simulation.sample_positions)
    if len(set(matched_positions)) != len(matched_positions):
        raise ValueError("simulator returned duplicate sifted positions")
    if len(set(sample_positions)) != len(sample_positions):
        raise ValueError("simulator returned duplicate sample positions")
    if any(position not in matched_positions for position in sample_positions):
        raise ValueError("simulator returned a sample position that was not sifted")
    if any(type(position) is not int or not 0 <= position < rounds_used for position in matched_positions):
        raise ValueError("simulator returned an invalid sifted position")

    records = simulation.rounds
    sample_alice_bits = "".join(str(records[position].alice_bit) for position in sample_positions)
    sample_bob_bits = "".join(str(records[position].bob_measurement) for position in sample_positions)
    sample_error_count = sum(
        records[position].alice_bit != records[position].bob_measurement
        for position in sample_positions
    )
    sample_qber = sample_error_count / len(sample_positions) if sample_positions else None
    sampled = set(sample_positions)
    candidate_positions = tuple(position for position in matched_positions if position not in sampled)

    def abort(message: str) -> AOSKeyDemoResult:
        return AOSKeyDemoResult(
            rounds_used=rounds_used,
            round_cap=round_cap,
            matched_sifted_count=len(matched_positions),
            sample_positions=sample_positions,
            sample_alice_bits=sample_alice_bits,
            sample_bob_bits=sample_bob_bits,
            sample_error_count=sample_error_count,
            sample_qber=sample_qber,
            post_sample_candidate_count=len(candidate_positions),
            retained_positions=(),
            retained_bits=None,
            success=False,
            status_message=message,
        )

    if len(sample_positions) != AOS_KEY_SAMPLE_BITS:
        return abort(
            f"ABORT — only {len(sample_positions)} of the required {AOS_KEY_SAMPLE_BITS} "
            "matched sample bits were available; no key was retained."
        )
    if sample_qber is None or sample_qber > MAX_TEACHING_QBER:
        qber_text = "unavailable" if sample_qber is None else f"{sample_qber:.1%}"
        return abort(
            f"ABORT — disclosed sample QBER {qber_text} exceeds the illustrative "
            f"{MAX_TEACHING_QBER:.0%} teaching threshold; no key was retained."
        )
    if len(candidate_positions) < AOS_KEY_RETAINED_BITS:
        return abort(
            f"ABORT — only {len(candidate_positions)} post-sample matched candidates were available; "
            f"{AOS_KEY_RETAINED_BITS} are required. No padding or reuse; no key was retained."
        )

    # Select the exact output set before constructing bits; never slice a longer
    # key string down to size. Sorting preserves round order after selection.
    retained_positions = tuple(
        sorted(secrets.SystemRandom().sample(list(candidate_positions), AOS_KEY_RETAINED_BITS))
    )
    retained_alice_bits = "".join(str(records[position].alice_bit) for position in retained_positions)
    retained_bob_bits = "".join(str(records[position].bob_measurement) for position in retained_positions)
    if retained_alice_bits != retained_bob_bits:
        return abort(
            "ABORT — the selected retained bits disagree between simulated users; "
            "no key was retained."
        )

    return AOSKeyDemoResult(
        rounds_used=rounds_used,
        round_cap=round_cap,
        matched_sifted_count=len(matched_positions),
        sample_positions=sample_positions,
        sample_alice_bits=sample_alice_bits,
        sample_bob_bits=sample_bob_bits,
        sample_error_count=sample_error_count,
        sample_qber=sample_qber,
        post_sample_candidate_count=len(candidate_positions),
        retained_positions=retained_positions,
        retained_bits=retained_alice_bits,
        success=True,
        status_message="SUCCESS — exactly 256 post-sample bits retained in this app session.",
    )
