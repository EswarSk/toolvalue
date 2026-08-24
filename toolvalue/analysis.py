from __future__ import annotations

import math
import statistics
from collections import defaultdict

from .types import CaseProfile, ProfileReport, ToolAggregate


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def aggregate(
    profiles: list[CaseProfile],
    *,
    materiality: float = 0.01,
    optimization_threshold: float = 0.01,
) -> ProfileReport:
    """Aggregate case profiles into task-level tool value knowledge."""
    if not profiles:
        raise ValueError("At least one case profile is required")

    task = profiles[0].task
    if any(profile.task != task for profile in profiles):
        raise ValueError("Cannot aggregate profiles from different tasks")

    deltas: dict[str, list[float]] = defaultdict(list)
    attempts: dict[str, int] = defaultdict(int)
    divergences: dict[str, int] = defaultdict(int)
    costs: dict[str, list[float]] = defaultdict(list)
    latencies: dict[str, list[float]] = defaultdict(list)

    for profile in profiles:
        unit_costs: dict[str, float] = defaultdict(float)
        unit_latencies: dict[str, float] = defaultdict(float)
        for invocation in profile.baseline.invocations:
            unit_costs[invocation.group] += invocation.cost
            unit_latencies[invocation.group] += invocation.duration_ms
        for unit, value in unit_costs.items():
            costs[unit].append(value)
            latencies[unit].append(unit_latencies[unit])
        for counterfactual in profile.counterfactuals:
            unit = counterfactual.ablated_unit
            attempts[unit] += 1
            if counterfactual.status == "diverged":
                divergences[unit] += 1
            elif counterfactual.status == "complete" and counterfactual.delta is not None:
                deltas[unit].append(counterfactual.delta)

    aggregates: list[ToolAggregate] = []
    units = sorted(attempts)
    for unit in units:
        values = deltas[unit]
        avg_cost = _mean(costs[unit])
        mean_delta = _mean(values)
        positive_rate = sum(value >= materiality for value in values) / max(1, len(values))
        interval = None
        if len(values) >= 2:
            margin = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
            interval = (mean_delta - margin, mean_delta + margin)
        recommendation = None
        if avg_cost > 0 and mean_delta < optimization_threshold:
            recommendation = "candidate_for_skip"
        elif avg_cost >= 0.005 and positive_rate < 0.25:
            recommendation = "candidate_for_conditional_skip"
        aggregates.append(
            ToolAggregate(
                unit=unit,
                runs=len(values),
                mean_quality_delta=mean_delta,
                median_quality_delta=statistics.median(values) if values else 0.0,
                positive_rate=positive_rate,
                zero_value_rate=sum(abs(value) < materiality for value in values) / max(1, len(values)),
                harmful_rate=sum(value <= -materiality for value in values) / max(1, len(values)),
                divergence_rate=divergences[unit] / max(1, attempts[unit]),
                avg_cost=avg_cost,
                avg_latency_ms=_mean(latencies[unit]),
                value_per_dollar=(mean_delta / avg_cost) if avg_cost else None,
                confidence_interval_95=interval,
                recommendation=recommendation,
            )
        )

    aggregates.sort(key=lambda item: item.mean_quality_delta, reverse=True)
    completed_attempts = sum(attempts.values()) - sum(divergences.values())
    baseline_scores = [profile.baseline.score for profile in profiles if profile.baseline.score is not None]
    return ProfileReport(
        task=task,
        cases=len(profiles),
        baseline_quality=_mean([float(score) for score in baseline_scores]),
        average_cost=_mean([profile.baseline.cost for profile in profiles]),
        average_latency_ms=_mean([profile.baseline.duration_ms for profile in profiles]),
        replay_integrity=completed_attempts / max(1, sum(attempts.values())),
        tools=aggregates,
        profiles=profiles,
    )


def render_report(report: ProfileReport) -> str:
    width = 74
    lines = [
        "Agent Tool Value Profile",
        "─" * width,
        f"Task                         {report.task}",
        f"Cases                        {report.cases}",
        f"Baseline quality             {report.baseline_quality:>7.1%}",
        f"Average cost                 ${report.average_cost:>7.4f}",
        f"Average latency              {report.average_latency_ms:>7.0f} ms",
        f"Replay integrity             {report.replay_integrity:>7.1%}",
        "",
        f"{'Tool':<20}{'Quality Δ':>12}{'Useful':>10}{'Cost':>12}{'Value/$':>12}",
        "─" * width,
    ]
    for tool in report.tools:
        value = "—" if tool.value_per_dollar is None else f"{tool.value_per_dollar:.1f}"
        lines.append(
            f"{tool.unit:<20}{tool.mean_quality_delta:>+11.1%}"
            f"{tool.positive_rate:>10.1%}  ${tool.avg_cost:>9.4f}{value:>12}"
        )
    candidates = [tool for tool in report.tools if tool.recommendation]
    if candidates:
        lines.extend(["", "Optimization candidates", "─" * width])
        for index, tool in enumerate(sorted(candidates, key=lambda item: item.avg_cost, reverse=True), 1):
            lines.append(
                f"{index}. {tool.unit}: ${tool.avg_cost:.4f}/run; "
                f"materially useful in {tool.positive_rate:.1%} of cases"
            )
    lines.extend(["", "Leave-one-out counterfactual value; recommendation only."])
    return "\n".join(lines)


def aggregate_by_metadata(
    profiles: list[CaseProfile], key: str, *, materiality: float = 0.01
) -> dict[str, ProfileReport]:
    """Build independent reports for a developer-provided metadata dimension."""
    grouped: dict[str, list[CaseProfile]] = defaultdict(list)
    for profile in profiles:
        if key in profile.metadata:
            grouped[str(profile.metadata[key])].append(profile)
    return {
        value: aggregate(items, materiality=materiality)
        for value, items in sorted(grouped.items())
    }
