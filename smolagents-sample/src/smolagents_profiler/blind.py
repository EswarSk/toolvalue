from __future__ import annotations

import itertools
import random
import secrets
from dataclasses import dataclass

from toolvalue import EvalCase


def incident_oracle(signals: dict[str, str]) -> str:
    """Independent ground-truth policy; its result is never passed to the agent."""
    deployment_high = signals["deployment"] == "high"
    telemetry_spiking = signals["telemetry"] == "spiking"
    if signals["runbook"] == "rollback" or (deployment_high and telemetry_spiking):
        return "rollback"
    if deployment_high or telemetry_spiking:
        return "investigate"
    return "healthy"


@dataclass(frozen=True)
class BlindEvaluation:
    seed: int
    fixtures: dict[str, dict[str, str]]
    cases: list[EvalCase]
    reveal: list[dict[str, str | int]]


def generate_blind_evaluation(count: int, *, seed: int | None = None) -> BlindEvaluation:
    """Sample unique unseen combinations and label them without consulting the agent."""
    combinations = list(
        itertools.product(
            ("low", "high"),
            ("normal", "spiking"),
            ("none", "rollback"),
        )
    )
    if not 1 <= count <= len(combinations):
        raise ValueError(f"count must be between 1 and {len(combinations)}")

    actual_seed = seed if seed is not None else secrets.randbits(63)
    generator = random.Random(actual_seed)
    selected = generator.sample(combinations, count)

    fixtures: dict[str, dict[str, str]] = {}
    cases: list[EvalCase] = []
    reveal: list[dict[str, str | int]] = []
    for index, (deployment, telemetry, runbook) in enumerate(selected, 1):
        service = f"blind-{index:02d}-{generator.getrandbits(24):06x}"
        signals = {
            "deployment": deployment,
            "telemetry": telemetry,
            "runbook": runbook,
            "oncall": f"rotation-{generator.randrange(100, 999)}",
        }
        expected = incident_oracle(signals)
        fixtures[service] = signals
        cases.append(
            EvalCase(
                args=(service,),
                expected=expected,
                metadata={"blind": True, "scenario_index": index},
            )
        )
        reveal.append(
            {
                "index": index,
                "service": service,
                **signals,
                "expected": expected,
            }
        )
    return BlindEvaluation(
        seed=actual_seed,
        fixtures=fixtures,
        cases=cases,
        reveal=reveal,
    )
