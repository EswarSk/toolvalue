from __future__ import annotations

import math
import statistics
from collections import defaultdict

from .types import CaseProfile, ProfileReport, ToolAggregate


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _model_usage(invocations: list) -> tuple[int, float]:
    model_calls = [
        invocation
        for invocation in invocations
        if invocation.kind == "model" and not invocation.replayed
    ]
    return len(model_calls), sum(invocation.cost for invocation in model_calls)


def aggregate(
    profiles: list[CaseProfile],
    *,
    materiality: float = 0.01,
    optimization_threshold: float = 0.01,
    minimum_runs: int = 2,
    minimum_coverage: float = 0.8,
) -> ProfileReport:
    """Aggregate case profiles into task-level tool value knowledge."""
    if not profiles:
        raise ValueError("At least one case profile is required")

    task = profiles[0].task
    if any(profile.task != task for profile in profiles):
        raise ValueError("Cannot aggregate profiles from different tasks")

    deltas: dict[str, list[float]] = defaultdict(list)
    valid_case_ids: dict[str, set[str]] = defaultdict(set)
    attempts: dict[str, int] = defaultdict(int)
    divergences: dict[str, int] = defaultdict(int)
    recovery_failures: dict[str, int] = defaultdict(int)
    model_call_overheads: dict[str, list[float]] = defaultdict(list)
    model_cost_overheads: dict[str, list[float]] = defaultdict(list)
    costs: dict[str, list[float]] = defaultdict(list)
    latencies: dict[str, list[float]] = defaultdict(list)

    for profile in profiles:
        if not profile.baseline.valid:
            continue
        unit_costs: dict[str, float] = defaultdict(float)
        unit_latencies: dict[str, float] = defaultdict(float)
        for invocation in profile.baseline.invocations:
            if invocation.kind != "tool":
                continue
            unit_costs[invocation.group] += invocation.cost
            unit_latencies[invocation.group] += invocation.duration_ms
        for unit, value in unit_costs.items():
            costs[unit].append(value)
            latencies[unit].append(unit_latencies[unit])
        baseline_model_calls, baseline_model_cost = _model_usage(profile.baseline.invocations)
        for counterfactual in profile.counterfactuals:
            unit = counterfactual.ablated_unit
            attempts[unit] += 1
            counter_model_calls, counter_model_cost = _model_usage(counterfactual.invocations)
            model_call_overheads[unit].append(float(max(0, counter_model_calls - baseline_model_calls)))
            model_cost_overheads[unit].append(max(0.0, counter_model_cost - baseline_model_cost))
            if counterfactual.status == "diverged":
                divergences[unit] += 1
            elif counterfactual.status in {"invalid", "failed"}:
                recovery_failures[unit] += 1
            elif counterfactual.status == "complete" and counterfactual.delta is not None:
                deltas[unit].append(counterfactual.delta)
                valid_case_ids[unit].add(profile.id)

    aggregates: list[ToolAggregate] = []
    units = sorted(attempts)
    for unit in units:
        values = deltas[unit]
        avg_cost = _mean(costs[unit])
        mean_delta = _mean(values) if values else None
        positive_rate = (
            sum(value >= materiality for value in values) / len(values)
            if values
            else None
        )
        interval = None
        if len(values) >= 2:
            margin = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
            assert mean_delta is not None
            interval = (mean_delta - margin, mean_delta + margin)
        recommendation = None
        coverage = len(values) / attempts[unit]
        reliable = (
            coverage >= minimum_coverage
            and len(values) >= minimum_runs
            and len(valid_case_ids[unit]) >= 2
        )
        if (
            reliable
            and avg_cost > 0
            and interval is not None
            and interval[1] < optimization_threshold
        ):
            recommendation = "candidate_for_skip"
        aggregates.append(
            ToolAggregate(
                unit=unit,
                attempts=attempts[unit],
                runs=len(values),
                independent_cases=len(valid_case_ids[unit]),
                mean_quality_delta=mean_delta,
                median_quality_delta=statistics.median(values) if values else None,
                positive_rate=positive_rate,
                zero_value_rate=(sum(abs(value) < materiality for value in values) / len(values)) if values else None,
                harmful_rate=(sum(value <= -materiality for value in values) / len(values)) if values else None,
                divergence_rate=divergences[unit] / attempts[unit],
                recovery_failure_rate=recovery_failures[unit] / attempts[unit],
                attribution_coverage=coverage,
                attribution_reliable=reliable,
                avg_model_call_overhead=_mean(model_call_overheads[unit]),
                avg_model_cost_overhead=_mean(model_cost_overheads[unit]),
                avg_cost=avg_cost,
                avg_latency_ms=_mean(latencies[unit]),
                value_per_dollar=(mean_delta / avg_cost) if avg_cost and mean_delta is not None else None,
                confidence_interval_95=interval,
                recommendation=recommendation,
            )
        )

    aggregates.sort(
        key=lambda item: (
            not item.attribution_reliable,
            -(item.mean_quality_delta or 0.0) if item.attribution_reliable else 0.0,
            item.unit,
        )
    )
    total_attempts = sum(attempts.values())
    completed_attempts = sum(len(values) for values in deltas.values())
    eligible_cases = sum(profile.baseline.valid for profile in profiles)
    baseline_scores = [profile.baseline.score for profile in profiles if profile.baseline.score is not None]
    return ProfileReport(
        task=task,
        cases=len(profiles),
        eligible_cases=eligible_cases,
        baseline_quality=_mean([float(score) for score in baseline_scores]),
        baseline_eligibility=eligible_cases / len(profiles),
        average_cost=_mean([profile.baseline.cost for profile in profiles]),
        average_latency_ms=_mean([profile.baseline.duration_ms for profile in profiles]),
        replay_integrity=(total_attempts - sum(divergences.values())) / total_attempts if total_attempts else 1.0,
        attribution_coverage=completed_attempts / total_attempts if total_attempts else 0.0,
        tools=aggregates,
        profiles=profiles,
    )


