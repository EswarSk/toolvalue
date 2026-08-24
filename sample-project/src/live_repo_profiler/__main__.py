from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from toolvalue import SQLiteStore, render_report

from .agent import build_agent
from .client import GitHubAPIError, GitHubClient
from .dataset import DEFAULT_CASES


TOOLS_PER_CASE = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="profile-live-repos",
        description="Profile ToolValue against live public GitHub repository data",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=len(DEFAULT_CASES),
        help=f"number of labeled repositories to evaluate (1-{len(DEFAULT_CASES)})",
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
    parser.add_argument(
        "--request-cost-usd",
        type=float,
        default=0.0,
        help="internal accounting cost assigned to each GitHub request",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.limit <= len(DEFAULT_CASES):
        print(f"--limit must be between 1 and {len(DEFAULT_CASES)}", file=sys.stderr)
        return 2
    if args.request_cost_usd < 0:
        print("--request-cost-usd cannot be negative", file=sys.stderr)
        return 2

    cases = DEFAULT_CASES[: args.limit]
    client = GitHubClient()
    try:
        with SQLiteStore(args.store) as store:
            agent = build_agent(client, store=store, request_cost_usd=args.request_cost_usd)
            report = agent.evaluate(cases)
    except GitHubAPIError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    expected_network_calls = len(cases) * TOOLS_PER_CASE
    expected_model_runs = len(cases) * (TOOLS_PER_CASE + 1)
    print(render_report(report))
    print("\nLive baseline results")
    for case, profile in zip(cases, report.profiles):
        print(
            f"  {case.args[0]:28} "
            f"predicted={profile.baseline.output['category']:<24} "
            f"expected={case.expected:<24} score={profile.baseline.score:.3f}"
        )
    print(
        f"\nNetwork requests: {client.network_calls} observed / "
        f"{expected_network_calls} expected (baseline only)"
    )
    print(
        f"Decision runs:    {agent.model_runs} observed / "
        f"{expected_model_runs} expected (baseline + ablations)"
    )
    if client.rate_limit_remaining is not None:
        print(f"GitHub rate limit remaining: {client.rate_limit_remaining}")

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(
            report.to_dict(include_profiles=True, include_content=False),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Report written to {args.json}")
    print(f"Profile metadata written to {args.store}")

    if client.network_calls != expected_network_calls or agent.model_runs != expected_model_runs:
        print("Replay integrity check failed: observed call counts did not match", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
