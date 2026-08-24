"""ToolValue public API."""

from .analysis import aggregate, aggregate_by_metadata, render_report
from .errors import ConfigurationError, ReplayDiverged, ToolValueError
from .instrument import instrument_tool, middleware, model, tool
from .profiler import profile
from .store import InMemoryStore, SQLiteStore
from .types import (
    CaseProfile,
    CounterfactualRun,
    EvalCase,
    ProfileReport,
    RunRecord,
    RunValidationContext,
    ToolAggregate,
    ToolInvocation,
    ToolUnavailable,
)

__all__ = [
    "CaseProfile",
    "ConfigurationError",
    "CounterfactualRun",
    "EvalCase",
    "InMemoryStore",
    "ProfileReport",
    "ReplayDiverged",
    "RunRecord",
    "RunValidationContext",
    "SQLiteStore",
    "ToolAggregate",
    "ToolInvocation",
    "ToolUnavailable",
    "ToolValueError",
    "aggregate",
    "aggregate_by_metadata",
    "instrument_tool",
    "middleware",
    "model",
    "profile",
    "render_report",
    "tool",
]

__version__ = "0.1.0"
