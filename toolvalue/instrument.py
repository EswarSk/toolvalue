from __future__ import annotations

import copy
import inspect
import time
import uuid
from collections.abc import Callable
from functools import wraps
from typing import Any, Literal, TypeVar, overload

from .codec import invocation_key, json_safe, stable_hash
from .context import current_context
from .types import RunMode, ToolInvocation, ToolUnavailable

F = TypeVar("F", bound=Callable[..., Any])
Cost = float | Callable[[Any], float]


def _resolve_cost(cost: Cost, result: Any) -> float:
    return float(cost(result) if callable(cost) else cost)


def _arguments(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    return {"args": json_safe(args), "kwargs": json_safe(kwargs)}


def _record(
    *,
    tool_name: str,
    group: str,
    key: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result: Any,
    cost: float,
    duration_ms: float,
    status: Literal["success", "failure", "unavailable"],
    kind: Literal["tool", "model"] = "tool",
    error: str | None = None,
    replayed: bool = False,
) -> None:
    context = current_context()
    if context is None:
        return
    stored_result = copy.deepcopy(result) if context.capture_content else None
    context.invocations.append(
        ToolInvocation(
            id=f"call_{uuid.uuid4().hex[:12]}",
            run_id=context.run_id,
            tool_name=tool_name,
            group=group,
            arguments=_arguments(args, kwargs),
            arguments_hash=key,
            result=stored_result,
            result_hash=stable_hash(result) if status == "success" else None,
            cost=cost,
            duration_ms=duration_ms,
            status=status,
            kind=kind,
            error=error,
            replayed=replayed,
        )
    )


def _replay_value(
    *, tool_name: str, group: str, replay_policy: str, key: str, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> Any:
    context = current_context()
    assert context is not None
    started = time.perf_counter()
    if replay_policy == "never":
        result: Any = ToolUnavailable(reason="replay_policy_never", tool_name=tool_name)
    else:
        result = context.replay(tool_name=tool_name, group=group, arguments_hash=key)
    duration_ms = (time.perf_counter() - started) * 1000
    _record(
        tool_name=tool_name,
        group=group,
        key=key,
        args=args,
        kwargs=kwargs,
        result=result,
        cost=0.0,
        duration_ms=duration_ms,
        status="unavailable" if isinstance(result, ToolUnavailable) else "success",
        replayed=True,
    )
    return result


@overload
def tool(function: F, /) -> F: ...


@overload
def tool(
    function: None = None,
    /,
    *,
    name: str | None = None,
    group: str | None = None,
    cost: Cost = 0.0,
    replay_policy: Literal["record", "never"] = "record",
) -> Callable[[F], F]: ...


def tool(
    function: F | None = None,
    /,
    *,
    name: str | None = None,
    group: str | None = None,
    cost: Cost = 0.0,
    replay_policy: Literal["record", "never"] = "record",
) -> F | Callable[[F], F]:
    """Instrument a tool boundary for recording and strict replay."""

    def decorate(func: F) -> F:
        tool_name = name or func.__name__
        tool_group = group or tool_name

        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                context = current_context()
                if context is None:
                    return await func(*args, **kwargs)
                key = invocation_key(tool_name, args, kwargs)
                if context.mode == RunMode.REPLAY:
                    return _replay_value(tool_name=tool_name, group=tool_group, replay_policy=replay_policy, key=key, args=args, kwargs=kwargs)
                started = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    _record(tool_name=tool_name, group=tool_group, key=key, args=args, kwargs=kwargs, result=None, cost=0.0, duration_ms=(time.perf_counter() - started) * 1000, status="failure", error=f"{type(exc).__name__}: {exc}")
                    raise
                _record(tool_name=tool_name, group=tool_group, key=key, args=args, kwargs=kwargs, result=result, cost=_resolve_cost(cost, result), duration_ms=(time.perf_counter() - started) * 1000, status="success")
                return result

            wrapper: Any = async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                context = current_context()
                if context is None:
                    return func(*args, **kwargs)
                key = invocation_key(tool_name, args, kwargs)
                if context.mode == RunMode.REPLAY:
                    return _replay_value(tool_name=tool_name, group=tool_group, replay_policy=replay_policy, key=key, args=args, kwargs=kwargs)
                started = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                except Exception as exc:
                    _record(tool_name=tool_name, group=tool_group, key=key, args=args, kwargs=kwargs, result=None, cost=0.0, duration_ms=(time.perf_counter() - started) * 1000, status="failure", error=f"{type(exc).__name__}: {exc}")
                    raise
                _record(tool_name=tool_name, group=tool_group, key=key, args=args, kwargs=kwargs, result=result, cost=_resolve_cost(cost, result), duration_ms=(time.perf_counter() - started) * 1000, status="success")
                return result

            wrapper = sync_wrapper

        wrapper.__toolvalue_tool__ = {"name": tool_name, "group": tool_group, "cost": cost, "replay_policy": replay_policy}
        return wrapper

    if function is not None:
        return decorate(function)
    return decorate


@overload
def model(function: F, /) -> F: ...


@overload
def model(
    function: None = None,
    /,
    *,
    name: str | None = None,
    cost: Cost = 0.0,
) -> Callable[[F], F]: ...


def model(
    function: F | None = None,
    /,
    *,
    name: str | None = None,
    cost: Cost = 0.0,
) -> F | Callable[[F], F]:
    """Instrument a reasoning boundary that reruns during counterfactual replay.

    External evidence belongs behind ``@tool`` and is frozen after the baseline.
    A model or deterministic decision function belongs behind ``@model`` so it
    can respond to each ablated evidence set while its latency and cost remain
    observable.
    """

    def decorate(func: F) -> F:
        model_name = name or func.__name__

        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                context = current_context()
                if context is None:
                    return await func(*args, **kwargs)
                key = invocation_key(model_name, args, kwargs)
                started = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    _record(
                        tool_name=model_name,
                        group=model_name,
                        key=key,
                        args=args,
                        kwargs=kwargs,
                        result=None,
                        cost=0.0,
                        duration_ms=(time.perf_counter() - started) * 1000,
                        status="failure",
                        kind="model",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    raise
                _record(
                    tool_name=model_name,
                    group=model_name,
                    key=key,
                    args=args,
                    kwargs=kwargs,
                    result=result,
                    cost=_resolve_cost(cost, result),
                    duration_ms=(time.perf_counter() - started) * 1000,
                    status="success",
                    kind="model",
                )
                return result

            wrapper: Any = async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                context = current_context()
                if context is None:
                    return func(*args, **kwargs)
                key = invocation_key(model_name, args, kwargs)
                started = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                except Exception as exc:
                    _record(
                        tool_name=model_name,
                        group=model_name,
                        key=key,
                        args=args,
                        kwargs=kwargs,
                        result=None,
                        cost=0.0,
                        duration_ms=(time.perf_counter() - started) * 1000,
                        status="failure",
                        kind="model",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    raise
                _record(
                    tool_name=model_name,
                    group=model_name,
                    key=key,
                    args=args,
                    kwargs=kwargs,
                    result=result,
                    cost=_resolve_cost(cost, result),
                    duration_ms=(time.perf_counter() - started) * 1000,
                    status="success",
                    kind="model",
                )
                return result

            wrapper = sync_wrapper

        wrapper.__toolvalue_model__ = {"name": model_name, "cost": cost, "replay_policy": "rerun"}
        return wrapper

    if function is not None:
        return decorate(function)
    return decorate


def instrument_tool(function: F, *, name: str | None = None, group: str | None = None, cost: Cost = 0.0) -> F:
    """Registry-friendly equivalent of ``@tool``."""
    return tool(name=name, group=group, cost=cost)(function)


class ToolRegistryMiddleware:
    """Small adapter for registries that can replace registered callables."""

    def wrap(self, name: str, function: F, *, group: str | None = None, cost: Cost = 0.0) -> F:
        return instrument_tool(function, name=name, group=group, cost=cost)


def middleware() -> ToolRegistryMiddleware:
    return ToolRegistryMiddleware()
