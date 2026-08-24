from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from toolvalue import EvalCase, SQLiteStore, ToolUnavailable, middleware, model, profile, tool


class AsyncProfilerTests(unittest.IsolatedAsyncioTestCase):
    async def test_plain_call_stays_plain_and_records_observation(self) -> None:
        @tool(cost=.001)
        async def lookup(value: str) -> str:
            return value.upper()

        @profile(task="observe_only")
        async def agent(value: str) -> str:
            return await lookup(value)

        self.assertEqual(await agent("acme"), "ACME")
        self.assertEqual(len(agent.toolvalue_store.runs), 1)
        self.assertEqual(agent.toolvalue_store.runs[0].score, None)

    async def test_records_once_and_replays_without_external_calls(self) -> None:
        calls = {"homepage": 0, "reviews": 0}

        @tool(cost=.002)
        async def homepage(_: str) -> dict:
            calls["homepage"] += 1
            return {"industry": "Plumbing"}

        @tool(cost=.007)
        async def reviews(_: str) -> dict:
            calls["reviews"] += 1
            return {"industry": "Home services"}

        def scorer(output: str, expected: str) -> float:
            return float(output == expected)

        @profile(task="industry", scorer=scorer)
        async def classify(name: str) -> str:
            home = await homepage(name)
            review = await reviews(name)
            if not isinstance(home, ToolUnavailable):
                return home["industry"]
            if not isinstance(review, ToolUnavailable):
                return review["industry"]
            return "Unknown"

        result = await classify.profile_case("ABC Plumbing", expected="Plumbing")
        self.assertEqual(calls, {"homepage": 1, "reviews": 1})
        self.assertEqual(result.baseline.score, 1.0)
        by_tool = {item.ablated_unit: item for item in result.counterfactuals}
        self.assertEqual(by_tool["homepage"].delta, 1.0)
        self.assertEqual(by_tool["reviews"].delta, 0.0)
        self.assertEqual(by_tool["homepage"].status, "complete")

    async def test_strict_replay_marks_unseen_call_as_diverged(self) -> None:
        @tool
        async def homepage(_: str):
            return {"industry": "Legal services"}

        @tool
        async def search(query: str):
            return {"industry": query}

        @profile(task="strict_replay", scorer=lambda output, expected: float(output == expected))
        async def agent(name: str) -> str:
            home = await homepage(name)
            if isinstance(home, ToolUnavailable):
                result = await search("new query not present in baseline")
                return result["industry"]
            return home["industry"]

        result = await agent.profile_case("Harbor & Finch", expected="Legal services")
        counterfactual = result.counterfactuals[0]
        self.assertEqual(counterfactual.status, "diverged")
        self.assertEqual(counterfactual.reason, "unseen_tool_call:search")

    async def test_dataset_aggregation_finds_waste(self) -> None:
        @tool(cost=.002)
        async def useful(value: str) -> str:
            return value

        @tool(cost=.020)
        async def waste(_: str) -> str:
            return "unused"

        @profile(task="aggregate", scorer=lambda output, expected: float(output == expected))
        async def agent(value: str) -> str:
            first = await useful(value)
            await waste(value)
            return "Unknown" if isinstance(first, ToolUnavailable) else first

        report = await agent.evaluate([EvalCase(args=("A",), expected="A"), EvalCase(args=("B",), expected="B")])
        tools = {item.unit: item for item in report.tools}
        self.assertEqual(tools["useful"].mean_quality_delta, 1.0)
        self.assertEqual(tools["waste"].mean_quality_delta, 0.0)
        self.assertEqual(tools["waste"].recommendation, "candidate_for_skip")
        self.assertEqual(report.replay_integrity, 1.0)

    async def test_repeated_calls_replay_by_occurrence_and_groups_ablate_together(self) -> None:
        calls = {"page": 0, "registry": 0}

        @tool(group="web")
        async def page(value: str) -> str:
            calls["page"] += 1
            return value

        @tool(group="registry")
        async def registry(value: str) -> str:
            calls["registry"] += 1
            return value

        @profile(task="groups", scorer=lambda output, expected: float(output == expected))
        async def agent(value: str) -> str:
            first = await page(value)
            second = await page(value)
            await registry(value)
            if isinstance(first, ToolUnavailable) or isinstance(second, ToolUnavailable):
                return "Unknown"
            return first

        result = await agent.profile_case("correct", expected="correct")
        self.assertEqual(calls, {"page": 2, "registry": 1})
        self.assertEqual({item.ablated_unit for item in result.counterfactuals}, {"web", "registry"})
        by_unit = {item.ablated_unit: item for item in result.counterfactuals}
        self.assertEqual(by_unit["web"].delta, 1.0)
        self.assertEqual(by_unit["registry"].delta, 0.0)


