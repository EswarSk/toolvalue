from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from .codec import json_safe


class RunMode(str, Enum):
    OBSERVE = "observe"
    RECORD = "record"
    REPLAY = "replay"


@dataclass(frozen=True)
class ToolUnavailable:
    reason: str = "counterfactual_ablation"
    tool_name: str | None = None

    def __bool__(self) -> bool:
        return False


@dataclass
class ToolInvocation:
    id: str
    run_id: str
    tool_name: str
    group: str
    arguments: dict[str, Any]
    arguments_hash: str
    result: Any
    result_hash: str | None
    cost: float
    duration_ms: float
    status: Literal["success", "failure", "unavailable"]
    error: str | None = None
    replayed: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["arguments"] = json_safe(self.arguments) if include_content else None
        data["result"] = json_safe(self.result) if include_content else None
        return data


@dataclass
class RunRecord:
    id: str
    task: str
    input_hash: str
    output: Any
    score: float | None
    score_components: dict[str, float]
    invocations: list[ToolInvocation]
    duration_ms: float
    metadata: dict[str, Any]
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def cost(self) -> float:
        return sum(invocation.cost for invocation in self.invocations if not invocation.replayed)

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "input_hash": self.input_hash,
            "output": json_safe(self.output) if include_content else None,
            "score": self.score,
            "score_components": self.score_components,
            "invocations": [item.to_dict(include_content=include_content) for item in self.invocations],
            "duration_ms": self.duration_ms,
            "cost": self.cost,
            "metadata": json_safe(self.metadata),
            "started_at": self.started_at,
        }


@dataclass
class CounterfactualRun:
    id: str
    baseline_run_id: str
    ablated_unit: str
    output: Any
    baseline_score: float
    counterfactual_score: float | None
    delta: float | None
    status: Literal["complete", "diverged", "failed"]
    invocations: list[ToolInvocation]
    duration_ms: float
    reason: str | None = None
    score_components: dict[str, float] = field(default_factory=dict)

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["output"] = json_safe(self.output) if include_content else None
        data["invocations"] = [item.to_dict(include_content=include_content) for item in self.invocations]
        return data


@dataclass
class CaseProfile:
    id: str
    task: str
    expected: Any
    baseline: RunRecord
    counterfactuals: list[CounterfactualRun]
    metadata: dict[str, Any]

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "expected": json_safe(self.expected) if include_content else None,
            "baseline": self.baseline.to_dict(include_content=include_content),
            "counterfactuals": [item.to_dict(include_content=include_content) for item in self.counterfactuals],
            "metadata": json_safe(self.metadata),
        }


@dataclass(frozen=True)
class EvalCase:
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    expected: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolAggregate:
    unit: str
    runs: int
    mean_quality_delta: float
    median_quality_delta: float
    positive_rate: float
    zero_value_rate: float
    harmful_rate: float
    divergence_rate: float
    avg_cost: float
    avg_latency_ms: float
    value_per_dollar: float | None
    confidence_interval_95: tuple[float, float] | None
    recommendation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ProfileReport:
    task: str
    cases: int
    baseline_quality: float
    average_cost: float
    average_latency_ms: float
    replay_integrity: float
    tools: list[ToolAggregate]
    profiles: list[CaseProfile] = field(default_factory=list, repr=False)

    def to_dict(self, *, include_profiles: bool = False, include_content: bool = False) -> dict[str, Any]:
        data = {
            "task": self.task,
            "cases": self.cases,
            "baseline_quality": self.baseline_quality,
            "average_cost": self.average_cost,
            "average_latency_ms": self.average_latency_ms,
            "replay_integrity": self.replay_integrity,
            "tools": [tool.to_dict() for tool in self.tools],
        }
        if include_profiles:
            data["profiles"] = [profile.to_dict(include_content=include_content) for profile in self.profiles]
        return data
