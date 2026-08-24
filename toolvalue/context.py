from __future__ import annotations

import copy
import contextvars
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .errors import ReplayDiverged, ReplayedToolError
from .types import RunMode, ToolInvocation, ToolUnavailable


@dataclass
class ExecutionContext:
    run_id: str
    task: str
    mode: RunMode
    capture_content: bool = True
    ablated_unit: str | None = None
    baseline_invocations: list[ToolInvocation] = field(default_factory=list)
    invocations: list[ToolInvocation] = field(default_factory=list)
    _replay_queues: dict[str, list[ToolInvocation]] = field(init=False, default_factory=dict)
    _replay_offsets: dict[str, int] = field(init=False, default_factory=lambda: defaultdict(int))

    def __post_init__(self) -> None:
        queues: dict[str, list[ToolInvocation]] = defaultdict(list)
        for invocation in self.baseline_invocations:
            queues[invocation.arguments_hash].append(invocation)
        self._replay_queues = dict(queues)

    def replay(self, *, tool_name: str, group: str, arguments_hash: str) -> Any:
        if self.ablated_unit in {tool_name, group}:
            return ToolUnavailable(tool_name=tool_name)

        offset = self._replay_offsets[arguments_hash]
        matches = self._replay_queues.get(arguments_hash, [])
        if offset >= len(matches):
            raise ReplayDiverged(tool_name, arguments_hash)
        self._replay_offsets[arguments_hash] += 1
        baseline = matches[offset]
        if baseline.status == "failure":
            raise ReplayedToolError(tool_name, baseline.error or "unknown failure")
        return copy.deepcopy(baseline.result)


_current_context: contextvars.ContextVar[ExecutionContext | None] = contextvars.ContextVar(
    "toolvalue_execution_context", default=None
)


def current_context() -> ExecutionContext | None:
    return _current_context.get()


def set_context(context: ExecutionContext) -> contextvars.Token[ExecutionContext | None]:
    return _current_context.set(context)


def reset_context(token: contextvars.Token[ExecutionContext | None]) -> None:
    _current_context.reset(token)
