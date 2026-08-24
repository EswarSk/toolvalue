from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from toolvalue import EvalCase, ProfileReport, ToolUnavailable, model, profile, tool
from toolvalue.store import Store

from .client import GitHubClient


KEYWORDS: dict[str, tuple[str, ...]] = {
    "container_orchestration": (
        "kubernetes",
        "container orchestration",
        "container scheduling",
        "container management",
    ),
    "infrastructure_as_code": (
        "terraform",
        "infrastructure as code",
        "infrastructure automation",
    ),
    "observability": (
        "prometheus",
        "observability",
        "monitoring system",
        "time series database",
    ),
    "testing": (
        "playwright",
        "end-to-end test",
        "web testing",
        "browser automation",
        "testing and automation",
    ),
    "ui_library": (
        "react",
        "user interface",
        "ui library",
        "frontend library",
    ),
    "web_framework": (
        "django",
        "fastapi",
        "web framework",
        "web api framework",
    ),
    "data_science": (
        "pandas",
        "dataframe",
        "data analysis",
        "data science",
    ),
}


def _text(value: Any) -> str | None:
    if isinstance(value, ToolUnavailable):
        return None
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True).lower()
    if isinstance(value, (list, tuple, set)):
        return " ".join(str(item) for item in value).lower()
    return str(value).lower()


def _signals(text: str) -> Counter[str]:
    matches: Counter[str] = Counter()
    for category, keywords in KEYWORDS.items():
        matches[category] = sum(1 for keyword in keywords if keyword in text)
    return +matches


def score_classification(output: dict[str, Any], expected: str) -> dict[str, float]:
    """Favor the right label while rewarding independently grounded confidence."""
    accurate = float(output["category"] == expected)
    confidence = float(output["confidence"]) if accurate else 0.0
    return {
        "overall": 0.85 * accurate + 0.15 * confidence,
        "label_accuracy": accurate,
        "grounded_confidence": confidence,
    }


@dataclass
class RepositoryAgent:
    """Callable facade exposing profiling methods and observable sample counters."""

    function: Callable[..., dict[str, Any]]
    client: GitHubClient
    counters: dict[str, int]

    def __call__(self, repository: str) -> dict[str, Any]:
        return self.function(repository)

    def profile_case(self, repository: str, *, expected: str, metadata: dict[str, Any] | None = None):
        return self.function.profile_case(repository, expected=expected, metadata=metadata)

    def evaluate(self, cases: list[EvalCase]) -> ProfileReport:
        return self.function.evaluate(cases)

    @property
    def model_runs(self) -> int:
        return self.counters["model"]


def build_agent(
    client: GitHubClient,
    *,
    store: Store | None = None,
    request_cost_usd: float = 0.0,
    decision_cost_usd: float = 0.0,
) -> RepositoryAgent:
    """Build an agent around an injectable client without hardcoded runtime state."""
    counters = {"model": 0}

    @tool(name="github_metadata", cost=request_cost_usd)
    def fetch_metadata(repository: str) -> dict[str, Any]:
        return client.repository_metadata(repository)

    @tool(name="github_readme", cost=request_cost_usd)
    def fetch_readme(repository: str) -> str:
        return client.readme(repository)

    @tool(name="github_topics", cost=request_cost_usd)
    def fetch_topics(repository: str) -> list[str]:
        return client.topics(repository)

    @tool(name="github_languages", cost=request_cost_usd)
    def fetch_languages(repository: str) -> dict[str, int]:
        return client.languages(repository)

    @model(name="repository_classifier", cost=decision_cost_usd)
    def decide(metadata: Any, readme: Any, topics: Any, languages: Any) -> dict[str, Any]:
        counters["model"] += 1
        sources = {
            "metadata": _text(metadata),
            "readme": _text(readme),
            "topics": _text(topics),
            "languages": _text(languages),
        }
        aggregate_signals: Counter[str] = Counter()
        supporting_sources: dict[str, set[str]] = defaultdict(set)
        available_sources: list[str] = []
        for source, text in sources.items():
            if text is None:
                continue
            available_sources.append(source)
            for category, count in _signals(text).items():
                aggregate_signals[category] += count
                supporting_sources[category].add(source)

        if not aggregate_signals:
            return {
                "category": "unknown",
                "confidence": 0.0,
                "supporting_sources": [],
                "available_sources": available_sources,
            }

        category, total_matches = aggregate_signals.most_common(1)[0]
        support = sorted(supporting_sources[category])
        confidence = min(0.99, 0.35 + 0.16 * len(support) + 0.03 * min(total_matches, 8))
        return {
            "category": category,
            "confidence": round(confidence, 3),
            "supporting_sources": support,
            "available_sources": available_sources,
        }

    profile_options: dict[str, Any] = {
        "task": "github_repository_classification",
        "scorer": score_classification,
    }
    if store is not None:
        profile_options["store"] = store

    @profile(**profile_options)
    def classify(repository: str) -> dict[str, Any]:
        return decide(
            fetch_metadata(repository),
            fetch_readme(repository),
            fetch_topics(repository),
            fetch_languages(repository),
        )

    return RepositoryAgent(function=classify, client=client, counters=counters)
