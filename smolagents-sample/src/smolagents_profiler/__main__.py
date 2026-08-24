from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import smolagents
from dotenv import load_dotenv
from toolvalue import SQLiteStore, render_report

from .agent import TOOL_ORDER, build_agent
from .blind import BlindEvaluation, generate_blind_evaluation
from .dataset import INCIDENTS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="profile-smolagents",
        description="Run ToolValue against a real Hugging Face smolagents ToolCallingAgent",
    )
    parser.add_argument(
        "--backend",
        choices=("scripted", "openrouter"),
        default="scripted",
        help="decision model backend; OpenRouter makes real LLM calls",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        help="OpenRouter model ID; must support tool calling",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="number of incidents; defaults to all scripted cases or one OpenRouter case",
    )
    parser.add_argument(
        "--blind-cases",
        type=int,
        help="generate 1-8 random held-out scenarios and reveal them only after the run",
    )
    parser.add_argument(
        "--blind-seed",
        type=int,
        help="optional reproduction seed for --blind-cases",
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
    project_env = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(project_env, override=False)
    args = build_parser().parse_args(argv)
    if args.blind_cases is not None and args.limit is not None:
        print("Use either --blind-cases or --limit, not both", file=sys.stderr)
        return 2
    blind_evaluation: BlindEvaluation | None = None
    if args.blind_cases is not None:
        try:
            blind_evaluation = generate_blind_evaluation(
                args.blind_cases,
                seed=args.blind_seed,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        cases = blind_evaluation.cases
        fixtures = blind_evaluation.fixtures
    else:
        limit = args.limit if args.limit is not None else (1 if args.backend == "openrouter" else len(INCIDENTS))
        if not 1 <= limit <= len(INCIDENTS):
            print(f"--limit must be between 1 and {len(INCIDENTS)}", file=sys.stderr)
            return 2
        cases = INCIDENTS[:limit]
        fixtures = None
    api_key = os.getenv("OPENROUTER_API_KEY") if args.backend == "openrouter" else None
    if args.backend == "openrouter" and not api_key:
        print(
            "OPENROUTER_API_KEY is not set. Export it in your shell; do not pass it as a CLI argument.",
            file=sys.stderr,
        )
        return 2
    with SQLiteStore(args.store) as store:
        agent_options = {
            "store": store,
            "model_backend": args.backend,
            "openrouter_api_key": api_key,
            "openrouter_model_id": args.model,
        }
        if fixtures is not None:
            agent_options["fixtures"] = fixtures
        agent = build_agent(
            **agent_options,
        )
        report = agent.evaluate(cases)

    tools_per_case = len(TOOL_ORDER)
    expected_tool_calls = len(cases) * tools_per_case
    expected_model_runs = len(cases) * (tools_per_case + 1) ** 2

    print(f"Hugging Face smolagents {smolagents.__version__}")
    print(f"Model backend: {agent.model_backend} ({agent.model_id})")
    print(render_report(report))
    print("\nBaseline incident decisions")
    for case, case_profile in zip(cases, report.profiles):
        print(
            f"  {case.args[0]:22} "
            f"predicted={case_profile.baseline.output:<12} "
            f"expected={case.expected:<12} "
            f"score={case_profile.baseline.score:.0%}"
        )
    if blind_evaluation is not None:
        print(f"\nBlind scenario reveal (seed={blind_evaluation.seed})")
        predictions = {
            case.args[0]: profile.baseline.output
            for case, profile in zip(cases, report.profiles)
        }
        for scenario in blind_evaluation.reveal:
            service = str(scenario["service"])
            print(
                f"  {scenario['index']}: {service} "
                f"deployment={scenario['deployment']} "
                f"telemetry={scenario['telemetry']} "
                f"runbook={scenario['runbook']} "
                f"predicted={predictions[service]} expected={scenario['expected']}"
            )
    print(
        f"\nFixture tool executions: {agent.external_tool_calls} observed / "
        f"{expected_tool_calls} expected (baselines only)"
    )
    if args.backend == "scripted":
        print(
            f"Scripted model calls:    {agent.model_runs} observed / "
            f"{expected_model_runs} expected (baseline + ablations)"
        )
    else:
        print(f"OpenRouter LLM calls:    {agent.model_runs}")
        print(f"OpenRouter input tokens: {agent.input_tokens}")
        print(f"OpenRouter output tokens:{agent.output_tokens:>6}")
        print(f"OpenRouter reported cost:{agent.model_cost:>9.6f} credits")

    args.json.parent.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict(include_profiles=True, include_content=False)
    payload["experiment"] = {
        "model_backend": agent.model_backend,
        "model_id": agent.model_id,
        "model_calls": agent.model_runs,
        "input_tokens": agent.input_tokens,
        "output_tokens": agent.output_tokens,
        "openrouter_reported_cost": agent.model_cost,
        "underlying_tool_executions": agent.external_tool_calls,
        "blind_evaluation": blind_evaluation is not None,
    }
    if blind_evaluation is not None:
        payload["experiment"]["blind_seed"] = blind_evaluation.seed
        payload["experiment"]["blind_scenarios"] = blind_evaluation.reveal
    args.json.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Report written to {args.json}")
    print(f"Profile metadata written to {args.store}")

    if report.replay_integrity != 1.0:
        print("Replay integrity check failed", file=sys.stderr)
        return 1
    if agent.external_tool_calls != expected_tool_calls:
        print("Execution-count invariant failed", file=sys.stderr)
        return 1
    if any(len(case.counterfactuals) != tools_per_case for case in report.profiles):
        print("Not every baseline called all four required tools", file=sys.stderr)
        return 1
    if args.backend == "scripted" and agent.model_runs != expected_model_runs:
        print("Scripted model-count invariant failed", file=sys.stderr)
        return 1
    if args.backend == "openrouter" and (agent.model_runs == 0 or agent.input_tokens == 0):
        print("No verifiable OpenRouter model usage was recorded", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
