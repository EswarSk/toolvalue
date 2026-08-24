class ToolValueError(Exception):
    """Base exception for profiler errors."""


class ConfigurationError(ToolValueError):
    """Raised when counterfactual profiling is not configured safely."""


class ReplayDiverged(ToolValueError):
    """Internal signal raised when strict replay encounters unseen evidence."""

    def __init__(self, tool_name: str, arguments_hash: str):
        self.tool_name = tool_name
        self.arguments_hash = arguments_hash
        super().__init__(f"Strict replay diverged on unseen call to {tool_name}")


class ReplayedToolError(ToolValueError):
    """Represents a tool failure captured during the baseline run."""

    def __init__(self, tool_name: str, recorded_error: str):
        self.tool_name = tool_name
        self.recorded_error = recorded_error
        super().__init__(f"Recorded {tool_name} failure: {recorded_error}")
