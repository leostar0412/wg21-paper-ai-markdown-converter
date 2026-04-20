#!/usr/bin/env python3
"""Orchestrate URL → Markdown ingestion, optional improve phases, bundle, and callback."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from paper_tools.callback_client import build_artifact_payload, post_callback
from paper_tools.workflow.orchestrator import run_workflow
from paper_tools.workflow.schema import WorkflowConfig, parse_config_dict


def _bootstrap_env_from_file(path: Path | None, *, override: bool) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    script_dir = Path(__file__).resolve().parent
    candidates: list[Path] = []
    if path is not None and path.is_file():
        candidates.append(path)
    else:
        ev = os.environ.get("PAPER_TOOLS_ENV_FILE", "").strip()
        if ev:
            candidates.append(Path(ev).expanduser().resolve())
        candidates.append(script_dir / ".env")
    for p in candidates:
        if p.is_file():
            load_dotenv(p, override=override)
            break


def _callback_on_validation_error(cfg_dict: dict | None, message: str) -> None:
    url = (cfg_dict or {}).get("callback_url")
    if not url:
        return
    token = (cfg_dict or {}).get("callback_auth_token") or os.environ.get(
        "CALLBACK_AUTH_TOKEN", ""
    )
    payload = build_artifact_payload(
        run_status="invalid_input",
        error_message=message,
        papers=[],
    )
    post_callback(str(url), payload, auth_token=token.strip() or None)


async def _async_main(args: argparse.Namespace) -> int:
    repo_root = (args.repo_root or Path(__file__).resolve().parent).resolve()
    skills_dir = (args.skills_dir or (repo_root / "skills")).resolve()

    if args.config_file:
        raw = json.loads(args.config_file.read_text(encoding="utf-8"))
    elif args.config_json.strip():
        raw = json.loads(args.config_json)
    else:
        print("Provide --config-file or --config-json", file=sys.stderr)
        return 2

    if not isinstance(raw, dict):
        print("Config must be a JSON object", file=sys.stderr)
        return 2

    try:
        cfg = parse_config_dict(raw)
    except Exception as e:
        _callback_on_validation_error(raw, str(e))
        print(f"Invalid config: {e}", file=sys.stderr)
        return 2

    cfg.apply_environment()
    # if not os.environ.get("CLAUDE_PERMISSION_MODE"):
    os.environ["CLAUDE_PERMISSION_MODE"] = "acceptEdits"

    run_root, result_payload, logs_payload = await run_workflow(
        cfg,
        repo_root=repo_root,
        skills_dir=skills_dir,
        fetch_timeout=args.fetch_timeout,
        improve_timeout_ms=args.improve_timeout_ms,
        skip_improve=args.skip_improve,
    )

    wf_url = os.environ.get("GITHUB_SERVER_URL", "").rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    workflow_run_url = (
        f"{wf_url}/{repo}/actions/runs/{run_id}"
        if wf_url and repo and run_id
        else None
    )

    papers_out = result_payload.get("papers", [])
    ok = result_payload.get("run_status") == "succeeded"

    if cfg.callback_url:
        token = (cfg.callback_auth_token or "").strip() or (
            os.environ.get("CALLBACK_AUTH_TOKEN", "") or None
        )
        cb_payload = build_artifact_payload(
            run_status="succeeded" if ok else "failed",
            workflow_run_url=workflow_run_url,
            repository=repo or None,
            run_id=run_id or None,
            papers=papers_out,
        )
        post_callback(str(cfg.callback_url), cb_payload, auth_token=token)

    if args.quiet:
        print(
            f"run_status={result_payload.get('run_status')} run_dir={run_root}",
            file=sys.stderr,
        )
    else:
        print(json.dumps(result_payload, indent=2, ensure_ascii=False))
        print(f"\nRun directory: {run_root}", file=sys.stderr)
    return 0 if ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config-file", type=Path, help="Workflow JSON file.")
    parser.add_argument(
        "--config-json",
        type=str,
        default="",
        help="Inline JSON (e.g. from GitHub Actions).",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Output root (default: directory of this script).",
    )
    parser.add_argument(
        "--skills-dir",
        type=Path,
        default=None,
        help="Skills directory (default: <repo>/skills).",
    )
    parser.add_argument(
        "--skip-improve",
        action="store_true",
        help="Download and convert only (no improve phases).",
    )
    parser.add_argument("--fetch-timeout", type=int, default=120)
    parser.add_argument("--improve-timeout-ms", type=int, default=None)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--env-override", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Minimal stderr logging (warnings/errors only) and no result JSON on stdout.",
    )
    args = parser.parse_args()

    if args.verbose and args.quiet:
        parser.error("cannot combine --verbose and --quiet")
    log_level = (
        logging.DEBUG
        if args.verbose
        else logging.WARNING
        if args.quiet
        else logging.INFO
    )
    logging.basicConfig(level=log_level, format="%(levelname)s %(message)s")
    _bootstrap_env_from_file(args.env_file, override=args.env_override)

    raise SystemExit(asyncio.run(_async_main(args)))


if __name__ == "__main__":
    main()