def render_report(report: ProfileReport) -> str:
    width = 102
    lines = [
        "Agent Tool Value Profile",
        "─" * width,
        f"Task                         {report.task}",
        f"Cases                        {report.cases}",
        f"Eligible baselines           {report.eligible_cases}/{report.cases}",
        f"Observed baseline quality    {report.baseline_quality:>7.1%}",
        f"Baseline eligibility         {report.baseline_eligibility:>7.1%}",
        f"Average cost                 ${report.average_cost:>7.4f}",
        f"Average latency              {report.average_latency_ms:>7.0f} ms",
        f"Replay integrity             {report.replay_integrity:>7.1%}",
        f"Attribution coverage         {report.attribution_coverage:>7.1%}",
        f"Reliable tool estimates      {sum(tool.attribution_reliable for tool in report.tools)}/{len(report.tools)}",
        "",
        f"{'Tool':<20}{'Agent Δ':>12}{'Useful':>10}{'Evidence':>10}{'Coverage':>11}{'Recovery':>11}{'LLM +calls':>12}{'Cost':>12}",
        "─" * width,
    ]
    for tool in report.tools:
        delta = (
            f"{tool.mean_quality_delta:+.1%}"
            if tool.attribution_reliable and tool.mean_quality_delta is not None
            else "insufficient"
        )
        useful = (
            f"{tool.positive_rate:.1%}"
            if tool.attribution_reliable and tool.positive_rate is not None
            else "—"
        )
        lines.append(
            f"{tool.unit:<20}{delta:>12}{useful:>10}"
            f"{f'{tool.independent_cases}c/{tool.runs}r':>10}"
            f"{tool.attribution_coverage:>11.1%}{tool.recovery_failure_rate:>11.1%}"
            f"{tool.avg_model_call_overhead:>12.1f}  ${tool.avg_cost:>9.4f}"
        )
    candidates = [tool for tool in report.tools if tool.recommendation]
    if candidates:
        lines.extend(["", "Optimization candidates", "─" * width])
        for index, tool in enumerate(sorted(candidates, key=lambda item: item.avg_cost, reverse=True), 1):
            lines.append(
                f"{index}. {tool.unit}: ${tool.avg_cost:.4f}/run; "
                f"materially useful in {tool.positive_rate:.1%} of valid counterfactuals"
            )
    lines.extend([
        "",
        "Quality deltas exclude invalid recoveries; coverage shows how much attribution evidence was usable.",
        "Agent Δ is end-to-end sensitivity to missing output, not proof that the tool content is causal.",
    ])
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
