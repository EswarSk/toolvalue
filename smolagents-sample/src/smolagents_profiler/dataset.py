from __future__ import annotations

from toolvalue import EvalCase


INCIDENT_FIXTURES: dict[str, dict[str, str]] = {
    "payments-api": {
        "deployment": "high",
        "telemetry": "spiking",
        "runbook": "none",
        "oncall": "payments-primary",
    },
    "checkout-api": {
        "deployment": "low",
        "telemetry": "normal",
        "runbook": "rollback",
        "oncall": "checkout-primary",
    },
    "search-api": {
        "deployment": "low",
        "telemetry": "spiking",
        "runbook": "none",
        "oncall": "search-primary",
    },
    "catalog-api": {
        "deployment": "high",
        "telemetry": "normal",
        "runbook": "none",
        "oncall": "catalog-primary",
    },
    "recommendations-api": {
        "deployment": "low",
        "telemetry": "normal",
        "runbook": "none",
        "oncall": "recommendations-primary",
    },
}


INCIDENTS = [
    EvalCase(args=("payments-api",), expected="rollback", metadata={"team": "payments"}),
    EvalCase(args=("checkout-api",), expected="rollback", metadata={"team": "checkout"}),
    EvalCase(args=("search-api",), expected="investigate", metadata={"team": "search"}),
    EvalCase(args=("catalog-api",), expected="investigate", metadata={"team": "catalog"}),
    EvalCase(args=("recommendations-api",), expected="healthy", metadata={"team": "recommendations"}),
]
