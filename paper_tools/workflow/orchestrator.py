"""End-to-end ingestion: download → convert → layout excerpt → improve → bundle."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_tools.config import DEFAULT_MAX_TURNS, DEFAULT_TIMEOUT_MS
from paper_tools.convert import (
    convert_html_file_to_md,
    convert_pdf_path_to_md_v1,
    ingestion_run_dir_name,
    unique_stem,
)
from paper_tools.layout_excerpt import (
    html_excerpt_manifest_note,
    write_pdf_layout_json,
)
from paper_tools.substrate.base import AgentSubstrate, SubstrateConfig
from paper_tools.substrate.claude_code import ClaudeCodeSubstrate
from paper_tools.substrate.cursor import CursorSubstrate
from paper_tools.url_download import detect_type, download_into_paper_folder
from paper_tools.workflow.schema import WorkflowConfig
from paper_tools.workflow.skill_runner import SkillResult, SkillRunner
from paper_tools.workspace_context import augment_user_prompt_with_workspace

logger = logging.getLogger(__name__)


def _nl_norm(s: str) -> str:
    return (s or "").replace("\r\n", "\n").replace("\r", "\n")


def _content_key(s: str) -> str:
    """Normalize for comparison (line endings + trim)."""
    return _nl_norm(s).strip()


def _persist_approved_markdown_if_improved(
    md_path: Path, md_before: str, out: SkillResult
) -> dict[str, Any]:
    """
    After an approved author run, compare Markdown to the pre-phase snapshot.

    - If the file on disk already differs from ``md_before``, the author improved it in place — keep it.
    - Else if the stream body differs from ``md_before``, write that (full document from the author).
    - Otherwise leave the file unchanged.
    """
    before_k = _content_key(md_before)
    try:
        after_disk_raw = md_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Could not read %s after phase: %s", md_path, e)
        after_disk_raw = ""

    disk_k = _content_key(after_disk_raw)
    stream_raw = (out.output or "").strip()
    stream_k = _content_key(stream_raw)

    if disk_k != before_k:
        logger.info(
            "Phase approved: %s changed on disk vs pre-phase snapshot (keeping file as edited)",
            md_path.name,
        )
        return {
            "changed": True,
            "source": "disk",
            "reason": "on_disk_differs_from_before",
        }

    if stream_k and stream_k != before_k:
        # Authors sometimes return a short meta message ("no changes needed", analysis)
        # instead of the full document. Do not replace a long paper with that fragment.
        if len(md_before) >= 8000 and len(stream_raw) < 4000:
            logger.warning(
                "Phase approved but author stream is much shorter than pre-phase file "
                "(%d vs %d chars); not overwriting %s — likely meta-commentary, not full MD",
                len(stream_raw),
                len(md_before),
                md_path.name,
            )
            return {
                "changed": False,
                "source": "stream_rejected_short",
                "reason": "author_stream_suspiciously_shorter_than_baseline",
            }
        text = _nl_norm(stream_raw)
        if not text.endswith("\n"):
            text += "\n"
        md_path.write_text(text, encoding="utf-8")
        logger.info(
            "Phase approved: wrote author stream output to %s (file on disk had not changed)",
            md_path.name,
        )
        return {"changed": True, "source": "stream"}

    logger.info(
        "Phase approved: no Markdown change vs pre-phase snapshot for %s (stream and disk match baseline)",
        md_path.name,
    )
    return {
        "changed": False,
        "source": "none",
        "reason": "no_diff_from_before",
    }


def _author_could_not_run_skill(out: SkillResult) -> bool:
    """Skill ended early: author invoke failed or produced no output (cannot continue phases)."""
    for log in out.telemetry.get("round_logs") or []:
        if log.get("stopped_reason") in (
            "author_invoke_failed",
            "author_empty_output",
        ):
            return True
    return False


PHASE_SKILLS = [
    "headings",
    "code",
    "links",
    "tables",
    "lists",
    "line_breaks",
    "styles",
]


def substrate_route(cfg: WorkflowConfig) -> tuple[str, str]:
    """Return (author_substrate, reviewer_substrate) as registry keys."""
    c = cfg.claude_code
    has_claude = bool(c and (c.api_key.strip() or c.auth_token.strip()))
    u = cfg.cursor
    has_cursor = bool(u and u.api_key.strip())
    if has_claude and has_cursor:
        return "claude-code", "cursor"
    if has_claude:
        return "claude-code", "claude-code"
    return "cursor", "cursor"


def build_substrates(
    cfg: WorkflowConfig,
) -> tuple[AgentSubstrate, AgentSubstrate]:
    """Instantiate author and reviewer substrates (may be the same instance)."""
    c = cfg.claude_code
    has_claude = bool(c and (c.api_key.strip() or c.auth_token.strip()))
    u = cfg.cursor
    has_cursor = bool(u and u.api_key.strip())
    # Default matches SkillRunner + url2md: non-interactive authors may Edit/Write.
    _pm = os.environ.get("CLAUDE_PERMISSION_MODE") or "acceptEdits"
    claude = ClaudeCodeSubstrate(permission_mode=_pm) if has_claude else None
    cursor = CursorSubstrate(api_key=u.api_key.strip()) if has_cursor else None
    if claude and cursor:
        return claude, cursor
    if claude:
        return claude, claude
    assert cursor is not None
    return cursor, cursor


@dataclass
class PaperRecord:
    source_url: str
    stem: str
    file_type: str
    conversion_ok: bool = False
    conversion_error: str | None = None
    layout_json_path: str | None = None
    baseline_approved: bool | None = None
    phases: list[dict[str, Any]] = field(default_factory=list)
    final_ok: bool = False
    status_reason: str = ""


async def _baseline_review(
    reviewer: AgentSubstrate,
    workspace: Path,
    md_text: str,
    excerpt_note: str,
    tier_id: str,
    reviewer_substrate: str,
    timeout_ms: int,
    parse_runner: SkillRunner,
) -> bool:
    from paper_tools.model_registry import resolve

    model = resolve(tier_id, reviewer_substrate) or None
    cfg = SubstrateConfig(
        model=model,
        max_turns=DEFAULT_MAX_TURNS,
        cwd=workspace,
        workspace_dir=workspace,
        additional_dirs=[workspace],
        readonly=True,
        mode="ask",
    )
    prompt = augment_user_prompt_with_workspace(
        f"""## First-pass Markdown sanity review

