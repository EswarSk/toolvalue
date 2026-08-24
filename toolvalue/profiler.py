from __future__ import annotations

import inspect
import statistics
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from functools import wraps
from typing import Any, TypeVar, cast

from .analysis import aggregate
from .codec import stable_hash
from .context import ExecutionContext, current_context, reset_context, set_context
from .errors import ConfigurationError, ReplayDiverged
from .store import InMemoryStore, Store
from .types import CaseProfile, CounterfactualRun, EvalCase, ProfileReport, RunMode, RunRecord

F = TypeVar("F", bound=Callable[..., Any])
ScoreResult = float | int | Mapping[str, float]
Scorer = Callable[[Any, Any], ScoreResult | Awaitable[ScoreResult]]


def _scorer_list(scorer: Scorer | Sequence[Scorer] | None) -> list[Scorer]:
    if scorer is None:
        return []
    if callable(scorer):
        return [scorer]
    return list(scorer)


def _coerce_score(result: ScoreResult, name: str) -> tuple[float, dict[str, float]]:
    if isinstance(result, Mapping):
        components = {str(key): float(value) for key, value in result.items()}
        if not components:
            raise ValueError(f"Scorer {name} returned an empty mapping")
        overall = components.get("overall", statistics.fmean(components.values()))
        return overall, components
    value = float(result)
    return value, {name: value}


def _merge_scores(values: list[tuple[float, dict[str, float]]]) -> tuple[float, dict[str, float]]:
    if not values:
        raise ConfigurationError("Counterfactual profiling requires a scorer")
    overall = statistics.fmean(item[0] for item in values)
    components: dict[str, float] = {}
    for _, part in values:
        for key, value in part.items():
            unique = key
            suffix = 2
            while unique in components:
                unique = f"{key}_{suffix}"
                suffix += 1
            components[unique] = value
    return overall, components


def _score_sync(scorers: list[Scorer], output: Any, expected: Any) -> tuple[float, dict[str, float]]:
    values: list[tuple[float, dict[str, float]]] = []
    for scorer in scorers:
        result = scorer(output, expected)
        if inspect.isawaitable(result):
            raise ConfigurationError("An async scorer cannot be used with a synchronous profiled function")
        values.append(_coerce_score(result, getattr(scorer, "__name__", "score")))
    return _merge_scores(values)


async def _score_async(scorers: list[Scorer], output: Any, expected: Any) -> tuple[float, dict[str, float]]:
    values: list[tuple[float, dict[str, float]]] = []
    for scorer in scorers:
        result = scorer(output, expected)
        if inspect.isawaitable(result):
            result = await result
        values.append(_coerce_score(result, getattr(scorer, "__name__", "score")))
    return _merge_scores(values)


def _run_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _units(run: RunRecord, requested: Iterable[str] | None) -> list[str]:
    available = list(
        dict.fromkeys(
            invocation.group
            for invocation in run.invocations
            if invocation.kind == "tool"
        )
    )
    if requested is None:
        return available
    selected = list(dict.fromkeys(requested))
    unknown = sorted(set(selected) - set(available))
    if unknown:
        raise ValueError(f"Unknown ablation units: {', '.join(unknown)}")
    return selected


