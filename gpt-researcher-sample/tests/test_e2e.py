from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gpt_researcher_profiler import PAPERS, build_agent, generate_blind_evaluation
from gpt_researcher_profiler.sources import FixtureSourceClient
from toolvalue import EvalCase, SQLiteStore


class GPTResearcherIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_pinned_upstream_package_imports(self) -> None:
        from gpt_researcher import GPTResearcher

        self.assertTrue(callable(GPTResearcher))

    async def test_blind_selection_is_reproducible_and_withholds_answers(self) -> None:
        first = generate_blind_evaluation(3, seed=20260824)
        second = generate_blind_evaluation(3, seed=20260824)

        self.assertEqual([case.args for case in first.cases], [case.args for case in second.cases])
        self.assertEqual(first.reveal, second.reveal)
        self.assertTrue(all("title" not in case.metadata for case in first.cases))

    async def test_source_results_are_frozen_and_open_citations_adds_unique_value(self) -> None:
        cases = [
            EvalCase(args=(paper.doi,), expected=paper.expected)
            for paper in PAPERS[:5]
        ]
        with tempfile.TemporaryDirectory() as directory:
            with SQLiteStore(Path(directory) / "profiles.db") as store:
                agent = build_agent(store=store)
                report = await agent.evaluate(cases)
                stored = store.profile_payloads("gpt_researcher_scholarly_source_review")

        self.assertEqual(report.baseline_quality, 1.0)
        self.assertEqual(report.baseline_eligibility, 1.0)
        self.assertEqual(report.replay_integrity, 1.0)
        self.assertEqual(report.attribution_coverage, 1.0)
        self.assertEqual(agent.external_source_calls, 20)
        self.assertEqual(agent.model_runs, 25)
        self.assertEqual(len(stored), 5)
        self.assertTrue(all(len(profile.counterfactuals) == 4 for profile in report.profiles))

        by_source = {item.unit: item for item in report.tools}
        self.assertAlmostEqual(by_source["open_citations"].mean_quality_delta or 0.0, 1 / 15)
        self.assertEqual(by_source["crossref"].mean_quality_delta, 0.0)
        self.assertEqual(by_source["openalex"].mean_quality_delta, 0.0)
        self.assertEqual(by_source["europe_pmc"].mean_quality_delta, 0.0)
        self.assertTrue(all(item.attribution_reliable for item in report.tools))
        self.assertIsNone(stored[0]["baseline"]["output"])

    async def test_repeated_trials_only_repeat_the_writer(self) -> None:
        paper = PAPERS[0]
        agent = build_agent()
        report = await agent.evaluate(
            [EvalCase(args=(paper.doi,), expected=paper.expected)],
            trials=3,
        )

        self.assertEqual(agent.external_source_calls, 4)
        self.assertEqual(agent.model_runs, 13)
        self.assertEqual(len(report.profiles[0].counterfactuals), 12)
        self.assertEqual(
            [item.trial for item in report.profiles[0].counterfactuals[:3]],
            [1, 2, 3],
        )

    async def test_source_fetch_error_invalidates_an_otherwise_correct_baseline(self) -> None:
        class FailingSourceClient(FixtureSourceClient):
            async def open_citations(self, doi: str) -> dict[str, object]:
                return {
                    "source": "open_citations",
                    "doi": doi,
                    "title": None,
                    "year": None,
                    "first_author": None,
                    "venue": None,
                    "url": None,
                    "error": "HTTPError: 429",
                }

        paper = PAPERS[2]
        agent = build_agent(source_client=FailingSourceClient())
        report = await agent.evaluate([EvalCase(args=(paper.doi,), expected=paper.expected)])
        profile = report.profiles[0]

        self.assertEqual(profile.baseline.score, 1.0)
        self.assertFalse(profile.baseline.valid)
        self.assertEqual(profile.baseline.invalid_reason, "source_fetch_error:open_citations")
        self.assertEqual(profile.counterfactuals, [])
        self.assertEqual(agent.external_source_calls, 4)
        self.assertEqual(agent.model_runs, 1)

    async def test_gpt_researcher_backend_requires_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "OPENROUTER_API_KEY"):
            build_agent(writer_backend="gpt-researcher")


if __name__ == "__main__":
    unittest.main()
