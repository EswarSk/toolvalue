from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import smolagents
from smolagents_profiler import INCIDENTS, build_agent
from toolvalue import SQLiteStore


class SmolagentsIntegrationTests(unittest.TestCase):
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
        self.assertEqual(report.replay_integrity, 1.0)
        self.assertEqual(len(stored), 5)
        self.assertTrue(all(len(case.counterfactuals) == 4 for case in report.profiles))
        self.assertTrue(
            all(
                case.baseline.output == fixture.expected
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
