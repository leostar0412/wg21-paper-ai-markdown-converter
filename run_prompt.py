#!/usr/bin/env python3
"""Send a prompt scoped to a folder via Claude Code, Cursor CLI, or a pragma-style skill.

Read access: the chosen folder is passed as ``cwd``, ``--add-dir`` (Claude), and
``--workspace`` (Cursor) so agents can read project files.

Write policy (no silent writes to the folder):
  * **Cursor** uses ``--mode ask`` (read-only / no apply) unless you pass
    ``--cursor-write`` (adds ``--force`` — use only when you intend auto-apply).
  * **Claude Code** defaults to ``--permission-mode acceptEdits`` when
    ``CLAUDE_PERMISSION_MODE`` is unset (matches ``url2md`` improve phases).
    Use ``plan`` if you want the CLI to prompt before each edit. Override with
    ``--claude-permission-mode`` or ``CLAUDE_PERMISSION_MODE``.

Usage:
  python run_prompt.py --folder ./papers --substrate claude --prompt "Summarize README.md"
  python run_prompt.py --env-file /path/to/.env --folder ./papers --substrate claude --prompt "..."
  python run_prompt.py --folder ./papers --substrate cursor --prompt-file task.txt
  python run_prompt.py --folder ./papers --substrate skill --skill my-skill

Env: copy ``.env.example`` to ``.env`` (or set ``PAPER_TOOLS_ENV_FILE``), or pass ``--env-file``.

Run log: a human-readable summary is printed to stderr unless ``--no-run-log-print``.
JSON is written to ``<folder>/paper_tools_run_log.json`` by default; override with ``--run-log path``.

Cursor CLI auth: ``agent login`` or ``CURSOR_API_KEY`` (optional ``--cursor-api-key``).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from paper_tools.substrate.base import AgentSubstrate, SubstrateConfig
from paper_tools.substrate.claude_code import ClaudeCodeSubstrate
from paper_tools.substrate.cursor import CursorSubstrate
from paper_tools.invocation_log import (
    build_payload_direct,
    build_skill_run_payload,
    format_human_report,
    write_json,
)
from paper_tools.textutil import agent_run_to_text
from paper_tools.workspace_context import augment_user_prompt_with_workspace
from paper_tools.workflow.skill_runner import SkillRunner
from paper_tools.workflow.skill_spec import load_skill_spec

# Written under ``--folder`` when ``--run-log`` is omitted.
DEFAULT_RUN_LOG_NAME = "paper_tools_run_log.json"


def _bootstrap_env_from_file(explicit: Path | None, *, override: bool) -> Path | None:
    """Load a .env file into ``os.environ`` before substrates read credentials.

    Search order when ``explicit`` is None:
    1. ``PAPER_TOOLS_ENV_FILE`` if set
    2. ``<repo>/.env`` next to this script

    Returns the path loaded, or None if no file was applied.
    """
    try:
        from dotenv import load_dotenv
    except ImportError as e:
        raise SystemExit(
            "python-dotenv is required for --env-file. "
            "Install: pip install python-dotenv"
        ) from e

    script_dir = Path(__file__).resolve().parent
    candidates: list[Path] = []
    if explicit is not None:
        p = explicit.expanduser().resolve()
        if not p.is_file():
            raise SystemExit(f"Env file not found: {p}")
        candidates.append(p)
    else:
        env_var = os.environ.get("PAPER_TOOLS_ENV_FILE", "").strip()
        if env_var:
            candidates.append(Path(env_var).expanduser().resolve())
        candidates.append(script_dir / ".env")

    loaded: Path | None = None
    for p in candidates:
        if p.is_file():
            load_dotenv(p, override=override)
            loaded = p
            break

    return loaded


def _cursor_substrate_from_args(args: argparse.Namespace) -> CursorSubstrate:
    """Build :class:`CursorSubstrate` with optional binary path and API key."""
    kwargs: dict = {}
    cb = (getattr(args, "cursor_bin", None) or "").strip()
    if cb:
        kwargs["cli_path"] = cb
    cak = (getattr(args, "cursor_api_key", None) or "").strip()
    if cak:
        kwargs["api_key"] = cak
    return CursorSubstrate(**kwargs)


def _substrate_from_skill_name(substrate_name: str, args: argparse.Namespace) -> AgentSubstrate:
    """Instantiate author/reviewer substrate from skill YAML ``substrate`` field."""
    n = (substrate_name or "claude-code").strip().lower().replace("_", "-")
    if n in ("cursor",):
        return _cursor_substrate_from_args(args)
    if n in ("claude-code", "claude"):
        return ClaudeCodeSubstrate(
            cli_path=args.claude_bin,
            permission_mode=args.claude_permission_mode or None,
        )
    logging.getLogger(__name__).warning(
        "Unknown substrate %r — defaulting to claude-code", substrate_name
    )
    return ClaudeCodeSubstrate(cli_path=args.claude_bin)


def _emit_run_log(payload: dict, args: argparse.Namespace) -> None:
    if not args.no_run_log_print:
        print(format_human_report(payload), file=sys.stderr, end="")
    write_json(args.run_log, payload)


def _substrates_for_skill(skill_name: str, skills_dir: Path, args: argparse.Namespace) -> tuple[AgentSubstrate, AgentSubstrate | None]:
    """Load skill frontmatter and build author + reviewer substrates (not pragma app.yaml)."""
    spec = load_skill_spec(skills_dir, skill_name)
    author = _substrate_from_skill_name(spec.author_substrate or "claude-code", args)
    if spec.reviewer_substrate is None:
        reviewer: AgentSubstrate | None = None
    else:
        reviewer = _substrate_from_skill_name(spec.reviewer_substrate, args)
    return author, reviewer


def _load_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if args.prompt:
        return args.prompt
    return sys.stdin.read()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--folder",
        required=True,
        type=Path,
        help="Directory the agent may read (and optionally propose edits under review).",
    )
    p.add_argument("--substrate", choices=("claude", "cursor", "skill"), required=True)
    p.add_argument("--prompt", default="", help="Inline user prompt")
    p.add_argument("--prompt-file", type=Path, help="Read prompt from file (overrides --prompt)")
    p.add_argument("--skill", help="Skill name (without .md) when --substrate skill")
    p.add_argument(
        "--skills-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "skills",
        help="Directory containing <skill>.md definitions",
    )
    p.add_argument("--model", default="", help="Model id (optional; CLI default if empty)")
    p.add_argument("--timeout-ms", type=int, default=300_000)
    p.add_argument("--max-turns", type=int, default=50)
    p.add_argument(
        "--claude-permission-mode",
        default=os.environ.get("CLAUDE_PERMISSION_MODE") or "acceptEdits",
        help="Claude Code --permission-mode (default: acceptEdits, or CLAUDE_PERMISSION_MODE). "
        "Use plan if you want approval prompts for each edit.",
    )
    p.add_argument(
        "--cursor-write",
        action="store_true",
        help="Allow Cursor agent mode with --force (can apply edits without ask-mode).",
    )
    p.add_argument("--claude-bin", default=os.environ.get("CLAUDE_CODE_BIN", "claude"))
    p.add_argument("--cursor-bin", default=os.environ.get("CURSOR_CODE_BIN", ""))
    p.add_argument(
        "--cursor-api-key",
        default="",
        help="Cursor CLI --api-key (else CURSOR_API_KEY from the environment).",
    )
    p.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Load this .env before invoking CLIs (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, "
        "ANTHROPIC_BASE_URL, CURSOR_API_KEY, …). If omitted, uses PAPER_TOOLS_ENV_FILE or "
        "<repo>/.env when present.",
    )
    p.add_argument(
        "--env-override",
        action="store_true",
        help="Values from the env file override existing environment variables.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument(
        "--run-log",
        type=Path,
        default=None,
        help=f"JSON run log path (default: <folder>/{DEFAULT_RUN_LOG_NAME}).",
    )
    p.add_argument(
        "--no-run-log-print",
        action="store_true",
        help="Skip printing the human-readable run log to stderr (JSON file still written).",
    )
    return p


async def _run_claude(folder: Path, prompt: str, args: argparse.Namespace) -> None:
    sub = ClaudeCodeSubstrate(
        cli_path=args.claude_bin,
        permission_mode=args.claude_permission_mode or None,
    )
    folder = folder.resolve()
    prompt = augment_user_prompt_with_workspace(prompt, folder)
    cfg = SubstrateConfig(
        model=args.model or None,
        max_turns=args.max_turns,
        cwd=folder,
        additional_dirs=[folder],
        permission_mode=args.claude_permission_mode or None,
    )
    result = await sub.invoke(prompt, config=cfg, timeout_ms=args.timeout_ms)
    print(agent_run_to_text(result))
    if result.stderr:
        print("--- stderr ---", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
    payload = build_payload_direct(
        mode="claude",
        folder=str(folder.resolve()),
        result=result,
        attempts=1,
        configured_model=args.model or None,
    )
    payload["timeout_ms_per_invoke"] = args.timeout_ms
    _emit_run_log(payload, args)
    if result.exit_status != "success":
        sys.exit(1)


async def _run_cursor(folder: Path, prompt: str, args: argparse.Namespace) -> None:
    sub = _cursor_substrate_from_args(args)
    folder = folder.resolve()
    prompt = augment_user_prompt_with_workspace(prompt, folder)
    cfg = SubstrateConfig(
        model=args.model or None,
        max_turns=args.max_turns,
        cwd=folder,
        workspace_dir=folder,
        readonly=not args.cursor_write,
        mode=None if args.cursor_write else "ask",
    )
    result = await sub.invoke(prompt, config=cfg, timeout_ms=args.timeout_ms)
    print(agent_run_to_text(result))
    if result.stderr:
        print("--- stderr ---", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
    payload = build_payload_direct(
        mode="cursor",
        folder=str(folder.resolve()),
        result=result,
        attempts=1,
        configured_model=args.model or None,
    )
    payload["timeout_ms_per_invoke"] = args.timeout_ms
    _emit_run_log(payload, args)
    if result.exit_status != "success":
        sys.exit(1)


async def _run_skill(folder: Path, prompt: str, args: argparse.Namespace) -> None:
    if not args.skill:
        print("--skill is required when --substrate skill", file=sys.stderr)
        sys.exit(2)
    author, reviewer = _substrates_for_skill(args.skill, args.skills_dir, args)
    runner = SkillRunner(
        author,
        reviewer,
        args.skills_dir,
        workspace_root=folder.resolve(),
    )
    out = await runner.run(args.skill, prompt, timeout_ms=args.timeout_ms)
    print(out.output)
    sk_payload = build_skill_run_payload(str(folder.resolve()), out)
    sk_payload["timeout_ms_per_invoke"] = args.timeout_ms
    _emit_run_log(sk_payload, args)
    if not out.approved:
        if out.author_results:
            last = out.author_results[-1]
            if last.stderr and last.stderr.strip():
                print(
                    f"--- Author stderr ({last.substrate}, last attempt) ---",
                    file=sys.stderr,
                )
                print(last.stderr.strip(), file=sys.stderr)
        sys.exit(3)


def main() -> None:
    args = _build_parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    loaded = _bootstrap_env_from_file(args.env_file, override=args.env_override)
    if loaded and args.verbose:
        logging.getLogger(__name__).info("Loaded environment from %s", loaded)
    folder = args.folder
    if not folder.is_dir():
        print(f"Not a directory: {folder}", file=sys.stderr)
        sys.exit(2)
    folder = folder.resolve()
    if args.run_log is None:
        args.run_log = folder / DEFAULT_RUN_LOG_NAME
    else:
        args.run_log = args.run_log.expanduser().resolve()
    text = _load_prompt(args).strip()
    if not text:
        print("Empty prompt (use --prompt, --prompt-file, or stdin)", file=sys.stderr)
        sys.exit(2)

    if args.substrate == "claude":
        asyncio.run(_run_claude(folder, text, args))
    elif args.substrate == "cursor":
        asyncio.run(_run_cursor(folder, text, args))
    else:
        asyncio.run(_run_skill(folder, text, args))


if __name__ == "__main__":
    main()
