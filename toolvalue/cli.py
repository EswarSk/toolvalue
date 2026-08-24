from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from .analysis import render_report
from .demo import EXTERNAL_CALLS, run_demo
from .store import SQLiteStore


def _render_payload(payload: dict[str, Any]) -> str:
    width = 102
    eligible_cases = payload.get("eligible_cases", payload["cases"])
    baseline_eligibility = payload.get("baseline_eligibility", 1.0)
    attribution_coverage = payload.get("attribution_coverage", payload["replay_integrity"])
    lines = [
        "Agent Tool Value Profile",
        "─" * width,
        f"Task                         {payload['task']}",
        f"Cases                        {payload['cases']}",
        f"Eligible baselines           {eligible_cases}/{payload['cases']}",
        f"Observed baseline quality    {payload['baseline_quality']:>7.1%}",
        f"Baseline eligibility         {baseline_eligibility:>7.1%}",
        f"Average cost                 ${payload['average_cost']:>7.4f}",
        f"Replay integrity             {payload['replay_integrity']:>7.1%}",
        f"Attribution coverage         {attribution_coverage:>7.1%}",
        "",
        f"{'Tool':<20}{'Agent Δ':>12}{'Useful':>10}{'Evidence':>10}{'Coverage':>11}{'Recovery':>11}{'LLM +calls':>12}{'Cost':>12}",
        "─" * width,
    ]
    for tool in payload["tools"]:
        reliable = tool.get("attribution_reliable", True)
        delta = (
            f"{tool['mean_quality_delta']:+.1%}"
            if reliable and tool["mean_quality_delta"] is not None
            else "insufficient"
        )
        useful = (
            f"{tool['positive_rate']:.1%}"
            if reliable and tool["positive_rate"] is not None
            else "—"
        )
        coverage = tool.get("attribution_coverage", 1.0)
        recovery = tool.get("recovery_failure_rate", 0.0)
        model_calls = tool.get("avg_model_call_overhead", 0.0)
        evidence = f"{tool.get('independent_cases', tool.get('runs', 0))}c/{tool.get('runs', 0)}r"
        lines.append(
            f"{tool['unit']:<20}{delta:>12}{useful:>10}{evidence:>10}{coverage:>11.1%}"
            f"{recovery:>11.1%}{model_calls:>12.1f}  ${tool['avg_cost']:>9.4f}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="toolvalue", description="Profile the marginal value of agent tools")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run the bundled business-enrichment profile")
    demo.add_argument("--json", type=Path, help="Write the aggregate report as JSON")
    demo.add_argument("--store", type=Path, default=Path(".toolvalue/profiles.db"), help="SQLite metadata store")
    analyze = commands.add_parser("analyze", help="Render an existing JSON report")
    analyze.add_argument("report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "demo":
        with SQLiteStore(args.store) as store:
            report = asyncio.run(run_demo(store))
        print(render_report(report))
        baseline_external_calls = sum(EXTERNAL_CALLS.values())
        print(f"\nExternal calls made: {baseline_external_calls} (baseline only; replays were frozen)")
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(report.to_dict(), indent=2) + "\n")
            print(f"Report written to {args.json}")
        return 0
    payload = json.loads(args.report.read_text())
    print(_render_payload(payload))
    return 0
