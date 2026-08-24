from __future__ import annotations

import asyncio
import json
import os
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Protocol

from toolvalue import (
    EvalCase,
    ProfileReport,
    RunValidationContext,
    ToolUnavailable,
    model as value_model,
    profile,
    tool as value_tool,
)
from toolvalue.store import Store

from .dataset import paper_question
from .sources import FixtureSourceClient, SOURCE_ORDER, SourceClient


def _normalized(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _parse_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


@dataclass(frozen=True)
class ResearchOutcome:
    answer: dict[str, Any] | None
    raw: str
    state: str
    reported_cost: float = 0.0


def score_answer(output: ResearchOutcome | Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, float]:
    answer = output.answer if isinstance(output, ResearchOutcome) else output
    answer = answer or {}
    title = float(_normalized(answer.get("title")) == _normalized(expected.get("title")))
    try:
        year = float(int(answer.get("year")) == int(expected.get("year")))
    except (TypeError, ValueError):
        year = 0.0
    author = float(
        _normalized(answer.get("first_author")) == _normalized(expected.get("first_author"))
    )
    return {
        "overall": (title + year + author) / 3,
        "title": title,
        "year": year,
        "first_author": author,
    }


def validate_research_run(context: RunValidationContext) -> str | None:
    if not isinstance(context.output, ResearchOutcome):
        return "missing_research_outcome"
    if context.output.state != "success":
        return f"researcher_state:{context.output.state}"
    counts = Counter(
        invocation.group
        for invocation in context.invocations
        if invocation.kind == "tool"
    )
    policy_errors = [f"{name}={counts[name]}" for name in SOURCE_ORDER if counts[name] != 1]
    if policy_errors:
        return f"source_policy_violation:{','.join(policy_errors)}"
    source_errors = [
        invocation.group
        for invocation in context.invocations
        if (
            invocation.kind == "tool"
            and invocation.status == "success"
            and isinstance(invocation.result, Mapping)
            and invocation.result.get("error")
        )
    ]
    if source_errors:
        return f"source_fetch_error:{','.join(sorted(source_errors))}"
    if context.phase == "baseline" and context.score < 1.0:
        return f"baseline_quality_below_threshold:{context.score:.3f}"
    return None


class ResearchWriter(Protocol):
    name: str
    model_id: str
    package_version: str

    async def write(self, question: str, records: list[dict[str, Any]]) -> ResearchOutcome: ...


def _consensus(records: list[dict[str, Any]], field: str) -> Any:
    candidates = [record.get(field) for record in records if record.get(field) not in (None, "")]
    if not candidates:
        return None
    if field == "year":
        keys = [str(value) for value in candidates]
    else:
        keys = [_normalized(value) for value in candidates]
    counts = Counter(keys)
    winner = max(counts, key=lambda item: (counts[item], -keys.index(item)))
    return candidates[keys.index(winner)]


class ScriptedResearchWriter:
    name = "scripted"
    model_id = "toolvalue/consensus-writer"

    def __init__(self) -> None:
        try:
            self.package_version = version("gpt-researcher")
        except PackageNotFoundError:
            self.package_version = "not-installed"

    async def write(self, question: str, records: list[dict[str, Any]]) -> ResearchOutcome:
        del question
        answer = {
            "title": _consensus(records, "title"),
            "year": _consensus(records, "year"),
            "first_author": _consensus(records, "first_author"),
        }
        return ResearchOutcome(
            answer=answer,
            raw=json.dumps(answer, ensure_ascii=False),
            state="success",
        )


class GPTResearcherWriter:
    name = "gpt-researcher"

    def __init__(self, *, api_key: str, model_id: str) -> None:
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required for the GPT Researcher backend")
        self.model_id = model_id
        self.package_version = version("gpt-researcher")
        os.environ["OPENROUTER_API_KEY"] = api_key
        os.environ["SMART_LLM"] = f"openrouter:{model_id}"
        os.environ["FAST_LLM"] = f"openrouter:{model_id}"
        os.environ["STRATEGIC_LLM"] = f"openrouter:{model_id}"
        os.environ.setdefault("EMBEDDING", "openrouter:openai/text-embedding-3-small")
        os.environ.setdefault("SMART_TOKEN_LIMIT", "256")
        os.environ.setdefault("FAST_TOKEN_LIMIT", "256")
        os.environ.setdefault("STRATEGIC_TOKEN_LIMIT", "256")
        os.environ.setdefault("IMAGE_GENERATION_ENABLED", "false")
        os.environ.setdefault("VERBOSE", "false")

    async def write(self, question: str, records: list[dict[str, Any]]) -> ResearchOutcome:
        context = "\n\n".join(
            f"SOURCE {record['source'].upper()}:\n{json.dumps(record, ensure_ascii=False, sort_keys=True)}"
            for record in records
        )
        prompt = (
            f"{question}\n\n"
            "Review and reconcile only the supplied source records. "
            "A nonempty field in even one supplied record is supporting evidence: copy it exactly, "
            "and never return null for a field when any record supplies that field. "
            "For year, use the peer-reviewed publication year rather than a preprint year. "
            "Return exactly one JSON object with keys title, year, and first_author. "
            "Use null when the records do not support a field. Do not add Markdown or commentary."
        )
        try:
            from gpt_researcher import GPTResearcher

            researcher = GPTResearcher(
                query=question,
                report_type="custom_report",
                report_source="static",
                agent="scholarly-source-reviewer",
                role="You reconcile scholarly database records without using unsupported prior knowledge.",
                context=context,
                verbose=False,
            )
            raw = await researcher.write_report(ext_context=context, custom_prompt=prompt)
            answer = _parse_json_object(raw)
            state = "success" if answer is not None else "invalid_json"
            return ResearchOutcome(
                answer=answer,
                raw=raw,
                state=state,
                reported_cost=float(researcher.get_costs() or 0.0),
            )
        except Exception as exc:
            return ResearchOutcome(
                answer=None,
                raw=f"{type(exc).__name__}: {exc}",
                state="writer_error",
            )


@dataclass
class ProfiledResearchAgent:
    function: Callable[..., Any]
    counters: dict[str, float]
    writer: ResearchWriter
    source_mode: str

    async def __call__(self, doi: str) -> ResearchOutcome:
        return await self.function(doi)

    async def evaluate(self, cases: list[EvalCase], *, trials: int | None = None) -> ProfileReport:
        return await self.function.evaluate(cases, trials=trials)

    @property
    def external_source_calls(self) -> int:
        return int(sum(self.counters[name] for name in SOURCE_ORDER))

    @property
    def model_runs(self) -> int:
        return int(self.counters["model"])

    @property
    def reported_model_cost(self) -> float:
        return float(self.counters["model_cost"])


def build_agent(
    *,
    source_client: SourceClient | None = None,
    source_mode: str = "fixture",
    writer_backend: str = "scripted",
    openrouter_api_key: str | None = None,
    openrouter_model_id: str = "openai/gpt-4o-mini",
    store: Store | None = None,
) -> ProfiledResearchAgent:
    if source_client is None:
        if source_mode != "fixture":
            raise ValueError("source_client is required when source_mode is not fixture")
        source_client = FixtureSourceClient()
    if writer_backend == "scripted":
        writer: ResearchWriter = ScriptedResearchWriter()
    elif writer_backend == "gpt-researcher":
        writer = GPTResearcherWriter(
            api_key=openrouter_api_key or "",
            model_id=openrouter_model_id,
        )
    else:
        raise ValueError(f"Unsupported writer backend: {writer_backend}")

    counters = {name: 0.0 for name in (*SOURCE_ORDER, "model", "model_cost")}

    @value_tool(name="crossref")
    async def crossref(doi: str) -> dict[str, Any]:
        counters["crossref"] += 1
        return await source_client.crossref(doi)

    @value_tool(name="openalex")
    async def openalex(doi: str) -> dict[str, Any]:
        counters["openalex"] += 1
        return await source_client.openalex(doi)

    @value_tool(name="open_citations")
    async def open_citations(doi: str) -> dict[str, Any]:
        counters["open_citations"] += 1
        return await source_client.open_citations(doi)

    @value_tool(name="europe_pmc")
    async def europe_pmc(doi: str) -> dict[str, Any]:
        counters["europe_pmc"] += 1
        return await source_client.europe_pmc(doi)

    @value_model(name="gpt_researcher_writer", cost=lambda output: output.reported_cost)
    async def synthesize(question: str, records: list[dict[str, Any]]) -> ResearchOutcome:
        counters["model"] += 1
        outcome = await writer.write(question, records)
        counters["model_cost"] += outcome.reported_cost
        return outcome

    profile_options: dict[str, Any] = {
        "task": "gpt_researcher_scholarly_source_review",
        "scorer": score_answer,
        "validator": validate_research_run,
    }
    if store is not None:
        profile_options["store"] = store

    @profile(**profile_options)
    async def research(doi: str) -> ResearchOutcome:
        observations = await asyncio.gather(
            crossref(doi),
            openalex(doi),
            open_citations(doi),
            europe_pmc(doi),
        )
        records = [
            observation
            for observation in observations
            if not isinstance(observation, ToolUnavailable)
        ]
        return await synthesize(paper_question(doi), records)

    return ProfiledResearchAgent(
        function=research,
        counters=counters,
        writer=writer,
        source_mode=source_mode,
    )
