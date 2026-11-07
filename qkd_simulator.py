"""Qiskit Aer implementation of a software-only BB84 teaching simulation."""
from __future__ import annotations

from dataclasses import dataclass
import secrets
from typing import Literal

from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator

SIMULATED_LABEL = "simulated quantum measurement—not a real QRNG/QKD"
MAX_TEACHING_QBER = 0.11
Basis = Literal["Z", "X"]


@dataclass(frozen=True)
class RoundRecord:
    """One simulated preparation-and-measurement round."""

    index: int
    alice_bit: int
    alice_basis: Basis
    bob_basis: Basis
    bob_measurement: int
    bases_match: bool
    sifted: bool
    sampled_for_qber: bool


@dataclass(frozen=True)
class BB84Result:
    """Transient simulator output; callers should render it with SIMULATED_LABEL."""

    rounds: tuple[RoundRecord, ...]
    sifted_positions: tuple[int, ...]
    sample_positions: tuple[int, ...]
    sample_error_count: int
    sample_qber: float | None
    post_sample_alice_bits: str
    post_sample_bob_bits: str
    demo_bits: str | None


def _circuit_for_round(alice_bit: int, alice_basis: Basis, bob_basis: Basis) -> QuantumCircuit:
    """Prepare one BB84 state, measure in Bob's chosen basis, and return a 1-bit circuit."""
    circuit = QuantumCircuit(1, 1)
    if alice_basis == "Z":
        if alice_bit:
            circuit.x(0)
    elif alice_basis == "X":
        # X|0> then H prepares |-> for bit 1; H|0> prepares |+> for bit 0.
        if alice_bit:
            circuit.x(0)
        circuit.h(0)
    else:
        raise ValueError("Alice basis must be 'Z' or 'X'")

    if bob_basis == "X":
        circuit.h(0)
    elif bob_basis != "Z":
        raise ValueError("Bob basis must be 'Z' or 'X'")
    circuit.measure(0, 0)
    return circuit


def simulate_bb84(
    round_count: int = 128,
    disturbance_percent: int = 0,
    sample_size: int = 8,
) -> BB84Result:
    """Run a BB84-style teaching demonstration on Qiskit Aer.

    The optional disturbance is a classical post-measurement bit-flip overlay, not
    a quantum channel, physical noise model, or eavesdropper simulation.
    """
    if type(round_count) is not int or not 1 <= round_count <= 1024:
        raise ValueError("round_count must be an integer from 1 through 1024")
    if type(disturbance_percent) is not int or not 0 <= disturbance_percent <= 100:
        raise ValueError("disturbance_percent must be an integer from 0 through 100")
    if type(sample_size) is not int or sample_size < 0:
        raise ValueError("sample_size must be a non-negative integer")

    alice_bits = [secrets.randbelow(2) for _ in range(round_count)]
    alice_bases: list[Basis] = [secrets.choice(("Z", "X")) for _ in range(round_count)]
    bob_bases: list[Basis] = [secrets.choice(("Z", "X")) for _ in range(round_count)]

    circuits = [
        _circuit_for_round(alice_bits[i], alice_bases[i], bob_bases[i])
        for i in range(round_count)
    ]
    backend = AerSimulator(method="stabilizer")
    compiled = transpile(circuits, backend, optimization_level=0)
    aer_result = backend.run(
        compiled,
        shots=1,
        memory=True,
        seed_simulator=secrets.randbits(32),
    ).result()
    raw_measurements = [
        int(str(aer_result.get_memory(i)[0]).replace(" ", "")[-1])
        for i in range(round_count)
    ]

    # This separate software overlay is intentionally shown as disturbance, not
    # described as behavior of a missing physical/quantum channel.
    bob_measurements = [
        bit ^ int(secrets.randbelow(100) < disturbance_percent)
        for bit in raw_measurements
    ]
    sifted_positions = tuple(i for i in range(round_count) if alice_bases[i] == bob_bases[i])
    chosen_sample_positions = tuple(
        sorted(secrets.SystemRandom().sample(list(sifted_positions), min(sample_size, len(sifted_positions))))
    )
    sample_set = set(chosen_sample_positions)
    sample_errors = sum(alice_bits[i] != bob_measurements[i] for i in chosen_sample_positions)
    sample_qber = sample_errors / len(chosen_sample_positions) if chosen_sample_positions else None

    remaining_positions = [i for i in sifted_positions if i not in sample_set]
    remaining_alice = "".join(str(alice_bits[i]) for i in remaining_positions)
    remaining_bob = "".join(str(bob_measurements[i]) for i in remaining_positions)
    demo_bits = None
    if (
        remaining_alice
        and remaining_alice == remaining_bob
        and sample_qber is not None
        and sample_qber <= MAX_TEACHING_QBER
    ):
        demo_bits = remaining_alice

    rounds = tuple(
        RoundRecord(
            index=i + 1,
            alice_bit=alice_bits[i],
            alice_basis=alice_bases[i],
            bob_basis=bob_bases[i],
            bob_measurement=bob_measurements[i],
            bases_match=alice_bases[i] == bob_bases[i],
            sifted=i in sifted_positions,
            sampled_for_qber=i in sample_set,
        )
        for i in range(round_count)
    )
    return BB84Result(
        rounds=rounds,
        sifted_positions=sifted_positions,
        sample_positions=chosen_sample_positions,
        sample_error_count=sample_errors,
        sample_qber=sample_qber,
        post_sample_alice_bits=remaining_alice,
        post_sample_bob_bits=remaining_bob,
        demo_bits=demo_bits,
    )
