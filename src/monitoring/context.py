"""Propagate contextvars into worker threads (profiler, cost tracker, etc.)."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import copy_context
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def run_in_pipeline_context(fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """Run ``fn`` inside a copy of the current :mod:`contextvars` context."""
    ctx = copy_context()
    return ctx.run(fn, *args, **kwargs)


def submit_in_pipeline_context(
    executor: ThreadPoolExecutor,
    fn: Callable[P, R],
    *args: P.args,
    **kwargs: P.kwargs,
) -> Future[R]:
    """Submit ``fn`` to ``executor`` with the current contextvars copied."""
    ctx = copy_context()
    if kwargs:
        return executor.submit(ctx.run, lambda: fn(*args, **kwargs))
    return executor.submit(ctx.run, fn, *args)
