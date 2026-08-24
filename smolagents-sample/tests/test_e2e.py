from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import smolagents
from smolagents_profiler import INCIDENTS, build_agent, generate_blind_evaluation, incident_oracle
from smolagents_profiler.agent import _openrouter_response_cost
from toolvalue import SQLiteStore


class SmolagentsIntegrationTests(unittest.TestCase):
    def test_blind_scenarios_are_unique_oracle_labeled_and_not_in_agent_input(self) -> None:
        evaluation = generate_blind_evaluation(5, seed=20260824)
        signal_combinations = {
            (item["deployment"], item["telemetry"], item["runbook"])
            for item in evaluation.reveal
        }
        self.assertEqual(len(signal_combinations), 5)
        for case, scenario in zip(evaluation.cases, evaluation.reveal):
            service = case.args[0]
            self.assertEqual(case.args, (scenario["service"],))
            self.assertNotIn("expected", case.metadata)
            self.assertEqual(case.expected, incident_oracle(evaluation.fixtures[service]))

        agent = build_agent(fixtures=evaluation.fixtures)
        report = agent.evaluate(evaluation.cases[:3])
        self.assertEqual(report.baseline_quality, 1.0)
        self.assertEqual(agent.external_tool_calls, 12)

    def test_openrouter_cost_is_read_from_usage_metadata(self) -> None:
        message = SimpleNamespace(raw=SimpleNamespace(usage=SimpleNamespace(cost=.0042)))
        self.assertEqual(_openrouter_response_cost(message), .0042)

    def test_openrouter_backend_requires_environment_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "OPENROUTER_API_KEY"):
            build_agent(model_backend="openrouter")

    def test_openrouter_backend_constructs_without_making_a_request(self) -> None:
        agent = build_agent(
            model_backend="openrouter",
            openrouter_api_key="test-key-that-is-never-sent",
            openrouter_model_id="openai/gpt-4o-mini",
        )
        self.assertEqual(agent.model_backend, "openrouter")
        self.assertEqual(agent.model_id, "openai/gpt-4o-mini")
        self.assertEqual(agent.model_runs, 0)

    def test_real_toolcalling_agent_is_profiled_without_reexecuting_tools(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "profiles.db"
            with SQLiteStore(database) as store:
                agent = build_agent(store=store)
                report = agent.evaluate(INCIDENTS)
                stored = store.profile_payloads("smolagents_incident_triage")

        self.assertEqual(smolagents.__version__, "1.26.0")
        self.assertEqual(agent.external_tool_calls, 20)
        self.assertEqual(agent.model_runs, 125)
        self.assertEqual(report.cases, 5)
        self.assertEqual(report.baseline_quality, 1.0)
        self.assertEqual(report.baseline_eligibility, 1.0)
        self.assertEqual(report.replay_integrity, 1.0)
        self.assertEqual(report.attribution_coverage, 1.0)
        self.assertEqual(len(stored), 5)
        self.assertTrue(all(len(case.counterfactuals) == 4 for case in report.profiles))
        self.assertTrue(
            all(
                case.baseline.output.answer == fixture.expected
                for case, fixture in zip(report.profiles, INCIDENTS)
            )
        )

        by_tool = {item.unit: item for item in report.tools}
        self.assertEqual(by_tool["deployment_signal"].mean_quality_delta, 0.4)
        self.assertEqual(by_tool["telemetry_signal"].mean_quality_delta, 0.4)
        self.assertEqual(by_tool["runbook_signal"].mean_quality_delta, 0.2)
        self.assertEqual(by_tool["oncall_signal"].mean_quality_delta, 0.0)
        self.assertIsNone(stored[0]["baseline"]["output"])


if __name__ == "__main__":
    unittest.main()
