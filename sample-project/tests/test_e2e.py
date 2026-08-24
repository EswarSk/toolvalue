from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from live_repo_profiler import DEFAULT_CASES, build_agent
from toolvalue import SQLiteStore


class FakeGitHubClient:
    def __init__(self) -> None:
        self.network_calls = 0

    def _count(self) -> None:
        self.network_calls += 1

    def repository_metadata(self, repository: str) -> dict:
        self._count()
        descriptions = {
            "django/django": "The web framework for perfectionists with deadlines.",
            "facebook/react": "The library for web and native user interfaces.",
        }
        return {"description": descriptions[repository], "primary_language": "Python"}

    def readme(self, repository: str) -> str:
        self._count()
        return {
            "django/django": "Django is a high-level Python web framework.",
            "facebook/react": "React makes it painless to create interactive user interfaces.",
        }[repository]

    def topics(self, repository: str) -> list[str]:
        self._count()
        return {
            "django/django": ["django", "web-framework"],
            "facebook/react": ["react", "ui-library"],
        }[repository]

    def languages(self, repository: str) -> dict[str, int]:
        self._count()
        return {"Python": 100} if repository == "django/django" else {"JavaScript": 100}


class LiveSampleEndToEndTests(unittest.TestCase):
    def test_baselines_hit_client_and_counterfactuals_only_rerun_model(self) -> None:
        client = FakeGitHubClient()
        cases = DEFAULT_CASES[:2]

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "profiles.db"
            with SQLiteStore(database) as store:
                agent = build_agent(client, store=store, request_cost_usd=.001)
                report = agent.evaluate(cases)
                stored = store.profile_payloads("github_repository_classification")

        self.assertEqual(client.network_calls, 8)
        self.assertEqual(agent.model_runs, 10)
        self.assertEqual(report.cases, 2)
        self.assertEqual(report.replay_integrity, 1.0)
        self.assertAlmostEqual(report.baseline_quality, 0.9925)
        self.assertEqual(len(stored), 2)
        self.assertEqual(
            {tool.unit for tool in report.tools},
            {"github_metadata", "github_readme", "github_topics", "github_languages"},
        )
        self.assertTrue(all(len(profile.counterfactuals) == 4 for profile in report.profiles))
        self.assertTrue(all(profile.baseline.output["category"] == case.expected for profile, case in zip(report.profiles, cases)))
        self.assertIsNone(stored[0]["baseline"]["output"])


if __name__ == "__main__":
    unittest.main()