{excerpt_note}

## Document text

{md_text[:200000]}
""",
        workspace,
    )
    system = (
        "You review a first-pass Markdown conversion before structured editing. "
        "Output a YAML block with `verdict: approve` or `verdict: request_changes` "
        "and optional `comments` (list of field/problem/fix) like other reviewers in this project."
    )
    result = await reviewer.invoke(
        prompt,
        system_prompt=system,
        config=cfg,
        timeout_ms=timeout_ms,
    )
    if result.exit_status != "success":
        logger.warning(
            "Baseline reviewer invocation failed: %s", result.exit_status
        )
        return False
    verdict = parse_runner._parse_review_verdict(result)
    if verdict is None:
        return True
    return verdict.get("verdict") == "approve"


async def run_workflow(
    cfg: WorkflowConfig,
    *,
    repo_root: Path,
    skills_dir: Path,
    fetch_timeout: int = 120,
    improve_timeout_ms: int | None = None,
    skip_improve: bool = False,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """
    Execute the full pipeline under
    ``repo_root / temp / ingestion_run_<hash12>_<UTC>_<url_stem>``.

    Returns ``(run_root, result_dict, logs_dict)``.
    """
    cfg.apply_environment()
    improve_timeout_ms = improve_timeout_ms or int(
        os.environ.get("PAPER_IMPROVE_TIMEOUT_MS", str(DEFAULT_TIMEOUT_MS))
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    temp_root = (repo_root / "temp").resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    run_name = ingestion_run_dir_name(cfg.papers, ts)
    run_root = (temp_root / run_name).resolve()
    papers_root = run_root / "papers"
    out_md = run_root / "outputs" / "markdown"
    papers_root.mkdir(parents=True, exist_ok=True)
    out_md.mkdir(parents=True, exist_ok=True)

    author_sub, reviewer_sub = build_substrates(cfg)
    auth_name, rev_name = substrate_route(cfg)
    tier_id = cfg.tier_id()

    # Dummy runner only for _parse_review_verdict (baseline)
    parse_runner = SkillRunner(
        author_sub,
        reviewer_sub,
        skills_dir,
        workspace_root=papers_root,
    )

    used_stems: set[str] = set()
    paper_records: list[PaperRecord] = []
    logs: dict[str, Any] = {
        "schema_version": 1,
        "ingestion_root": str(run_root),
        "tier_id": tier_id,
        "papers": [],
    }

    for url in cfg.papers:
        stem = unique_stem(url, used_stems)
        pr = PaperRecord(source_url=url, stem=stem, file_type=detect_type(url))
        paper_dir = papers_root / stem
        md_path = paper_dir / f"{stem}.md"

        ft, ok_dl, err_dl = download_into_paper_folder(
            url, paper_dir, fetch_timeout=fetch_timeout
        )
        pr.file_type = ft
        if not ok_dl:
            pr.conversion_ok = False
            pr.final_ok = False
            pr.conversion_error = err_dl or "download failed"
            pr.status_reason = pr.conversion_error
            paper_records.append(pr)
            continue

        if ft == "pdf":
            pdf_path = paper_dir / "source.pdf"
            ok_conv = convert_pdf_path_to_md_v1(pdf_path, md_path)
            if ok_conv:
                write_pdf_layout_json(
                    pdf_path, paper_dir / f"{stem}.layout.json"
                )
                pr.layout_json_path = str(paper_dir / f"{stem}.layout.json")
        else:
            html_path = paper_dir / "source.html"
            ok_conv = convert_html_file_to_md(html_path, md_path)
            pr.conversion_error = (
                None if ok_conv else "html pandoc conversion failed"
            )

        pr.conversion_ok = ok_conv
        if not ok_conv:
            pr.final_ok = False
            pr.status_reason = pr.conversion_error or "conversion failed"
            paper_records.append(pr)
            continue

        excerpt_note = ""
        if ft == "pdf":
            excerpt_note = (
                f"Layout excerpt JSON: `{stem}.layout.json` (PDF structure). "
                "Use it as ground truth for tables and layout where applicable."
            )
        else:
            excerpt_note = (
                f"HTML source (structural excerpt): `source.html`. "
                f"{html_excerpt_manifest_note()}"
            )

        md_text = md_path.read_text(encoding="utf-8")

        if not skip_improve:
            base_ok = await _baseline_review(
                reviewer_sub,
                paper_dir,
                md_text,
                excerpt_note,
                tier_id,
                rev_name,
                improve_timeout_ms,
                parse_runner,
            )
            pr.baseline_approved = base_ok

            runner = SkillRunner(
                author_sub,
                reviewer_sub,
                skills_dir,
                workspace_root=paper_dir,
            )

            for phase in PHASE_SKILLS:
                phase_log: dict[str, Any] = {"phase": phase}
                user_prompt = augment_user_prompt_with_workspace(
                    f"""## Task context
