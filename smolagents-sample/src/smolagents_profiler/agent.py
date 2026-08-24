from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from smolagents import ChatMessage, ChatMessageToolCall, MessageRole, Model, OpenAIModel, Tool, ToolCallingAgent
from smolagents.models import ChatMessageToolCallFunction
from toolvalue import EvalCase, ProfileReport, RunValidationContext, model as value_model
from toolvalue import profile, tool as value_tool
from toolvalue.store import Store

from .dataset import INCIDENT_FIXTURES


TOOL_ORDER = (
    "deployment_signal",
    "telemetry_signal",
    "runbook_signal",
    "oncall_signal",
)

TRIAGE_INSTRUCTIONS = """
For every incident, call exactly one tool per turn in this order:
deployment_signal, telemetry_signal, runbook_signal, oncall_signal.
Call every tool exactly once, even when an earlier observation is unavailable.
After all four observations, return exactly one lowercase label through
final_answer using this policy:
- rollback when RUNBOOK_ACTION=rollback, or when DEPLOYMENT_RISK=high and ERROR_STATE=spiking;
- investigate when exactly one of DEPLOYMENT_RISK=high or ERROR_STATE=spiking is present;
- healthy otherwise.
ToolUnavailable means that signal is missing. Do not infer a missing signal.
When a tool returns TOOL_UNAVAILABLE, that attempt is complete: never call that tool again.
The on-call identity never changes the classification.
""".strip()


@dataclass(frozen=True)
class AgentOutcome:
    answer: str
    state: str


def exact_match(output: AgentOutcome | str, expected: str) -> float:
    """Independent, deterministic evaluation with no model-as-judge."""
    answer = output.answer if isinstance(output, AgentOutcome) else output
    return float(answer == expected)


def validate_triage_run(context: RunValidationContext) -> str | None:
    """Reject outcomes that cannot support a controlled attribution claim."""
    if not isinstance(context.output, AgentOutcome):
        return "missing_agent_run_state"
    if context.output.state != "success":
        return f"agent_termination:{context.output.state}"

    counts = Counter(
        invocation.group
        for invocation in context.invocations
        if invocation.kind == "tool"
    )
    policy_errors = [
        f"{name}={counts[name]}"
        for name in TOOL_ORDER
        if counts[name] != 1
    ]
    if policy_errors:
        return f"tool_policy_violation:{','.join(policy_errors)}"
    if context.phase == "baseline" and context.score < 1.0:
        return f"baseline_quality_below_threshold:{context.score:.3f}"
    return None


def _openrouter_response_cost(message: ChatMessage) -> float:
    raw = getattr(message, "raw", None)
    usage = getattr(raw, "usage", None)
    cost = getattr(usage, "cost", None)
    if cost is None:
        model_extra = getattr(usage, "model_extra", None) or {}
        cost = model_extra.get("cost")
    return float(cost or 0.0)


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

    def __init__(self, counters: dict[str, float]) -> None:
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


class OpenRouterTriageModel(Model):
    """Profiled smolagents model backed by OpenRouter's OpenAI-compatible API."""

    def __init__(
        self,
        counters: dict[str, float],
        *,
        api_key: str,
        model_id: str,
    ) -> None:
        super().__init__(model_id=model_id)
        self._counters = counters
        self._delegate = OpenAIModel(
            model_id=model_id,
            api_base="https://openrouter.ai/api/v1",
            api_key=api_key,
            temperature=0,
            max_tokens=128,
            client_kwargs={
                "default_headers": {
                    "HTTP-Referer": "https://github.com/EswarSk/toolvalue",
                    "X-OpenRouter-Title": "ToolValue smolagents experiment",
                }
            },
        )

    @value_model(name="openrouter_llm", cost=_openrouter_response_cost)
    def generate(
        self,
        messages: list[ChatMessage],
        stop_sequences: list[str] | None = None,
        response_format: dict[str, str] | None = None,
        tools_to_call_from: list[Tool] | None = None,
        **kwargs: Any,
    ) -> ChatMessage:
        self._counters["model"] += 1
        result = self._delegate.generate(
            messages,
            stop_sequences=stop_sequences,
            response_format=response_format,
            tools_to_call_from=tools_to_call_from,
            **kwargs,
        )
        token_usage = getattr(result, "token_usage", None)
        self._counters["input_tokens"] += float(getattr(token_usage, "input_tokens", 0) or 0)
        self._counters["output_tokens"] += float(getattr(token_usage, "output_tokens", 0) or 0)
        self._counters["model_cost"] += _openrouter_response_cost(result)
        return result


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
        counters: dict[str, float],
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
    function: Callable[..., AgentOutcome]
    counters: dict[str, float]
    model_backend: str
    model_id: str

    def __call__(self, service: str) -> str:
        return self.function(service).answer

    def profile_case(self, service: str, *, expected: str, metadata: dict[str, Any] | None = None):
        return self.function.profile_case(service, expected=expected, metadata=metadata)

    def evaluate(self, cases: list[EvalCase], *, trials: int | None = None) -> ProfileReport:
        return self.function.evaluate(cases, trials=trials)

    @property
    def external_tool_calls(self) -> int:
        return int(sum(self.counters[name] for name in TOOL_ORDER))

    @property
    def model_runs(self) -> int:
        return int(self.counters["model"])

    @property
    def input_tokens(self) -> int:
        return int(self.counters["input_tokens"])

    @property
    def output_tokens(self) -> int:
        return int(self.counters["output_tokens"])

    @property
    def model_cost(self) -> float:
        return float(self.counters["model_cost"])


def build_agent(
    *,
    fixtures: Mapping[str, Mapping[str, str]] = INCIDENT_FIXTURES,
    store: Store | None = None,
    model_backend: str = "scripted",
    openrouter_api_key: str | None = None,
    openrouter_model_id: str = "openai/gpt-4o-mini",
) -> ProfiledSmolAgent:
    counters = {
        name: 0.0
        for name in (*TOOL_ORDER, "model", "input_tokens", "output_tokens", "model_cost")
    }
    if model_backend == "scripted":
        model: Model = ScriptedTriageModel(counters)
        model_id = "toolvalue/scripted-triage"
    elif model_backend == "openrouter":
        if not openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is required for the OpenRouter backend")
        model = OpenRouterTriageModel(
            counters,
            api_key=openrouter_api_key,
            model_id=openrouter_model_id,
        )
        model_id = openrouter_model_id
    else:
        raise ValueError(f"Unsupported model backend: {model_backend}")
    upstream_agent = ToolCallingAgent(
        tools=[
            DeploymentSignalTool(fixtures, counters),
            TelemetrySignalTool(fixtures, counters),
            RunbookSignalTool(fixtures, counters),
            OnCallSignalTool(fixtures, counters),
        ],
        model=model,
        instructions=TRIAGE_INSTRUCTIONS,
        max_steps=6,
        verbosity_level=-1,
    )

    profile_options: dict[str, Any] = {
        "task": "smolagents_incident_triage",
        "scorer": exact_match,
        "validator": validate_triage_run,
    }
    if store is not None:
        profile_options["store"] = store

    @profile(**profile_options)
    def triage(service: str) -> AgentOutcome:
        result = upstream_agent.run(
            f"Triage service: {service}",
            reset=True,
            return_full_result=True,
        )
        return AgentOutcome(answer=str(result.output), state=result.state)

    return ProfiledSmolAgent(
        function=triage,
        counters=counters,
        model_backend=model_backend,
        model_id=model_id,
    )
