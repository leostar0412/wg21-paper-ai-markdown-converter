"""Extract assistant text from stream-json results (pragma SkillRunner pattern)."""

from __future__ import annotations

import yaml

from paper_tools.substrate.base import AgentRunResult


def strip_outer_fences(text: str) -> str:
    stripped = text.strip()
    lines = stripped.split("\n")
    if len(lines) < 3:
        return stripped
    if lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def agent_run_to_text(result: AgentRunResult) -> str:
    """Extract assistant text from an :class:`AgentRunResult`."""
    if result.parsed_output and isinstance(result.parsed_output, dict):
        t = result.parsed_output.get("text", "")
        if t:
            return strip_outer_fences(str(t)).strip()
    if result.raw_output:
        return result.raw_output.strip()
    return ""
