"""Cursor CLI substrate implementation.

Invokes the Cursor `agent` CLI in print mode with stream-json output,
parses results, and captures session data from SQLite for archival.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import shlex
import shutil
import time
from pathlib import Path

from .base import (
    AgentRunResult,
    AgentSubstrate,
    SubstrateConfig,
    TokenUsage,
    ToolCall,
    generate_run_id,
    generate_session_id,
)

logger = logging.getLogger(__name__)


def _write_cursor_mcp_config(mcp_servers: list, workspace_dir: Path) -> Path:
    """Write .cursor/mcp.json in the workspace directory."""
    cursor_dir = workspace_dir / ".cursor"
    cursor_dir.mkdir(exist_ok=True)
    mcp_path = cursor_dir / "mcp.json"
    config = {"mcpServers": {}}
    for server in mcp_servers:
        config["mcpServers"][server.name] = server.to_dict()
    mcp_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return mcp_path


class CursorSubstrate(AgentSubstrate):
    """Substrate wrapping the Cursor CLI (`agent`)."""

    def __init__(
        self, cli_path: str | None = None, api_key: str | None = None
    ):
        self._cli = cli_path or self._detect_cli()
        self._api_key = api_key or os.environ.get("CURSOR_API_KEY", "")

    @staticmethod
    def _detect_cli() -> str:
        """Find the Cursor CLI binary (agent or cursor)."""
        for name in ("agent", "cursor"):
            if shutil.which(name):
                return name
        return "agent"

    async def health_check(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._cli,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            return proc.returncode == 0
        except (FileNotFoundError, asyncio.TimeoutError, OSError):
            return False

    def get_session_log_path(self, session_id: str) -> Path | None:
        """Locate the Cursor CLI store.db for the given session.

        Scans ``{CLI_CHATS_PATH or ~/.cursor/chats}/{project_id}/{session_id}/store.db``.
        """
        from .cursor_chats import get_cursor_cli_chats_path

        chats_root = get_cursor_cli_chats_path()
        if not chats_root.is_dir():
            return None
        for project_dir in chats_root.iterdir():
            if not project_dir.is_dir():
                continue
            candidate = project_dir / session_id / "store.db"
            if candidate.is_file():
                return candidate
        return None

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
    ) -> AgentRunResult:
        config = config or SubstrateConfig()
        run_id = generate_run_id()
        session_id = session_id or generate_session_id()

        if config.mcp_servers and config.workspace_dir:
            _write_cursor_mcp_config(config.mcp_servers, config.workspace_dir)

        effective_prompt = prompt
        if not resume_session_id and system_prompt:
            effective_prompt = f"{system_prompt}\n\n---\n\n{prompt}"

        cmd = self._build_command(
            effective_prompt,
            config,
            output_format,
            session_id,
            resume_session_id,
        )

        start = time.monotonic()
        result = await self._execute(cmd, timeout_ms, config)
        duration_ms = int((time.monotonic() - start) * 1000)

        parsed = self._parse_stream_json(result.raw_lines)

        resolved_session_id = parsed.get("session_id") or session_id
        session_log = (
            self.get_session_log_path(resolved_session_id)
            if resolved_session_id
            else None
        )

        return AgentRunResult(
            run_id=run_id,
            session_id=resolved_session_id,
            raw_output=result.raw_text,
            parsed_output=parsed.get("result_json"),
            tool_calls=parsed.get("tool_calls", []),
            thinking_blocks=parsed.get("thinking_blocks", []),
            token_usage=parsed.get("token_usage"),
            duration_ms=duration_ms,
            exit_status=result.exit_status,
            substrate="cursor",
            session_log_path=session_log,
            model=parsed.get("model"),
            stderr=result.stderr,
        )

    def _build_command(
        self,
        prompt: str,
        config: SubstrateConfig,
        output_format: str,
        session_id: str,
        resume_session_id: str | None,
    ) -> list[str]:
        """Build the Cursor CLI command.

        Documented flags (cursor.com/docs/cli/reference/parameters):
          -p, --mode, --model, --output-format, --force/--yolo,
          --trust, --approve-mcps, --workspace, --resume [chatId]
        """
        cmd = [
            self._cli,
            "-p",
            prompt,
            "--output-format",
            output_format,
            "--trust",
        ]

        if config.mode:
            cmd.extend(["--mode", config.mode])
        elif config.readonly:
            cmd.extend(["--mode", "ask"])
        else:
            cmd.extend(["--force", "--approve-mcps"])

        if config.workspace_dir:
            cmd.extend(["--workspace", str(config.workspace_dir)])

        if config.model:
            cmd.extend(["--model", config.model])

        if resume_session_id:
            cmd.extend(["--resume", resume_session_id])

        return cmd

    def _build_env(self, config: SubstrateConfig) -> dict[str, str]:
        """Build an isolated environment dict for the subprocess."""
        env: dict[str, str] = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", str(Path.home())),
        }
        if self._api_key:
            env["CURSOR_API_KEY"] = self._api_key
        for key in (
            "TERM",
            "LANG",
            "LC_ALL",
            "TMPDIR",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "NODE_PATH",
            "NVM_DIR",
            "NVM_BIN",
            "npm_config_prefix",
        ):
            val = os.environ.get(key)
            if val:
                env[key] = val
        env.update(config.env_overrides)
        return env

    async def _execute(
        self,
        cmd: list[str],
        timeout_ms: int,
        config: SubstrateConfig | None = None,
    ) -> _RawResult:
        config = config or SubstrateConfig()
        env = self._build_env(config)
        cwd = str(config.cwd) if config.cwd else None

        logger.debug("cursor cmd: %s", shlex.join(cmd))
        logger.debug(
            "cursor cwd=%s timeout=%dms", cwd or "inherited", timeout_ms
        )

        # Stagger startup to avoid concurrent writes to ~/.cursor/cli-config.json
        await asyncio.sleep(random.uniform(0.1, 1.5))

        _STREAM_LIMIT = (
            4 * 1024 * 1024
        )  # 4 MB -- NDJSON lines can exceed the 64 KB default

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_STREAM_LIMIT,
            env=env,
            cwd=cwd,
        )
        logger.debug("cursor pid=%d started", proc.pid)

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        async def _drain_stdout() -> None:
            assert proc.stdout
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    logger.debug("[cursor stdout] %s", line[:500])
                    stdout_lines.append(line)

        async def _drain_stderr() -> None:
            assert proc.stderr
            while True:
                raw = await proc.stderr.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    logger.debug("[cursor stderr] %s", line)
                    stderr_lines.append(line)

        try:
            await asyncio.wait_for(
                asyncio.gather(_drain_stdout(), _drain_stderr()),
                timeout=timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "cursor pid=%d timed out after %dms — killing",
                proc.pid,
                timeout_ms,
            )
            proc.kill()
            await proc.wait()
            raw_text = "\n".join(stdout_lines)
            stderr_text = "\n".join(stderr_lines)
            return _RawResult(
                raw_text=raw_text,
                raw_lines=stdout_lines,
                stderr=stderr_text,
                exit_status="timeout",
            )

        await proc.wait()
        exit_status = "success" if proc.returncode == 0 else "failure"
        logger.debug(
            "cursor pid=%d exited code=%d (%s)",
            proc.pid,
            proc.returncode,
            exit_status,
        )

        raw_text = "\n".join(stdout_lines)
        stderr_text = "\n".join(stderr_lines)
        return _RawResult(
            raw_text=raw_text,
            raw_lines=stdout_lines,
            stderr=stderr_text,
            exit_status=exit_status,
        )

    def _parse_stream_json(self, lines: list[str]) -> dict:
        """Parse Cursor stream-json NDJSON into structured data."""
        result: dict = {
            "tool_calls": [],
            "thinking_blocks": [],
            "session_id": None,
            "model": None,
            "result_json": None,
            "token_usage": None,
        }
        pending_tools: dict[str, ToolCall] = {}

        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")

            if event_type == "system" and event.get("subtype") == "init":
                result["session_id"] = event.get("session_id")
                result["model"] = event.get("model")

            elif event_type == "assistant":
                msg = event.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "text":
                        pass  # text accumulated in result event

            elif event_type == "tool_call":
                subtype = event.get("subtype")
                call_id = event.get("call_id", "")
                tc_data = event.get("tool_call", {})

                if subtype == "started":
                    tool_name = self._extract_tool_name(tc_data)
                    tool_args = self._extract_tool_args(tc_data)
                    tc = ToolCall(
                        call_id=call_id, tool_name=tool_name, args=tool_args
                    )
                    pending_tools[call_id] = tc
                    result["tool_calls"].append(tc)

                elif subtype == "completed" and call_id in pending_tools:
                    tool_result = self._extract_tool_result(tc_data)
                    pending_tools[call_id].result = tool_result

            elif event_type == "result":
                result["session_id"] = (
                    event.get("session_id") or result["session_id"]
                )
                result_text = event.get("result", "")
                try:
                    result["result_json"] = json.loads(result_text)
                except (json.JSONDecodeError, TypeError):
                    result["result_json"] = {"text": result_text}

                # Cursor CLI reports cumulative token usage on the result event.
                usage = event.get("usage") or {}
                if usage:
                    result["token_usage"] = TokenUsage(
                        input_tokens=usage.get("inputTokens") or 0,
                        output_tokens=usage.get("outputTokens") or 0,
                        cache_read_tokens=usage.get("cacheReadTokens") or 0,
                        cache_creation_tokens=usage.get("cacheWriteTokens")
                        or 0,
                    )

        return result

    @staticmethod
    def _extract_tool_name(tc_data: dict) -> str:
        for key in tc_data:
            if key.endswith("ToolCall"):
                return key.replace("ToolCall", "")
        fn = tc_data.get("function", {})
        return fn.get("name", "unknown")

    @staticmethod
    def _extract_tool_args(tc_data: dict) -> dict:
        for key, val in tc_data.items():
            if key.endswith("ToolCall") and isinstance(val, dict):
                return val.get("args", {})
        fn = tc_data.get("function", {})
        args_str = fn.get("arguments", "{}")
        try:
            return json.loads(args_str)
        except (json.JSONDecodeError, TypeError):
            return {"raw": args_str}

    @staticmethod
    def _extract_tool_result(tc_data: dict) -> dict | None:
        for key, val in tc_data.items():
            if key.endswith("ToolCall") and isinstance(val, dict):
                return val.get("result")
        return None


class _RawResult:
    __slots__ = ("raw_text", "raw_lines", "stderr", "exit_status")

    def __init__(
        self,
        raw_text: str,
        raw_lines: list[str],
        stderr: str,
        exit_status: str,
    ):
        self.raw_text = raw_text
        self.raw_lines = raw_lines
        self.stderr = stderr
        self.exit_status = exit_status
