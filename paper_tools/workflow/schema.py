"""Workflow configuration (JSON / CLI) — validated with Pydantic."""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class ClaudeCodeCredentials(BaseModel):
    """Maps to ``ANTHROPIC_*`` environment variables for Claude Code."""

    api_key: str = ""
    auth_token: str = ""
    base_url: str = ""


class CursorCredentials(BaseModel):
    """Maps to ``CURSOR_API_KEY`` for the Cursor CLI."""

    api_key: str = ""


class WorkflowConfig(BaseModel):
    """End-to-end paper ingestion workflow input."""

    papers: list[str] = Field(..., min_length=1)
    claude_code: ClaudeCodeCredentials | None = None
    cursor: CursorCredentials | None = None
    model_tier: int = Field(
        ..., ge=1, le=3, description="Maps to tier_1 … tier_3"
    )
    callback_url: str | None = Field(
        default=None,
        description="Optional HTTPS URL for a POST callback when the run finishes.",
    )
    callback_auth_token: str | None = None

    @field_validator("papers", mode="before")
    @classmethod
    def strip_urls(cls, v: Any) -> Any:
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return v

    @model_validator(mode="after")
    def at_least_one_provider(self) -> WorkflowConfig:
        c = self.claude_code
        has_claude = bool(c and (c.api_key.strip() or c.auth_token.strip()))
        u = self.cursor
        has_cursor = bool(u and u.api_key.strip())
        if not has_claude and not has_cursor:
            raise ValueError(
                "Provide credentials in `claude_code` (api_key and/or auth_token) "
                "and/or `cursor.api_key`."
            )
        return self

    def tier_id(self) -> str:
        return f"tier_{self.model_tier}"

    def apply_environment(self) -> None:
        """Set process environment for Claude Code / Cursor child processes."""
        if self.claude_code:
            c = self.claude_code
            if c.api_key.strip():
                os.environ["ANTHROPIC_API_KEY"] = c.api_key.strip()
            if c.auth_token.strip():
                os.environ["ANTHROPIC_AUTH_TOKEN"] = c.auth_token.strip()
            if c.base_url.strip():
                os.environ["ANTHROPIC_BASE_URL"] = c.base_url.strip()
        if self.cursor and self.cursor.api_key.strip():
            os.environ["CURSOR_API_KEY"] = self.cursor.api_key.strip()


def parse_config_dict(data: dict[str, Any]) -> WorkflowConfig:
    return WorkflowConfig.model_validate(data)
