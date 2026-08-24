from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from smolagents import ChatMessage, ChatMessageToolCall, MessageRole, Model, Tool, ToolCallingAgent
from smolagents.models import ChatMessageToolCallFunction
from toolvalue import EvalCase, ProfileReport, model as value_model
from toolvalue import profile, tool as value_tool
from toolvalue.store import Store

from .dataset import INCIDENT_FIXTURES


TOOL_ORDER = (
    "deployment_signal",
    "telemetry_signal",
    "runbook_signal",
    "oncall_signal",
)


def exact_match(output: str, expected: str) -> float:
    """Independent, deterministic evaluation with no model-as-judge."""
    return float(output == expected)


def _message_text(message: ChatMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", "")) if isinstance(part, Mapping) else str(part)
            for part in content
        )
    return str(content or "")


def _tool_call(
    name: str,
    arguments: dict[str, Any],
    *,
    call_number: int,
) -> ChatMessage:
    return ChatMessage(
        role=MessageRole.ASSISTANT,
        content=f"Calling {name}",
        tool_calls=[
            ChatMessageToolCall(
                id=f"call_{call_number}",
                type="function",
                function=ChatMessageToolCallFunction(name=name, arguments=arguments),
            )
        ],
    )


class ScriptedTriageModel(Model):
    """Local model adapter that drives the real smolagents tool-calling loop.

    It is intentionally deterministic so this integration measures ToolValue
    and smolagents behavior without requiring a model download or API key.
    """

    def __init__(self, counters: dict[str, int]) -> None:
        super().__init__(model_id="toolvalue/scripted-triage")
        self._counters = counters

    @value_model(name="smolagents_decision")
    def generate(
        self,
        messages: list[ChatMessage],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Tool] | None = None,
        **kwargs: Any,
    ) -> ChatMessage:
        del stop_sequences, response_format, tools_to_call_from, kwargs
        self._counters["model"] += 1

        user_messages = [
            _message_text(message)
            for message in messages
            if message.role == MessageRole.USER
        ]
        task = user_messages[-1]
        service = task.rsplit(":", 1)[-1].strip()

        tool_call_messages = [
            _message_text(message)
            for message in messages
            if message.role == MessageRole.TOOL_CALL
        ]
        called_tools = {
            name
            for name in TOOL_ORDER
            if any(name in call for call in tool_call_messages)
        }
        for name in TOOL_ORDER:
            if name not in called_tools:
                return _tool_call(
                    name,
                    {"service": service},
                    call_number=len(tool_call_messages) + 1,
                )

        observations = "\n".join(
            _message_text(message)
            for message in messages
            if message.role == MessageRole.TOOL_RESPONSE
        )
        deployment_high = "DEPLOYMENT_RISK=high" in observations
        telemetry_spiking = "ERROR_STATE=spiking" in observations
        runbook_rollback = "RUNBOOK_ACTION=rollback" in observations

        if runbook_rollback or (deployment_high and telemetry_spiking):
            answer = "rollback"
        elif deployment_high or telemetry_spiking:
            answer = "investigate"
        else:
            answer = "healthy"
        return _tool_call(
            "final_answer",
            {"answer": answer},
            call_number=len(tool_call_messages) + 1,
        )


class _FixtureTool(Tool):
    inputs = {
        "service": {
            "type": "string",
            "description": "Service name to inspect.",
        }
    }
    output_type = "string"

    def __init__(
        self,
        fixtures: Mapping[str, Mapping[str, str]],
        counters: dict[str, int],
    ) -> None:
        self._fixtures = fixtures
        self._counters = counters
        super().__init__()

    def _value(self, service: str, key: str) -> str:
        try:
            return self._fixtures[service][key]
        except KeyError as exc:
            raise ValueError(f"Unknown incident fixture: {service}") from exc


class DeploymentSignalTool(_FixtureTool):
    name = "deployment_signal"
    description = "Inspect the risk level of the service's most recent deployment."

    @value_tool(name="deployment_signal")
    def forward(self, service: str) -> str:
        self._counters[self.name] += 1
        return f"DEPLOYMENT_RISK={self._value(service, 'deployment')}"


class TelemetrySignalTool(_FixtureTool):
    name = "telemetry_signal"
    description = "Inspect whether the service error rate is normal or spiking."

    @value_tool(name="telemetry_signal")
    def forward(self, service: str) -> str:
        self._counters[self.name] += 1
        return f"ERROR_STATE={self._value(service, 'telemetry')}"


class RunbookSignalTool(_FixtureTool):
    name = "runbook_signal"
    description = "Look up the action currently recommended by the service runbook."

    @value_tool(name="runbook_signal")
    def forward(self, service: str) -> str:
        self._counters[self.name] += 1
        return f"RUNBOOK_ACTION={self._value(service, 'runbook')}"


class OnCallSignalTool(_FixtureTool):
    name = "oncall_signal"
    description = "Look up the engineer currently on call for the service."

    @value_tool(name="oncall_signal")
    def forward(self, service: str) -> str:
        self._counters[self.name] += 1
        return f"ONCALL={self._value(service, 'oncall')}"


@dataclass
class ProfiledSmolAgent:
    function: Callable[..., str]
    counters: dict[str, int]

    def __call__(self, service: str) -> str:
        return self.function(service)

    def profile_case(self, service: str, *, expected: str, metadata: dict[str, Any] | None = None):
        return self.function.profile_case(service, expected=expected, metadata=metadata)

    def evaluate(self, cases: list[EvalCase]) -> ProfileReport:
        return self.function.evaluate(cases)

    @property
    def external_tool_calls(self) -> int:
        return sum(self.counters[name] for name in TOOL_ORDER)

    @property
    def model_runs(self) -> int:
        return self.counters["model"]


def build_agent(
    *,
    fixtures: Mapping[str, Mapping[str, str]] = INCIDENT_FIXTURES,
    store: Store | None = None,
) -> ProfiledSmolAgent:
    counters = {name: 0 for name in (*TOOL_ORDER, "model")}
    model = ScriptedTriageModel(counters)
    upstream_agent = ToolCallingAgent(
        tools=[
            DeploymentSignalTool(fixtures, counters),
            TelemetrySignalTool(fixtures, counters),
            RunbookSignalTool(fixtures, counters),
            OnCallSignalTool(fixtures, counters),
        ],
        model=model,
        max_steps=6,
        verbosity_level=-1,
    )

    profile_options: dict[str, Any] = {
        "task": "smolagents_incident_triage",
        "scorer": exact_match,
    }
    if store is not None:
        profile_options["store"] = store

    @profile(**profile_options)
    def triage(service: str) -> str:
        return str(upstream_agent.run(f"Triage service: {service}", reset=True))

    return ProfiledSmolAgent(function=triage, counters=counters)
