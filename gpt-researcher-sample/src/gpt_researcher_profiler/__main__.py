from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from toolvalue import EvalCase, SQLiteStore, render_report

from .agent import ProfiledResearchAgent, build_agent
from .dataset import PAPERS, BlindPaperEvaluation, generate_blind_evaluation
from .sources import PublicSourceClient, SOURCE_ORDER


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="profile-gpt-researcher",
        description="Measure scholarly-source value with the real GPT Researcher publisher",
    )
    parser.add_argument(
        "--backend",
        choices=("scripted", "gpt-researcher"),
        default="scripted",
        help="scripted consensus is free; gpt-researcher makes real OpenRouter calls",
    )
    parser.add_argument(
        "--sources",
        choices=("fixture", "public"),
        help="source mode; defaults to fixture for scripted and public for GPT Researcher",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        help="OpenRouter model used by GPT Researcher",
    )
    parser.add_argument("--limit", type=int, help="number of curated DOI cases")
    parser.add_argument("--blind-cases", type=int, help="number of randomly selected held-out DOI cases")
    parser.add_argument("--blind-seed", type=int, help="seed used to reproduce blind selection")
    parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="counterfactual repetitions per source and case (3+ recommended for a real LLM)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="dotenv file containing OPENROUTER_API_KEY",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=Path(".toolvalue/profiles.db"),
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=Path(".toolvalue/report.json"),
    )
    return parser


def _fixed_cases(limit: int) -> list[EvalCase]:
    return [
        EvalCase(
            args=(paper.doi,),
            expected=paper.expected,
            metadata={"paper_index": index},
        )
        for index, paper in enumerate(PAPERS[:limit], 1)
    ]


async def run(args: argparse.Namespace) -> tuple[ProfiledResearchAgent, object, BlindPaperEvaluation | None]:
    source_mode = args.sources or ("public" if args.backend == "gpt-researcher" else "fixture")
    source_client = PublicSourceClient() if source_mode == "public" else None
    blind: BlindPaperEvaluation | None = None
    if args.blind_cases is not None:
        blind = generate_blind_evaluation(args.blind_cases, seed=args.blind_seed)
        cases = blind.cases
    else:
        limit = args.limit if args.limit is not None else (1 if args.backend == "gpt-researcher" else len(PAPERS))
        if not 1 <= limit <= len(PAPERS):
            raise ValueError(f"--limit must be between 1 and {len(PAPERS)}")
        cases = _fixed_cases(limit)

    api_key = os.getenv("OPENROUTER_API_KEY") if args.backend == "gpt-researcher" else None
    with SQLiteStore(args.store) as store:
        agent = build_agent(
            source_client=source_client,
            source_mode=source_mode,
            writer_backend=args.backend,
            openrouter_api_key=api_key,
            openrouter_model_id=args.model,
            store=store,
        )
        report = await agent.evaluate(cases, trials=args.trials)
    return agent, report, blind


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(args.env_file, override=False)
    if args.trials < 1:
        print("--trials must be at least 1", file=sys.stderr)
        return 2
    if args.limit is not None and args.blind_cases is not None:
        print("Use either --limit or --blind-cases, not both", file=sys.stderr)
        return 2
    if args.backend == "gpt-researcher" and not os.getenv("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY is not set in the environment or --env-file", file=sys.stderr)
        return 2
    try:
        agent, report, blind = asyncio.run(run(args))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    cases = blind.cases if blind is not None else _fixed_cases(args.limit or (1 if args.backend == "gpt-researcher" else len(PAPERS)))
    expected_source_calls = len(cases) * len(SOURCE_ORDER)
    expected_model_runs = len(cases) + sum(len(profile.counterfactuals) for profile in report.profiles)

    print(f"GPT Researcher {agent.writer.package_version}")
    print(f"Writer backend: {agent.writer.name} ({agent.writer.model_id})")
    print(f"Source mode: {agent.source_mode} ({', '.join(SOURCE_ORDER)})")
    print(f"Counterfactual trials per source/case: {args.trials}")
    print(render_report(report))
    print("\nBaseline paper answers")
    for case, profile in zip(cases, report.profiles):
        outcome = profile.baseline.output
        answer = outcome.answer or {}
        validity = "eligible" if profile.baseline.valid else f"ineligible ({profile.baseline.invalid_reason})"
        print(
            f"  {case.args[0]:30} score={profile.baseline.score:.0%} {validity}\n"
            f"    title={answer.get('title')}\n"
            f"    year={answer.get('year')} first_author={answer.get('first_author')}"
        )
    if blind is not None:
        print(f"\nBlind answer reveal (seed={blind.seed})")
        for item in blind.reveal:
            print(
                f"  {item['index']}: DOI={item['doi']} year={item['year']} "
                f"first_author={item['first_author']} title={item['title']}"
            )

    print(
        f"\nPublic/fixture source executions: {agent.external_source_calls} observed / "
        f"{expected_source_calls} expected (baselines only)"
    )
    print(f"Research-writer model runs:       {agent.model_runs} observed / {expected_model_runs} expected")
    print(f"GPT Researcher reported cost:    {agent.reported_model_cost:.6f} credits")

    args.json.parent.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict(include_profiles=True, include_content=False)
    payload["experiment"] = {
        "upstream": "assafelovic/gpt-researcher",
        "upstream_version": agent.writer.package_version,
        "writer_backend": agent.writer.name,
        "model_id": agent.writer.model_id,
        "source_mode": agent.source_mode,
        "sources": list(SOURCE_ORDER),
        "source_executions": agent.external_source_calls,
        "model_runs": agent.model_runs,
        "reported_model_cost": agent.reported_model_cost,
        "counterfactual_trials": args.trials,
    }
    if blind is not None:
        payload["experiment"]["blind_seed"] = blind.seed
        payload["experiment"]["blind_answers"] = blind.reveal
    args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Report written to {args.json}")
    print(f"Profile metadata written to {args.store}")

    if report.replay_integrity != 1.0:
        print("Replay integrity check failed", file=sys.stderr)
        return 1
    if agent.external_source_calls != expected_source_calls:
        print("Source execution-count invariant failed", file=sys.stderr)
        return 1
    if agent.model_runs != expected_model_runs:
        print("Writer execution-count invariant failed", file=sys.stderr)
        return 1
    if any(
        len(profile.counterfactuals) != (len(SOURCE_ORDER) * args.trials if profile.baseline.valid else 0)
        for profile in report.profiles
    ):
        print("Baseline eligibility/counterfactual invariant failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
