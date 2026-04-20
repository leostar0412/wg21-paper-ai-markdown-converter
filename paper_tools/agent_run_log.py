"""Serialize :class:`AgentRunResult` for structured workflow logs (JSON-safe)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from paper_tools.substrate.base import AgentRunResult, TokenUsage, ToolCall


def _json_safe(obj: Any) -> Any:
    """Round-trip through JSON so logs always serialize (paths, sets, …)."""
    try:
        return json.loads(json.dumps(obj, default=_json_default))
    except (TypeError, ValueError):
        return str(obj)


def _json_default(o: Any) -> Any:
    if isinstance(o, Path):
        return str(o)
    return str(o)


def token_usage_to_dict(t: TokenUsage | None) -> dict[str, Any] | None:
    if t is None:
        return None
    return {
        "input_tokens": t.input_tokens,
        "output_tokens": t.output_tokens,
        "cache_read_tokens": t.cache_read_tokens,
        "cache_creation_tokens": t.cache_creation_tokens,
        "total_tokens": t.total_tokens,
    }


def tool_call_to_dict(tc: ToolCall) -> dict[str, Any]:
    return {
        "call_id": tc.call_id,
        "tool_name": tc.tool_name,
        "args": _json_safe(tc.args) if tc.args is not None else {},
        "duration_ms": tc.duration_ms,
    }


def agent_run_result_to_dict(
    r: AgentRunResult,
    *,
    max_raw_chars: int = 250_000,
    max_stderr_chars: int = 32_000,
) -> dict[str, Any]:
    """Flatten a run result for ``logs.json`` (truncates very long streams)."""
    raw = r.raw_output or ""
    if len(raw) > max_raw_chars:
        raw = raw[:max_raw_chars] + "\n... [truncated]\n"

    err = r.stderr or ""
    if len(err) > max_stderr_chars:
        err = "... [stderr truncated]\n" + err[-max_stderr_chars:]

    out: dict[str, Any] = {
        "substrate": r.substrate,
        "exit_status": r.exit_status,
        "duration_ms": r.duration_ms,
        "session_id": r.session_id,
        "model": r.model,
        "authentication_failed": r.authentication_failed,
        "token_usage": token_usage_to_dict(r.token_usage),
        "session_log_path": str(r.session_log_path)
        if r.session_log_path
        else None,
        "tool_calls": [tool_call_to_dict(tc) for tc in r.tool_calls],
        "tool_calls_count": len(r.tool_calls),
        "raw_output": raw,
        "stderr": err,
    }
    if r.parsed_output is not None:
        if isinstance(r.parsed_output, dict):
            out["parsed_output"] = _json_safe(r.parsed_output)
        else:
            out["parsed_output"] = str(r.parsed_output)[:10_000]
    return out