- Primary Markdown file: `{stem}.md`
- Source type: {ft}
- {excerpt_note}

Follow the skill instructions for phase **{phase}**. Edit `{stem}.md` in place as needed.
""",
                    paper_dir,
                )
                try:
                    md_before_phase = md_path.read_text(encoding="utf-8")
                    out = await runner.run(
                        phase,
                        user_prompt,
                        timeout_ms=improve_timeout_ms,
                        model_tier_override=tier_id,
                        author_substrate_override=auth_name,
                        reviewer_substrate_override=rev_name,
                    )
                    phase_log["approved"] = out.approved
                    phase_log["rounds"] = out.rounds
                    phase_log["telemetry"] = out.telemetry
                    if out.approved:
                        phase_log["markdown_persist"] = (
                            _persist_approved_markdown_if_improved(
                                md_path, md_before_phase, out
                            )
                        )
                    pr.phases.append(phase_log)
                    if not out.approved:
                        if _author_could_not_run_skill(out):
                            pr.status_reason = f"phase {phase}: author invoke failed or empty output"
                            continue
                        logger.warning(
                            "Phase %s did not reach validator approval after max "
                            "rounds — continuing with remaining phases",
                            phase,
                        )
                        phase_log["continued_after_no_approval"] = True
                except Exception as e:
                    logger.exception("Phase %s failed", phase)
                    phase_log["error"] = str(e)
                    pr.phases.append(phase_log)
                    pr.status_reason = f"phase {phase} error: {e}"
                    continue

            pr.final_ok = len(pr.phases) == len(PHASE_SKILLS) and all(
                p.get("approved") is True for p in pr.phases
            )
            if not pr.status_reason:
                if pr.final_ok:
                    pr.status_reason = "ok"
                else:
                    unapproved = [
                        p["phase"]
                        for p in pr.phases
                        if p.get("approved") is not True
                    ]
                    if unapproved:
                        pr.status_reason = (
                            "validation not reached after max rounds for: "
                            + ", ".join(unapproved)
                        )
                    else:
                        pr.status_reason = "incomplete or failed phases"
        else:
            pr.final_ok = True
            pr.status_reason = "improve skipped"

        dest_md = out_md / f"{stem}.md"
        if md_path.is_file():
            shutil.copy2(md_path, dest_md)
        paper_records.append(pr)

    # result.json
    run_ok = bool(paper_records) and all(p.final_ok for p in paper_records)
    result_payload: dict[str, Any] = {
        "schema_version": 1,
        "run_status": "succeeded" if run_ok else "failed",
        "ingestion_root": str(run_root),
        "papers": [
            {
                "source_url": p.source_url,
                "stem": p.stem,
                "file_type": p.file_type,
                "conversion_ok": p.conversion_ok,
                "conversion_error": p.conversion_error,
                "final_ok": p.final_ok,
                "status_reason": p.status_reason,
                "phases": p.phases,
            }
            for p in paper_records
        ],
    }

    logs["papers"] = result_payload["papers"]
    logs["substrate_route"] = {"author": auth_name, "reviewer": rev_name}

    result_path = run_root / "result.json"
    logs_path = run_root / "logs.json"
    result_path.write_text(
        json.dumps(result_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logs_path.write_text(
        json.dumps(logs, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    bundle = run_root / "outputs" / "bundle.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in out_md.glob("*.md"):
            zf.write(f, f"markdown/{f.name}")
        zf.writestr("result.json", result_path.read_text(encoding="utf-8"))
        zf.writestr("logs.json", logs_path.read_text(encoding="utf-8"))

    return run_root, result_payload, logs