def profile(
    *,
    task: str,
    scorer: Scorer | Sequence[Scorer] | None = None,
    store: Store | None = None,
    capture_content: bool = True,
) -> Callable[[F], F]:
    """Decorate an existing agent function with observation and profiling methods.

    The wrapped function remains directly callable. It also receives:

    - ``profile_case(*args, expected=..., metadata=...)``
    - ``evaluate(cases)``
    - ``toolvalue_store``
    """
    if not task.strip():
        raise ValueError("task must be a non-empty string")
    scorers = _scorer_list(scorer)

    def decorate(function: F) -> F:
        result_store = store or InMemoryStore()
        is_async = inspect.iscoroutinefunction(function)

        if is_async:
            async def baseline_async(args: tuple[Any, ...], kwargs: dict[str, Any], expected: Any, metadata: dict[str, Any]) -> RunRecord:
                run_id = _run_id("run")
                context = ExecutionContext(run_id=run_id, task=task, mode=RunMode.RECORD, capture_content=True)
                token = set_context(context)
                started = time.perf_counter()
                try:
                    output = await function(*args, **kwargs)
                finally:
                    reset_context(token)
                duration = (time.perf_counter() - started) * 1000
                score, components = await _score_async(scorers, output, expected)
                return RunRecord(id=run_id, task=task, input_hash=stable_hash({"args": args, "kwargs": kwargs}), output=output, score=score, score_components=components, invocations=context.invocations, duration_ms=duration, metadata=metadata)

            async def case_async(*args: Any, expected: Any, metadata: dict[str, Any] | None = None, units: Iterable[str] | None = None, **kwargs: Any) -> CaseProfile:
                if not scorers:
                    raise ConfigurationError("profile_case requires scorer= on @profile")
                baseline = await baseline_async(args, kwargs, expected, metadata or {})
                counterfactuals: list[CounterfactualRun] = []
                for unit in _units(baseline, units):
                    counter_id = _run_id("cf")
                    context = ExecutionContext(run_id=counter_id, task=task, mode=RunMode.REPLAY, capture_content=True, ablated_unit=unit, baseline_invocations=baseline.invocations)
                    token = set_context(context)
                    started = time.perf_counter()
                    try:
                        output = await function(*args, **kwargs)
                        score, components = await _score_async(scorers, output, expected)
                        counterfactuals.append(CounterfactualRun(id=counter_id, baseline_run_id=baseline.id, ablated_unit=unit, output=output, baseline_score=cast(float, baseline.score), counterfactual_score=score, delta=cast(float, baseline.score) - score, status="complete", invocations=context.invocations, duration_ms=(time.perf_counter() - started) * 1000, score_components=components))
                    except ReplayDiverged as exc:
                        counterfactuals.append(CounterfactualRun(id=counter_id, baseline_run_id=baseline.id, ablated_unit=unit, output=None, baseline_score=cast(float, baseline.score), counterfactual_score=None, delta=None, status="diverged", invocations=context.invocations, duration_ms=(time.perf_counter() - started) * 1000, reason=f"unseen_tool_call:{exc.tool_name}"))
                    except Exception as exc:
                        counterfactuals.append(CounterfactualRun(id=counter_id, baseline_run_id=baseline.id, ablated_unit=unit, output=None, baseline_score=cast(float, baseline.score), counterfactual_score=None, delta=None, status="failed", invocations=context.invocations, duration_ms=(time.perf_counter() - started) * 1000, reason=f"{type(exc).__name__}: {exc}"))
                    finally:
                        reset_context(token)
                case = CaseProfile(id=_run_id("profile"), task=task, expected=expected, baseline=baseline, counterfactuals=counterfactuals, metadata=metadata or {})
                result_store.save_profile(case)
                return case

            async def evaluate_async(cases: Iterable[EvalCase], *, units: Iterable[str] | None = None) -> ProfileReport:
                profiles = [await case_async(*case.args, expected=case.expected, metadata=case.metadata, units=units, **case.kwargs) for case in cases]
                return aggregate(profiles)

            @wraps(function)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if current_context() is not None:
                    return await function(*args, **kwargs)
                run_id = _run_id("run")
                context = ExecutionContext(run_id=run_id, task=task, mode=RunMode.RECORD, capture_content=capture_content)
                token = set_context(context)
                started = time.perf_counter()
                try:
                    output = await function(*args, **kwargs)
                finally:
                    reset_context(token)
                run = RunRecord(id=run_id, task=task, input_hash=stable_hash({"args": args, "kwargs": kwargs}), output=output, score=None, score_components={}, invocations=context.invocations, duration_ms=(time.perf_counter() - started) * 1000, metadata={})
                result_store.save_run(run)
                return output

            wrapper: Any = async_wrapper
            wrapper.profile_case = case_async
            wrapper.evaluate = evaluate_async
        else:
            def baseline_sync(args: tuple[Any, ...], kwargs: dict[str, Any], expected: Any, metadata: dict[str, Any]) -> RunRecord:
                run_id = _run_id("run")
                context = ExecutionContext(run_id=run_id, task=task, mode=RunMode.RECORD, capture_content=True)
                token = set_context(context)
                started = time.perf_counter()
                try:
                    output = function(*args, **kwargs)
                finally:
                    reset_context(token)
                duration = (time.perf_counter() - started) * 1000
                score, components = _score_sync(scorers, output, expected)
                return RunRecord(id=run_id, task=task, input_hash=stable_hash({"args": args, "kwargs": kwargs}), output=output, score=score, score_components=components, invocations=context.invocations, duration_ms=duration, metadata=metadata)

            def case_sync(*args: Any, expected: Any, metadata: dict[str, Any] | None = None, units: Iterable[str] | None = None, **kwargs: Any) -> CaseProfile:
                if not scorers:
                    raise ConfigurationError("profile_case requires scorer= on @profile")
                baseline = baseline_sync(args, kwargs, expected, metadata or {})
                counterfactuals: list[CounterfactualRun] = []
                for unit in _units(baseline, units):
                    counter_id = _run_id("cf")
                    context = ExecutionContext(run_id=counter_id, task=task, mode=RunMode.REPLAY, capture_content=True, ablated_unit=unit, baseline_invocations=baseline.invocations)
                    token = set_context(context)
                    started = time.perf_counter()
                    try:
                        output = function(*args, **kwargs)
                        score, components = _score_sync(scorers, output, expected)
                        counterfactuals.append(CounterfactualRun(id=counter_id, baseline_run_id=baseline.id, ablated_unit=unit, output=output, baseline_score=cast(float, baseline.score), counterfactual_score=score, delta=cast(float, baseline.score) - score, status="complete", invocations=context.invocations, duration_ms=(time.perf_counter() - started) * 1000, score_components=components))
                    except ReplayDiverged as exc:
                        counterfactuals.append(CounterfactualRun(id=counter_id, baseline_run_id=baseline.id, ablated_unit=unit, output=None, baseline_score=cast(float, baseline.score), counterfactual_score=None, delta=None, status="diverged", invocations=context.invocations, duration_ms=(time.perf_counter() - started) * 1000, reason=f"unseen_tool_call:{exc.tool_name}"))
                    except Exception as exc:
                        counterfactuals.append(CounterfactualRun(id=counter_id, baseline_run_id=baseline.id, ablated_unit=unit, output=None, baseline_score=cast(float, baseline.score), counterfactual_score=None, delta=None, status="failed", invocations=context.invocations, duration_ms=(time.perf_counter() - started) * 1000, reason=f"{type(exc).__name__}: {exc}"))
                    finally:
                        reset_context(token)
                case = CaseProfile(id=_run_id("profile"), task=task, expected=expected, baseline=baseline, counterfactuals=counterfactuals, metadata=metadata or {})
                result_store.save_profile(case)
                return case

            def evaluate_sync(cases: Iterable[EvalCase], *, units: Iterable[str] | None = None) -> ProfileReport:
                profiles = [case_sync(*case.args, expected=case.expected, metadata=case.metadata, units=units, **case.kwargs) for case in cases]
                return aggregate(profiles)

            @wraps(function)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                if current_context() is not None:
                    return function(*args, **kwargs)
                run_id = _run_id("run")
                context = ExecutionContext(run_id=run_id, task=task, mode=RunMode.RECORD, capture_content=capture_content)
                token = set_context(context)
                started = time.perf_counter()
                try:
                    output = function(*args, **kwargs)
                finally:
                    reset_context(token)
                run = RunRecord(id=run_id, task=task, input_hash=stable_hash({"args": args, "kwargs": kwargs}), output=output, score=None, score_components={}, invocations=context.invocations, duration_ms=(time.perf_counter() - started) * 1000, metadata={})
                result_store.save_run(run)
                return output

            wrapper = sync_wrapper
            wrapper.profile_case = case_sync
            wrapper.evaluate = evaluate_sync

        wrapper.toolvalue_store = result_store
        wrapper.__toolvalue_profile__ = {"task": task, "scorers": [getattr(item, "__name__", "score") for item in scorers]}
        return cast(F, wrapper)

    return decorate
