"""Tool Registry (spec §8, §8.1).

Tools are plain Python callables registered with a name, version, timeout, retry policy and a permission scope
(the set of agent nodes allowed to call them).  Agents call tools only through `ToolRunner.call`, which checks
the scope, validates arguments, enforces the timeout, retries transient errors and records a `tool_calls` row.
"""
from __future__ import annotations

import concurrent.futures
import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import ToolExecutionError, TransientExternalError, WorkflowError
from app.core.logging import get_logger

log = get_logger(__name__)
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="tool")


@dataclass
class ToolSpec:
    name: str
    version: str
    fn: Callable[..., Any]
    description: str = ""
    timeout_s: float = 60.0
    max_retries: int = 2
    deterministic: bool = True
    scope: set[str] = field(default_factory=set)  # allowed node names; empty = any node
    redact_args: tuple[str, ...] = ()


TOOLS: dict[str, ToolSpec] = {}


def tool(name: str, version: str = "1.0", *, description: str = "", timeout_s: float = 60.0, max_retries: int = 2,
         deterministic: bool = True, scope: set[str] | None = None, redact_args: tuple[str, ...] = ()):
    def deco(fn):
        TOOLS[name] = ToolSpec(name, version, fn, description or (fn.__doc__ or "").strip().split("\n")[0], timeout_s,
                               max_retries, deterministic, scope or set(), redact_args)
        return fn
    return deco


def _summarize(value: Any) -> Any:
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, str):
        return value if len(value) <= 120 else value[:117] + "..."
    if isinstance(value, list | tuple):
        return f"<list[{len(value)}]>" if len(value) > 5 else [_summarize(v) for v in value]
    if isinstance(value, dict):
        return {k: _summarize(v) for k, v in list(value.items())[:12]}
    return value if isinstance(value, int | float | bool) or value is None else str(type(value).__name__)


class ToolRunner:
    """Per-node tool access; telemetry rows are buffered and written by the node decorator."""

    def __init__(self, node: str, step_id: str | None, run_id: str | None, telemetry: list):
        self.node, self.step_id, self.run_id, self.telemetry = node, step_id, run_id, telemetry

    def call(self, name: str, /, **kwargs: Any) -> Any:
        spec = TOOLS.get(name)
        if spec is None:
            raise ToolExecutionError(f"unknown tool {name}")
        if spec.scope and self.node not in spec.scope:
            raise ToolExecutionError(f"tool {name} is not permitted for node {self.node}")
        sig = inspect.signature(spec.fn)
        try:
            sig.bind(**kwargs)
        except TypeError as exc:
            raise ToolExecutionError(f"invalid arguments for {name}: {exc}") from exc
        args_log = {k: ("[REDACTED]" if k in spec.redact_args else _summarize(v)) for k, v in kwargs.items()}
        attempts, started = 0, time.monotonic()
        while True:
            attempts += 1
            try:
                fut = _pool.submit(spec.fn, **kwargs)
                result = fut.result(timeout=spec.timeout_s)
                self._record(spec, args_log, "completed", attempts, started, result=_summarize(result))
                return result
            except concurrent.futures.TimeoutError:
                err: Exception = TransientExternalError(f"tool {name} timed out after {spec.timeout_s}s")
            except TransientExternalError as exc:
                err = exc
            except WorkflowError as exc:
                self._record(spec, args_log, "failed", attempts, started, error=str(exc))
                raise
            except Exception as exc:
                self._record(spec, args_log, "failed", attempts, started, error=f"{type(exc).__name__}: {exc}")
                raise ToolExecutionError(f"{name} failed: {exc}") from exc
            if attempts > spec.max_retries:
                self._record(spec, args_log, "failed", attempts, started, error=str(err))
                raise err
            time.sleep(min(2 ** (attempts - 1), 8) * (0 if _testing() else 1))

    def _record(self, spec: ToolSpec, args: dict, status: str, attempts: int, started: float, result: Any = None,
                error: str | None = None) -> None:
        self.telemetry.append({
            "kind": "tool", "tool_name": spec.name, "tool_version": spec.version, "args_redacted": args,
            "result_ref": str(result)[:500] if result is not None else None, "status": status, "attempts": attempts,
            "duration_ms": int((time.monotonic() - started) * 1000), "error": error,
            "step_id": self.step_id, "run_id": self.run_id,
        })


def _testing() -> bool:
    from app.config import settings
    return settings.APP_ENV == "test"


def list_tools() -> list[dict]:
    return [{"name": s.name, "version": s.version, "description": s.description, "deterministic": s.deterministic,
             "timeout_s": s.timeout_s, "max_retries": s.max_retries, "scope": sorted(s.scope)} for s in TOOLS.values()]
