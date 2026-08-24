from __future__ import annotations

from toolvalue import EvalCase


DEFAULT_CASES = [
    EvalCase(
        args=("django/django",),
        expected="web_framework",
        metadata={"family": "application_framework"},
    ),
    EvalCase(
        args=("facebook/react",),
        expected="ui_library",
        metadata={"family": "application_framework"},
    ),
    EvalCase(
        args=("hashicorp/terraform",),
        expected="infrastructure_as_code",
        metadata={"family": "infrastructure"},
    ),
    EvalCase(
        args=("microsoft/playwright",),
        expected="testing",
        metadata={"family": "developer_tool"},
    ),
    EvalCase(
        args=("prometheus/prometheus",),
        expected="observability",
        metadata={"family": "infrastructure"},
    ),
    EvalCase(
        args=("kubernetes/kubernetes",),
        expected="container_orchestration",
        metadata={"family": "infrastructure"},
    ),
]
