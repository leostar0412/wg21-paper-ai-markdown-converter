"""Structured run logs: model, token usage, duration, retry counts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_tools.substrate.base import AgentRunResult, TokenUsage


def _usage_dict(tu: TokenUsage | None) -> dict[str, int]:
    if tu is None:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
        }
    return {
        "input_tokens": tu.input_tokens,
        "output_tokens": tu.output_tokens,
        "cache_read_tokens": tu.cache_read_tokens,
        "cache_creation_tokens": tu.cache_creation_tokens,
    }


def record_from_result(
    *,
    role: str,
    label: str,
    round_index: int | None,
    result: AgentRunResult,
    attempts: int,
    configured_model: str | None = None,
) -> dict[str, Any]:
    """One logical invocation (after retries collapsed to one result)."""
    tu = result.token_usage
    return {
        "role": role,
        "label": label,
        "round": round_index,
        "substrate": result.substrate,
        "model_reported": result.model,
        "model_configured": configured_model,
        "attempts": attempts,
        "exit_status": result.exit_status,
        "duration_ms": result.duration_ms,
        "session_id": result.session_id,
        "run_id": result.run_id,
        "tokens": _usage_dict(tu),
        "authentication_failed": getattr(result, "authentication_failed", False),
        "tool_calls_count": len(result.tool_calls),
    }


def sum_usage_dicts(rows: list[dict[str, Any]]) -> dict[str, int]:
    keys = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")
    out = {k: 0 for k in keys}
    for row in rows:
        t = row.get("tokens") or {}
        for k in keys:
            out[k] += int(t.get(k, 0) or 0)
    return out


def format_human_report(payload: dict[str, Any]) -> str:
    """Readable block for stderr (upload = input, download = output)."""
    lines: list[str] = []
    lines.append("")
    lines.append("========== RUN LOG ==========")
    lines.append(f"started_utc: {payload.get('started_utc', '')}")
    lines.append(f"mode: {payload.get('mode', '')}")
    if payload.get("skill"):
        lines.append(f"skill: {payload['skill']}")
    if payload.get("folder"):
        lines.append(f"folder: {payload['folder']}")
    if "skill_approved" in payload:
        lines.append(f"skill_approved: {payload['skill_approved']}")
    if payload.get("timeout_ms_per_invoke") is not None:
        lines.append(f"timeout_ms_per_invoke: {payload['timeout_ms_per_invoke']}")

    for inv in payload.get("invocations", []):
        role = inv.get("role", "?")
        lab = inv.get("label", "")
        r = inv.get("round")
        rd = f" round={r}" if r is not None else ""
        lines.append("")
        lines.append(f"--- {role} {lab}{rd} ---")
        lines.append(f"  substrate: {inv.get('substrate')}")
        lines.append(f"  model (reported): {inv.get('model_reported')}")
        lines.append(f"  model (configured): {inv.get('model_configured')}")
        lines.append(f"  attempts: {inv.get('attempts')}")
        lines.append(f"  exit_status: {inv.get('exit_status')}")
        lines.append(f"  duration_ms: {inv.get('duration_ms')}")
        tok = inv.get("tokens") or {}
        lines.append(
            "  tokens — upload (input): {input_tokens}  "
            "download (output): {output_tokens}  "
            "cache_read: {cache_read_tokens}  "
            "cache_write: {cache_creation_tokens}".format(
                input_tokens=tok.get("input_tokens", 0),
                output_tokens=tok.get("output_tokens", 0),
                cache_read_tokens=tok.get("cache_read_tokens", 0),
                cache_creation_tokens=tok.get("cache_creation_tokens", 0),
            )
        )
        lines.append(f"  session_id: {inv.get('session_id', '')[:36]}…")

    tot = payload.get("totals") or {}
    lines.append("")
    lines.append("--- totals (all invocations) ---")
    lines.append(f"  wall_duration_ms_sum: {tot.get('wall_duration_ms_sum', 0)}")
    ttot = tot.get("tokens") or {}
    lines.append(
        "  tokens — upload (input): {input_tokens}  "
        "download (output): {output_tokens}  "
        "cache_read: {cache_read_tokens}  "
        "cache_write: {cache_creation_tokens}".format(
            input_tokens=ttot.get("input_tokens", 0),
            output_tokens=ttot.get("output_tokens", 0),
            cache_read_tokens=ttot.get("cache_read_tokens", 0),
            cache_creation_tokens=ttot.get("cache_creation_tokens", 0),
        )
    )
    lines.append(f"  invocation_count: {tot.get('invocation_count', 0)}")
    lines.append(f"  retry_attempts_sum: {tot.get('retry_attempts_sum', 0)}")
    lines.append("==============================")
    lines.append("")
    return "\n".join(lines)


def build_payload_direct(
    *,
    mode: str,
    folder: str,
    result: AgentRunResult,
    attempts: int,
    configured_model: str | None,
) -> dict[str, Any]:
    inv = record_from_result(
        role=mode,
        label=f"{mode}-invoke",
        round_index=None,
        result=result,
        attempts=attempts,
        configured_model=configured_model,
    )
    td = inv["tokens"]
    return {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "folder": folder,
        "invocations": [inv],
        "totals": {
            "wall_duration_ms_sum": result.duration_ms,
            "tokens": {k: td[k] for k in td},
            "invocation_count": 1,
            "retry_attempts_sum": max(0, attempts - 1),
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_skill_run_payload(folder: str, out: Any) -> dict[str, Any]:
    """Build log dict from :class:`~paper_tools.workflow.skill_runner.SkillResult`."""
    tel = getattr(out, "telemetry", None) or {}
    invocations: list[dict[str, Any]] = []
    author_cfg = tel.get("author_model_configured") or None
    rev_cfg = tel.get("reviewer_model_configured") or None
    aa = list(tel.get("author_attempts") or [])
    ra = list(tel.get("reviewer_attempts") or [])

    for i, ar in enumerate(getattr(out, "author_results", []) or []):
        att = aa[i] if i < len(aa) else 1
        invocations.append(
            record_from_result(
                role="author",
                label=f"{tel.get('skill_name', 'skill')}-author-r{i + 1}",
                round_index=i + 1,
                result=ar,
                attempts=att,
                configured_model=author_cfg,
            )
        )
    for i, rr in enumerate(getattr(out, "reviewer_results", []) or []):
        att = ra[i] if i < len(ra) else 1
        invocations.append(
            record_from_result(
                role="reviewer",
                label=f"{tel.get('skill_name', 'skill')}-reviewer-r{i + 1}",
                round_index=i + 1,
                result=rr,
                attempts=att,
                configured_model=rev_cfg,
            )
        )

    wall = sum(int(x.get("duration_ms", 0) or 0) for x in invocations)
    tok_sum = sum_usage_dicts(invocations)
    retry_sum = sum(max(0, int(x.get("attempts", 1) or 1) - 1) for x in invocations)

    return {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "skill",
        "skill": tel.get("skill_name", ""),
        "folder": folder,
        "invocations": invocations,
        "totals": {
            "wall_duration_ms_sum": wall,
            "tokens": tok_sum,
            "invocation_count": len(invocations),
            "retry_attempts_sum": retry_sum,
        },
        "skill_approved": getattr(out, "approved", False),
    }
