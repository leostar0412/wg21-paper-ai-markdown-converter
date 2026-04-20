"""Agent substrate interface — forked from pragma-agent / WG21 ai_process."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str
    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        entry: dict = {"command": self.command, "args": self.args}
        if self.env:
            entry["env"] = self.env
        return entry


@dataclass
class SubstrateConfig:
    """Per-invocation configuration for a substrate."""

    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    mcp_servers: list[MCPServerConfig] | None = None
    strict_mcp: bool = False
    model: str | None = None
    max_turns: int | None = None
    max_budget_usd: float | None = None
    additional_dirs: list[Path] | None = None
    workspace_dir: Path | None = None
    env_overrides: dict[str, str] = field(default_factory=dict)
    permission_mode: str | None = None
    cwd: Path | None = None
    readonly: bool = False
    mode: str | None = None


@dataclass
class ToolCall:
    """A single tool invocation captured from a substrate run."""

    call_id: str
    tool_name: str
    args: dict
    result: dict | None = None
    duration_ms: int | None = None


@dataclass
class TokenUsage:
    """Token consumption for a substrate run."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class AgentRunResult:
    """Result of a single substrate invocation."""

    run_id: str
    session_id: str
    raw_output: str
    parsed_output: dict | None
    tool_calls: list[ToolCall]
    thinking_blocks: list[str]
    token_usage: TokenUsage | None
    duration_ms: int
    exit_status: Literal["success", "failure", "timeout"]
    substrate: Literal["claude-code", "cursor"]
    session_log_path: Path | None = None
    model: str | None = None
    stderr: str = ""
    authentication_failed: bool = False


def generate_run_id() -> str:
    return uuid.uuid4().hex[:12]


def generate_session_id() -> str:
    return str(uuid.uuid4())


class AgentSubstrate(ABC):
    """Abstract base for agent substrate implementations."""

    @abstractmethod
    async def invoke(
        self,
        prompt: str,
        system_prompt: str | None = None,
        append_system_prompt: str | None = None,
        config: SubstrateConfig | None = None,
        output_format: str = "stream-json",
        json_schema: dict | None = None,
        timeout_ms: int = 300_000,
        session_id: str | None = None,
        resume_session_id: str | None = None,
    ) -> AgentRunResult: ...

    @abstractmethod
    async def health_check(self) -> bool: ...

    @abstractmethod
    def get_session_log_path(self, session_id: str) -> Path | None: ...
