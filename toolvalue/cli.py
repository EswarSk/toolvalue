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
    width = 74
    lines = [
        "Agent Tool Value Profile",
        "─" * width,
        f"Task                         {payload['task']}",
        f"Cases                        {payload['cases']}",
        f"Baseline quality             {payload['baseline_quality']:>7.1%}",
        f"Average cost                 ${payload['average_cost']:>7.4f}",
        f"Replay integrity             {payload['replay_integrity']:>7.1%}",
        "",
        f"{'Tool':<20}{'Quality Δ':>12}{'Useful':>10}{'Cost':>12}{'Value/$':>12}",
        "─" * width,
    ]
    for tool in payload["tools"]:
        ratio = "—" if tool["value_per_dollar"] is None else f"{tool['value_per_dollar']:.1f}"
        lines.append(f"{tool['unit']:<20}{tool['mean_quality_delta']:>+11.1%}{tool['positive_rate']:>10.1%}  ${tool['avg_cost']:>9.4f}{ratio:>12}")
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
