"""Prefix user prompts with an explicit workspace path (matches pragma-style folder runs)."""

from __future__ import annotations

from pathlib import Path


def augment_user_prompt_with_workspace(user_prompt: str, workspace: Path | None) -> str:
    """Tell the agent which directory ``--folder`` refers to so phrases like "this folder" resolve."""
    if workspace is None:
        return user_prompt
    wp = workspace.resolve()
    return (
        "## Workspace\n\n"
        f"The task folder (your tool/process working directory) is:\n\n"
        f"`{wp}`\n\n"
        "When the user writes **this folder**, **the folder**, or **the project**, "
        "they mean that path — list or read files there as needed.\n\n"
        "---\n\n"
        "## User message\n\n"
        f"{user_prompt}"
    )
