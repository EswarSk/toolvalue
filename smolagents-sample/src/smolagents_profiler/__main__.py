from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import smolagents
from toolvalue import SQLiteStore, render_report

from .agent import TOOL_ORDER, build_agent
from .dataset import INCIDENTS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="profile-smolagents",
        description="Run ToolValue against a real Hugging Face smolagents ToolCallingAgent",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=Path(".toolvalue/profiles.db"),
        help="SQLite metadata store",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=Path(".toolvalue/report.json"),
        help="content-free JSON report destination",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with SQLiteStore(args.store) as store:
        agent = build_agent(store=store)
        report = agent.evaluate(INCIDENTS)

    tools_per_case = len(TOOL_ORDER)
    expected_tool_calls = len(INCIDENTS) * tools_per_case
    expected_model_runs = len(INCIDENTS) * (tools_per_case + 1) ** 2

    print(f"Hugging Face smolagents {smolagents.__version__}")
    print(render_report(report))
    print("\nBaseline incident decisions")
    for case, case_profile in zip(INCIDENTS, report.profiles):
        print(
            f"  {case.args[0]:22} "
            f"predicted={case_profile.baseline.output:<12} "
            f"expected={case.expected:<12} "
            f"score={case_profile.baseline.score:.0%}"
        )
    print(
        f"\nFixture tool executions: {agent.external_tool_calls} observed / "
        f"{expected_tool_calls} expected (baselines only)"
    )
    print(
        f"smolagents model calls:  {agent.model_runs} observed / "
        f"{expected_model_runs} expected (baseline + ablations)"
    )

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(report.to_dict(include_profiles=True, include_content=False), indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Report written to {args.json}")
    print(f"Profile metadata written to {args.store}")

    if report.replay_integrity != 1.0:
        print("Replay integrity check failed", file=sys.stderr)
        return 1
    if agent.external_tool_calls != expected_tool_calls or agent.model_runs != expected_model_runs:
        print("Execution-count invariant failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