class SyncProfilerTests(unittest.TestCase):
    def test_model_reruns_while_external_tools_only_run_in_baseline(self) -> None:
        calls = {"metadata": 0, "readme": 0, "decision": 0}

        @tool
        def metadata(_: str) -> str:
            calls["metadata"] += 1
            return "python"

        @tool
        def readme(_: str) -> str:
            calls["readme"] += 1
            return "a web framework"

        @model(cost=.003)
        def decide(language: object, description: object) -> str:
            calls["decision"] += 1
            if isinstance(description, ToolUnavailable):
                return "unknown"
            return "web_framework"

        @profile(task="rerunnable_model", scorer=lambda output, expected: float(output == expected))
        def agent(repository: str) -> str:
            return decide(metadata(repository), readme(repository))

        result = agent.profile_case("example/repo", expected="web_framework")

        self.assertEqual(calls, {"metadata": 1, "readme": 1, "decision": 3})
        self.assertEqual(
            {item.ablated_unit for item in result.counterfactuals},
            {"metadata", "readme"},
        )
        self.assertEqual(result.baseline.cost, .003)
        self.assertEqual(
            [item.kind for item in result.baseline.invocations],
            ["tool", "tool", "model"],
        )
        self.assertTrue(
            all(
                any(invocation.kind == "model" and not invocation.replayed for invocation in counter.invocations)
                for counter in result.counterfactuals
            )
        )

    def test_sync_function_and_registry_middleware(self) -> None:
        wrapped = middleware().wrap("directory", lambda name: {"name": name}, cost=.001)

        @profile(task="sync", scorer=lambda output, expected: float(output == expected))
        def agent(name: str) -> str:
            result = wrapped(name)
            return "Unknown" if isinstance(result, ToolUnavailable) else result["name"]

        result = agent.profile_case("Acme", expected="Acme")
        self.assertEqual(result.counterfactuals[0].delta, 1.0)

    def test_invalid_baseline_is_ineligible_and_skips_counterfactuals(self) -> None:
        calls = {"lookup": 0}

        @tool
        def lookup(value: str) -> str:
            calls["lookup"] += 1
            return value

        @profile(
            task="invalid_baseline",
            scorer=lambda output, expected: float(output == expected),
            validator=lambda context: "baseline_policy_failed" if context.phase == "baseline" else None,
        )
        def agent(value: str) -> str:
            return lookup(value)

        report = agent.evaluate([EvalCase(args=("correct",), expected="correct")])

        self.assertEqual(calls["lookup"], 1)
        self.assertFalse(report.profiles[0].baseline.valid)
        self.assertEqual(report.profiles[0].baseline.invalid_reason, "baseline_policy_failed")
        self.assertEqual(report.profiles[0].counterfactuals, [])
        self.assertEqual(report.eligible_cases, 0)
        self.assertEqual(report.baseline_eligibility, 0.0)
        self.assertEqual(report.attribution_coverage, 0.0)

    def test_invalid_recovery_is_excluded_from_delta_and_reports_model_overhead(self) -> None:
        @tool
        def evidence(_: str) -> str:
            return "signal"

        @model
        def decide(value: object) -> str:
            return "unknown" if isinstance(value, ToolUnavailable) else "correct"

        @profile(
            task="invalid_recovery",
            scorer=lambda output, expected: float(output == expected),
            validator=lambda context: "retry_policy_failed" if context.phase == "counterfactual" else None,
        )
        def agent(value: str) -> str:
            observation = evidence(value)
            first = decide(observation)
            if isinstance(observation, ToolUnavailable):
                decide(observation)
            return first

        report = agent.evaluate([EvalCase(args=("case",), expected="correct")], trials=3)
        counterfactual = report.profiles[0].counterfactuals[0]
        aggregate = report.tools[0]

        self.assertEqual([item.trial for item in report.profiles[0].counterfactuals], [1, 2, 3])
        self.assertEqual(counterfactual.status, "invalid")
        self.assertEqual(counterfactual.reason, "retry_policy_failed")
        self.assertIsNone(counterfactual.delta)
        self.assertEqual(aggregate.attempts, 3)
        self.assertEqual(aggregate.runs, 0)
        self.assertIsNone(aggregate.mean_quality_delta)
        self.assertEqual(aggregate.recovery_failure_rate, 1.0)
        self.assertEqual(aggregate.attribution_coverage, 0.0)
        self.assertEqual(aggregate.avg_model_call_overhead, 1.0)
        self.assertIsNone(aggregate.recommendation)

    def test_sqlite_store_defaults_to_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.db"
            with SQLiteStore(path) as store:
                @tool
                def lookup(value: str) -> str:
                    return value

                @profile(task="stored", scorer=lambda output, expected: float(output == expected), store=store)
                def agent(value: str) -> str:
                    result = lookup(value)
                    return "Unknown" if isinstance(result, ToolUnavailable) else result

                agent.profile_case("secret", expected="secret")
                payload = store.profile_payloads("stored")[0]
                self.assertIsNone(payload["expected"])
                self.assertIsNone(payload["baseline"]["output"])
                self.assertIsNone(payload["baseline"]["invocations"][0]["arguments"])
                self.assertIsNone(payload["baseline"]["invocations"][0]["result"])
                self.assertIsNotNone(payload["baseline"]["invocations"][0]["result_hash"])


if __name__ == "__main__":
    unittest.main()
