"""Claude Code CLI substrate implementation.

Invokes the `claude` CLI in print mode with stream-json output, parses
results in real-time, and captures full session JSONL for archival.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import shutil
import tempfile
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


def _encode_project_path(cwd: str) -> str:
    """Encode a working directory path the way Claude Code does for project dirs.

    Claude Code replaces every character that is not alphanumeric or a dash with
    a dash.  For example ``/home/will/_pragma-group/.worktrees/coding-alpha``
    becomes ``-home-will--pragma-group--worktrees-coding-alpha``.
    """
    return re.sub(r"[^a-zA-Z0-9-]", "-", cwd)


def _find_claude_sessions_dir(cwd: str) -> Path | None:
    """Locate the Claude Code project directory for a given working directory.

    Claude Code stores session JSONL files directly under
    ``~/.claude/projects/{encoded-cwd}/{session_id}.jsonl`` — there is no
    ``sessions/`` subdirectory.  This function returns the project directory
    itself so callers can look up ``{project_dir}/{session_id}.jsonl``.
    """
    home = Path.home()
    claude_dir = home / ".claude" / "projects"
    if not claude_dir.exists():
        return None

    encoded = _encode_project_path(cwd)
    candidate = claude_dir / encoded
    if candidate.is_dir():
        return candidate

    # Fuzzy fallback: find the project dir whose name most closely matches.
    for project_dir in claude_dir.iterdir():
        if project_dir.is_dir() and encoded.lower() in project_dir.name.lower():
            return project_dir

    return None


def _coalesce_assistant_text_blocks(blocks: list[str]) -> str:
    """Pick assistant output text when stream-json has no result payload.

    Prefer the **longest** block when it is substantially larger than the final
    block — common pattern: analysis + tools, then a short concluding paragraph
    that is *not* the full corrected document.
    """
    if not blocks:
        return ""
    if len(blocks) == 1:
        return blocks[0]
    last = blocks[-1]
    longest = max(blocks, key=len)
    # Heuristic: if an earlier block is much larger than the tail, use it.
    if len(longest) > len(last) * 3 and (len(longest) - len(last)) > 800:
        return longest
    return last


def _write_mcp_config(mcp_servers: list, path: Path) -> None:
    """Write an MCP configuration JSON file."""
    config = {"mcpServers": {}}
    for server in mcp_servers:
        config["mcpServers"][server.name] = server.to_dict()
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _resolve_claude_cli(cli_path: str | None) -> str:
    """Resolve executable: explicit arg, then ``CLAUDE_CODE_BIN``, then ``claude`` on PATH."""
    for raw in (
        (cli_path or "").strip(),
        (os.environ.get("CLAUDE_CODE_BIN") or "").strip(),
    ):
        if not raw:
            continue
        p = Path(raw).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p.resolve())
        w = shutil.which(raw)
        if w:
            return w
        raise FileNotFoundError(
            f"Claude Code CLI not found at {raw!r}. Install: "
            "https://docs.anthropic.com/en/docs/claude-code — or set CLAUDE_CODE_BIN."
        )
    w = shutil.which("claude")
    if w:
        return w
    raise FileNotFoundError(
        "Claude Code CLI not found: expected `claude` on PATH or set CLAUDE_CODE_BIN "
        "(CI: npm install -g @anthropic-ai/claude-code; add $(npm prefix -g)/bin to PATH)."
    )


class ClaudeCodeSubstrate(AgentSubstrate):
    """Substrate wrapping the Claude Code CLI (`claude`)."""

    def __init__(
        self,
        cli_path: str | None = None,
        api_key: str | None = None,
        auth_token: str | None = None,
        base_url: str | None = None,
        permission_mode: str | None = None,
    ):
        self._cli = _resolve_claude_cli(cli_path)
        self._api_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
        self._auth_token = auth_token or os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        self._base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL")
        self._permission_mode = permission_mode

        def _preview(val: str | None) -> str:
            if not val:
                return "(empty)"
            return val[:10] + "…"

        logger.debug(
            "ClaudeCodeSubstrate init: api_key=%s auth_token=%s base_url=%s permission_mode=%s%s",
            _preview(self._api_key),
            _preview(self._auth_token),
            self._base_url or "(none)",
            permission_mode or "(none)",
            " [NOTE: api_key and auth_token both empty — called before ConfigManager loaded .env]"
            if not self._api_key and not self._auth_token else "",
        )

    async def health_check(self) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._cli, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            return proc.returncode == 0
        except (FileNotFoundError, asyncio.TimeoutError, OSError):
            return False

    def get_session_log_path(self, session_id: str, cwd: str | None = None) -> Path | None:
        cwd = cwd or os.getcwd()
        sessions_dir = _find_claude_sessions_dir(cwd)
        if sessions_dir is None:
            return None
        candidate = sessions_dir / f"{session_id}.jsonl"
        if candidate.exists():
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
        temp_files: list[Path] = []

        try:
            cmd = self._build_command(
                prompt, system_prompt, append_system_prompt, config,
                output_format, json_schema, session_id, resume_session_id,
                temp_files,
            )

            effective_cwd = str(config.cwd) if config.cwd else None

            start = time.monotonic()
            result = await self._execute(cmd, prompt, timeout_ms, config)
            duration_ms = int((time.monotonic() - start) * 1000)

            parsed = self._parse_stream_json(result.raw_lines)

            session_log = self.get_session_log_path(
                parsed.get("session_id", session_id), cwd=effective_cwd,
            )

            return AgentRunResult(
                run_id=run_id,
                session_id=parsed.get("session_id", session_id),
                raw_output=result.raw_text,
                parsed_output=parsed.get("result_json"),
                tool_calls=parsed.get("tool_calls", []),
                thinking_blocks=parsed.get("thinking_blocks", []),
                token_usage=parsed.get("token_usage"),
                duration_ms=duration_ms,
                exit_status=result.exit_status,
                substrate="claude-code",
                session_log_path=session_log,
                model=parsed.get("model"),
                stderr=result.stderr,
                authentication_failed=bool(parsed.get("authentication_failed")),
            )
        finally:
            for f in temp_files:
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass

    def _build_command(
        self,
        prompt: str,
        system_prompt: str | None,
        append_system_prompt: str | None,
        config: SubstrateConfig,
        output_format: str,
        json_schema: dict | None,
        session_id: str,
        resume_session_id: str | None,
        temp_files: list[Path],
    ) -> list[str]:
        cmd = [self._cli, "-p", prompt, "--output-format", output_format, "--verbose"]

        if not resume_session_id and system_prompt:
            sp_file = Path(tempfile.mktemp(suffix=".md", prefix="pragma-sysprompt-"))
            sp_file.write_text(system_prompt, encoding="utf-8")
            temp_files.append(sp_file)
            cmd.extend(["--system-prompt-file", str(sp_file)])

        if not resume_session_id and append_system_prompt:
            asp_file = Path(tempfile.mktemp(suffix=".md", prefix="pragma-append-"))
            asp_file.write_text(append_system_prompt, encoding="utf-8")
            temp_files.append(asp_file)
            cmd.extend(["--append-system-prompt-file", str(asp_file)])

        if config.mcp_servers:
            mcp_file = Path(tempfile.mktemp(suffix=".json", prefix="pragma-mcp-"))
            _write_mcp_config(config.mcp_servers, mcp_file)
            temp_files.append(mcp_file)
            cmd.extend(["--mcp-config", str(mcp_file)])
            if config.strict_mcp:
                cmd.append("--strict-mcp-config")

        if config.allowed_tools is not None:
            cmd.extend(["--tools", ",".join(config.allowed_tools) if config.allowed_tools else ""])

        if config.disallowed_tools:
            cmd.append("--disallowedTools")
            cmd.extend(config.disallowed_tools)

        if config.additional_dirs:
            for d in config.additional_dirs:
                cmd.extend(["--add-dir", str(d)])

        if config.model:
            cmd.extend(["--model", config.model])

        if config.max_turns is not None:
            cmd.extend(["--max-turns", str(config.max_turns)])

        if config.max_budget_usd is not None:
            cmd.extend(["--max-budget-usd", str(config.max_budget_usd)])

        if json_schema:
            cmd.extend(["--json-schema", json.dumps(json_schema)])

        if resume_session_id:
            cmd.extend(["--resume", resume_session_id])
        else:
            cmd.extend(["--session-id", session_id])

        pm = config.permission_mode or self._permission_mode
        if not pm and config.mode == "plan":
            pm = "plan"
        if pm:
            cmd.extend(["--permission-mode", pm])

        return cmd

    def _build_env(self, config: SubstrateConfig) -> dict[str, str]:
        """Build an isolated environment dict for the subprocess."""
        env: dict[str, str] = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", str(Path.home())),
            "CLAUDE_CODE_DISABLE_TELEMETRY": "1",
            # Enable Anthropic prompt caching so repeated system prompts
            # (categorization schema, summarization format guidelines) are
            # cached across invocations within the same model/API session.
            # Without this flag the claude CLI never sends cache_control
            # breakpoints, resulting in cache_read=0 and full input-token
            # billing on every call even when the system prompt is identical.
            "CLAUDE_CODE_ENABLE_PROMPT_CACHE": "true",
        }
        env["ANTHROPIC_API_KEY"] = self._api_key
        if self._auth_token:
            env["ANTHROPIC_AUTH_TOKEN"] = self._auth_token
        if self._base_url:
            env["ANTHROPIC_BASE_URL"] = self._base_url
        for key in ("TERM", "LANG", "LC_ALL", "TMPDIR", "XDG_CONFIG_HOME",
                     "XDG_DATA_HOME", "NODE_PATH", "NVM_DIR", "NVM_BIN",
                     "npm_config_prefix"):
            val = os.environ.get(key)
            if val:
                env[key] = val
        # Subprocess env is not a full copy of os.environ; mirror permission mode
        # so CLIs that read CLAUDE_PERMISSION_MODE match --permission-mode.
        pm_env = config.permission_mode or self._permission_mode
        if pm_env:
            env["CLAUDE_PERMISSION_MODE"] = pm_env
        else:
            capm = os.environ.get("CLAUDE_PERMISSION_MODE")
            if capm:
                env["CLAUDE_PERMISSION_MODE"] = capm
        env.update(config.env_overrides)
        return env

    async def _execute(
        self, cmd: list[str], prompt: str, timeout_ms: int,
        config: SubstrateConfig | None = None,
    ) -> _RawResult:
        config = config or SubstrateConfig()
        env = self._build_env(config)
        cwd = str(config.cwd) if config.cwd else None

        logger.debug("claude cmd: %s", shlex.join(cmd))
        logger.debug("claude cwd=%s timeout=%dms", cwd or "inherited", timeout_ms)

        _STREAM_LIMIT = 4 * 1024 * 1024  # 4 MB -- NDJSON lines can exceed the 64 KB default

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_STREAM_LIMIT,
            env=env,
            cwd=cwd,
        )
        logger.debug("claude pid=%d started", proc.pid)

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
                    logger.debug("[claude stdout] %s", line[:500])
                    stdout_lines.append(line)

        async def _drain_stderr() -> None:
            assert proc.stderr
            while True:
                raw = await proc.stderr.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    logger.debug("[claude stderr] %s", line)
                    stderr_lines.append(line)

        try:
            await asyncio.wait_for(
                asyncio.gather(_drain_stdout(), _drain_stderr()),
                timeout=timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "claude pid=%d timed out after %dms — killing", proc.pid, timeout_ms,
            )
            proc.kill()
            await proc.wait()
            raw_text = "\n".join(stdout_lines)
            stderr_text = "\n".join(stderr_lines)
            return _RawResult(raw_text=raw_text, raw_lines=stdout_lines,
                              stderr=stderr_text, exit_status="timeout")

        await proc.wait()
        exit_status = "success" if proc.returncode == 0 else "failure"
        logger.debug("claude pid=%d exited code=%d (%s)", proc.pid, proc.returncode, exit_status)

        raw_text = "\n".join(stdout_lines)
        stderr_text = "\n".join(stderr_lines)
        return _RawResult(raw_text=raw_text, raw_lines=stdout_lines,
                          stderr=stderr_text, exit_status=exit_status)

    def _parse_stream_json(self, lines: list[str]) -> dict:
        """Parse stream-json NDJSON lines into structured data."""
        result: dict = {
            "tool_calls": [],
            "thinking_blocks": [],
            "text_blocks": [],
            "session_id": None,
            "model": None,
            "result_json": None,
            "token_usage": None,
            "authentication_failed": False,
        }
        pending_tools: dict[str, ToolCall] = {}

        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")

            if event_type == "system" and event.get("subtype") == "init":
                result["session_id"] = event.get("session_id") or event.get("sessionId")
                result["model"] = event.get("model")

            elif event_type == "assistant":
                if event.get("error") == "authentication_failed":
                    result["authentication_failed"] = True

                msg = event.get("message", {})
                if not result["model"] and msg.get("model"):
                    result["model"] = msg["model"]

                usage = msg.get("usage")
                if usage:
                    result["token_usage"] = TokenUsage(
                        input_tokens=usage.get("input_tokens") or 0,
                        output_tokens=usage.get("output_tokens") or 0,
                        cache_read_tokens=usage.get("cache_read_input_tokens") or 0,
                        cache_creation_tokens=usage.get("cache_creation_input_tokens") or 0,
                    )

                for block in msg.get("content", []):
                    if block.get("type") == "thinking":
                        result["thinking_blocks"].append(block.get("thinking", ""))
                    elif block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            result["text_blocks"].append(text)
                    elif block.get("type") == "tool_use":
                        tc = ToolCall(
                            call_id=block.get("id", ""),
                            tool_name=block.get("name", ""),
                            args=block.get("input", {}),
                        )
                        pending_tools[tc.call_id] = tc
                        result["tool_calls"].append(tc)

            elif event_type == "result":
                result["session_id"] = event.get("session_id") or result["session_id"]
                result_text = event.get("result", "")
                # The 'result' event carries authoritative cumulative usage for
                # the entire session.  Models that use extended thinking (e.g.
                # claude-haiku-4-5 / anthropic/claude-4.5-haiku-20251001) emit
                # multiple 'assistant' events on stdout — the early ones carry
                # zero-usage sentinel dicts while real token counts only appear
                # here.  Always prefer the result-level usage over whatever the
                # assistant events reported so that token accounting is correct
                # regardless of whether the model uses extended thinking.
                result_usage = event.get("usage")
                if result_usage:
                    result["token_usage"] = TokenUsage(
                        input_tokens=result_usage.get("input_tokens") or 0,
                        output_tokens=result_usage.get("output_tokens") or 0,
                        cache_read_tokens=result_usage.get("cache_read_input_tokens") or 0,
                        cache_creation_tokens=result_usage.get("cache_creation_input_tokens") or 0,
                    )
                try:
                    result["result_json"] = json.loads(result_text)
                except (json.JSONDecodeError, TypeError):
                    result["result_json"] = {"text": result_text}

        # When --json-schema is used, Claude Code returns the structured
        # output via a StructuredOutput tool call. Prefer it over result text.
        for tc in result["tool_calls"]:
            if tc.tool_name == "StructuredOutput" and tc.args:
                result["result_json"] = tc.args
                break

        # If result_json is empty text but we have text blocks from assistant
        # events, derive text from assistant messages. Using *only* the last block
        # is unsafe: multi-turn runs often end with a short meta summary ("Perfect!
        # … ## Conclusion … no changes needed") while an earlier block holds the
        # full Markdown file — that would overwrite the paper with the fragment.
        if (result["result_json"] == {"text": ""} or result["result_json"] is None) \
                and result["text_blocks"]:
            combined = _coalesce_assistant_text_blocks(result["text_blocks"])
            try:
                result["result_json"] = json.loads(combined)
            except (json.JSONDecodeError, TypeError):
                result["result_json"] = {"text": combined}

        if result.get("authentication_failed"):
            logger.warning(
                "Claude Code stream-json reported authentication_failed (not logged in or missing "
                "API credentials in the subprocess env). Ensure ANTHROPIC_API_KEY or OpenRouter "
                "mapping runs before ClaudeCodeSubstrate; subscription use may require `claude login`."
            )

        return result


class _RawResult:
    __slots__ = ("raw_text", "raw_lines", "stderr", "exit_status")

    def __init__(self, raw_text: str, raw_lines: list[str], stderr: str, exit_status: str):
        self.raw_text = raw_text
        self.raw_lines = raw_lines
        self.stderr = stderr
        self.exit_status = exit_status
