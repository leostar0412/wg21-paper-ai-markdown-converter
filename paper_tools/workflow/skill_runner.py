"""Skill runner — author/reviewer loop forked from pragma-agent (no SessionTracker / workspace)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from paper_tools.config import DEFAULT_MAX_TURNS
from paper_tools.substrate.base import (
    AgentRunResult,
    AgentSubstrate,
    SubstrateConfig,
)
from paper_tools.agent_run_log import agent_run_result_to_dict
from paper_tools.textutil import strip_outer_fences
from paper_tools.workspace_context import augment_user_prompt_with_workspace
from paper_tools.model_router import ModelRouter
from paper_tools.workflow.skill_spec import (
    inject_placeholders,
    load_skill_spec,
)

logger = logging.getLogger(__name__)

MAX_SUBSTRATE_RETRIES = 3


@dataclass
class ReviewRound:
    round_number: int
    author_output: str = ""
    reviewer_verdict: str = ""
    reviewer_comments: list[dict] = field(default_factory=list)


@dataclass
class DisagreementReport:
    skill_name: str
    total_rounds: int
    rounds: list[ReviewRound] = field(default_factory=list)
    author_final_output: str = ""
    unresolved_items: list[dict] = field(default_factory=list)

    def format_for_team_lead(self) -> str:
        lines = [
            f"# Disagreement Report: {self.skill_name}",
            f"Rounds completed: {self.total_rounds}",
            "",
        ]
        for r in self.rounds:
            lines.append(f"## Round {r.round_number}")
            lines.append("### Author Output (truncated)")
            lines.append(r.author_output[:1500])
            lines.append(f"\n### Reviewer Verdict: {r.reviewer_verdict}")
            lines.append("")
        return "\n".join(lines)


@dataclass
class SkillResult:
    output: str
    approved: bool
    rounds: int
    author_results: list[AgentRunResult] = field(default_factory=list)
    reviewer_results: list[AgentRunResult] = field(default_factory=list)
    disagreement: DisagreementReport | None = None
    reviewer_skipped: bool = False
    # Per-invocation retry counts (parallel to author_results / reviewer_results)
    telemetry: dict[str, Any] = field(default_factory=dict)


class SkillRunner:
    """Executes pragma-style skills with an author/reviewer loop."""

    def __init__(
        self,
        author_substrate: AgentSubstrate,
        reviewer_substrate: AgentSubstrate | None,
        skills_dir: Path | list[Path],
        workspace_root: Path | None = None,
        default_context: dict[str, str] | None = None,
    ):
        self.author_substrate = author_substrate
        self.reviewer_substrate = reviewer_substrate
        self.skills_dir = skills_dir
        self.workspace_root = workspace_root
        self.default_context = dict(default_context or {})
        self.model_router = ModelRouter()

    async def run(
        self,
        skill_name: str,
        user_prompt: str,
        context: dict[str, str] | None = None,
        timeout_ms: int = 60_000,
        *,
        model_tier_override: str | None = None,
        author_substrate_override: str | None = None,
        reviewer_substrate_override: str | None = None,
    ) -> SkillResult:
        spec = load_skill_spec(
            self.skills_dir,
            skill_name,
            orchestrator_tier=model_tier_override,
            author_substrate_override=author_substrate_override,
            reviewer_substrate_override=reviewer_substrate_override,
        )

        replacements: dict[str, str] = dict(spec.templates)
        replacements.update(self.default_context)
        if context:
            replacements.update(context)

        author_system = inject_placeholders(spec.author_prompt, replacements)
        reviewer_system = inject_placeholders(
            spec.reviewer_prompt, replacements
        )

        author_timeout = spec.author_timeout_ms or timeout_ms
        reviewer_timeout = spec.reviewer_timeout_ms or timeout_ms

        ws = self.workspace_root
        extra_dirs = [ws] if ws else None

        # Non-interactive pipeline: allow file edits without prompting (--permission-mode).
        # If a skill sets author.permission_mode explicitly, that wins.
        author_pm = spec.author_permission_mode
        if author_pm is None:
            author_pm = os.environ.get("CLAUDE_PERMISSION_MODE") or "acceptEdits"

        author_config = SubstrateConfig(
            model=spec.author_model or None,
            max_turns=spec.author_max_turns or DEFAULT_MAX_TURNS,
            allowed_tools=spec.author_allowed_tools,
            disallowed_tools=spec.author_disallowed_tools,
            permission_mode=author_pm,
            mode=spec.author_mode,
            cwd=ws,
            additional_dirs=extra_dirs,
            workspace_dir=ws,
        )
        reviewer_config = SubstrateConfig(
            model=spec.reviewer_model or None,
            max_turns=spec.reviewer_max_turns or DEFAULT_MAX_TURNS,
            readonly=spec.reviewer_readonly,
            allowed_tools=spec.reviewer_allowed_tools,
            disallowed_tools=spec.reviewer_disallowed_tools,
            mode=spec.reviewer_mode,
            cwd=ws,
            workspace_dir=ws,
            mcp_servers=None,
        )

        has_reviewer = (
            spec.reviewer_substrate is not None
            and self.reviewer_substrate is not None
        )

        author_results: list[AgentRunResult] = []
        reviewer_results: list[AgentRunResult] = []
        author_attempts: list[int] = []
        reviewer_attempts: list[int] = []

        # First author turn only: bind "this folder" to cwd/--folder (same idea as pragma runs).
        current_prompt = augment_user_prompt_with_workspace(user_prompt, ws)
        final_output = ""
        approved = False

        author_session_id: str | None = None
        reviewer_session_id: str | None = None
        review_rounds: list[ReviewRound] = []
        round_logs: list[dict[str, Any]] = []

        for round_num in range(1, spec.max_review_rounds + 1):
            is_resume = round_num > 1

            author_result, auth_try = await self._invoke_with_retry(
                self.author_substrate,
                current_prompt,
                author_system if not is_resume else None,
                author_config,
                author_timeout,
                f"{spec.name}-author-r{round_num}",
                resume_session_id=author_session_id if is_resume else None,
                model_tier=spec.author_model_tier,
                substrate_name=spec.author_substrate,
            )
            author_session_id = author_result.session_id
            author_results.append(author_result)
            author_attempts.append(auth_try)

            if author_result.exit_status != "success":
                logger.warning(
                    "Author failed after retries (status=%s)",
                    author_result.exit_status,
                )
                round_logs.append(
                    {
                        "round": round_num,
                        "author": agent_run_result_to_dict(author_result),
                        "stopped_reason": "author_invoke_failed",
                    }
                )
                break

            final_output = self._extract_output(author_result)
            if not final_output:
                logger.warning("Author produced no output")
                round_logs.append(
                    {
                        "round": round_num,
                        "author": agent_run_result_to_dict(author_result),
                        "author_output_chars": 0,
                        "stopped_reason": "author_empty_output",
                    }
                )
                break

            if not has_reviewer:
                round_logs.append(
                    {
                        "round": round_num,
                        "author": agent_run_result_to_dict(author_result),
                        "author_output_chars": len(final_output),
                        "reviewer_skipped": True,
                    }
                )
                approved = True
                break

            review_prompt = (
                f"## Revised Agent Output\n{final_output}"
                if is_resume
                else (
                    f"## Original Task\n{user_prompt}\n\n"
                    f"## Agent Output to Review\n{final_output}"
                )
            )

            reviewer_result, rev_try = await self._invoke_with_retry(
                self.reviewer_substrate,
                review_prompt,
                reviewer_system if not is_resume else None,
                reviewer_config,
                reviewer_timeout,
                f"{spec.name}-reviewer-r{round_num}",
                resume_session_id=reviewer_session_id if is_resume else None,
                model_tier=spec.reviewer_model_tier,
                substrate_name=spec.reviewer_substrate or "",
            )
            reviewer_session_id = reviewer_result.session_id
            reviewer_results.append(reviewer_result)
            reviewer_attempts.append(rev_try)

            if reviewer_result.exit_status != "success":
                logger.warning(
                    "Reviewer failed (status=%s) — skipping review this round",
                    reviewer_result.exit_status,
                )
                round_logs.append(
                    {
                        "round": round_num,
                        "author": agent_run_result_to_dict(author_result),
                        "author_output_chars": len(final_output),
                        "reviewer": agent_run_result_to_dict(reviewer_result),
                        "reviewer_verdict": f"invoke_failed:{reviewer_result.exit_status}",
                    }
                )
                continue

            verdict = self._parse_review_verdict(reviewer_result)
            if verdict is None:
                logger.warning("Reviewer returned non-conforming output")
                round_logs.append(
                    {
                        "round": round_num,
                        "author": agent_run_result_to_dict(author_result),
                        "author_output_chars": len(final_output),
                        "reviewer": agent_run_result_to_dict(reviewer_result),
                        "reviewer_verdict": "non_conforming",
                    }
                )
                continue

            if verdict["verdict"] == "approve":
                review_rounds.append(
                    ReviewRound(
                        round_number=round_num,
                        author_output=final_output,
                        reviewer_verdict="approve",
                    )
                )
                round_logs.append(
                    {
                        "round": round_num,
                        "author": agent_run_result_to_dict(author_result),
                        "author_output_chars": len(final_output),
                        "reviewer": agent_run_result_to_dict(reviewer_result),
                        "reviewer_verdict": "approve",
                    }
                )
                approved = True
                break

            comments = verdict.get("comments", [])
            review_rounds.append(
                ReviewRound(
                    round_number=round_num,
                    author_output=final_output,
                    reviewer_verdict="request_changes",
                    reviewer_comments=comments,
                )
            )
            round_logs.append(
                {
                    "round": round_num,
                    "author": agent_run_result_to_dict(author_result),
                    "author_output_chars": len(final_output),
                    "reviewer": agent_run_result_to_dict(reviewer_result),
                    "reviewer_verdict": "request_changes",
                    "reviewer_comments": comments,
                }
            )
            feedback_lines = []
            for i, c in enumerate(comments, 1):
                fld = c.get("field", "?")
                problem = c.get("problem", "")
                fix = c.get("fix", "")
                feedback_lines.append(f"{i}. **{fld}**: {problem}. {fix}")
            feedback_text = "\n".join(feedback_lines)
            current_prompt = (
                "## Revision Request\n\n"
                "The reviewer identified the following issues:\n\n"
                f"{feedback_text}\n\n"
                "Please fix only the listed issues and produce the complete corrected output."
            )

        disagreement: DisagreementReport | None = None
        if not approved:
            unresolved = []
            if review_rounds:
                unresolved = review_rounds[-1].reviewer_comments
            disagreement = DisagreementReport(
                skill_name=spec.name,
                total_rounds=len(review_rounds),
                rounds=review_rounds,
                author_final_output=final_output,
                unresolved_items=unresolved,
            )
            logger.warning(
                "Skill %s finished without approval — see disagreement report in result",
                spec.name,
            )

        all_reviewers_failed = (
            has_reviewer
            and len(reviewer_results) > 0
            and all(r.exit_status != "success" for r in reviewer_results)
        )

        return SkillResult(
            output=final_output,
            approved=approved,
            rounds=len(author_results),
            author_results=author_results,
            reviewer_results=reviewer_results,
            disagreement=disagreement,
            reviewer_skipped=all_reviewers_failed,
            telemetry={
                "skill_name": spec.name,
                "author_model_configured": spec.author_model or "",
                "reviewer_model_configured": spec.reviewer_model or "",
                "author_attempts": author_attempts,
                "reviewer_attempts": reviewer_attempts,
                "skill_approved": approved,
                "extracted_output_chars": len(final_output),
                "round_logs": round_logs,
            },
        )

    async def _invoke_with_retry(
        self,
        substrate: AgentSubstrate,
        prompt: str,
        system_prompt: str | None,
        config: SubstrateConfig,
        timeout_ms: int,
        label: str,
        *,
        resume_session_id: str | None = None,
        model_tier: str = "",
        substrate_name: str = "",
    ) -> tuple[AgentRunResult, int]:
        """Return (final result, number of invoke attempts used, 1..MAX)."""
        result: AgentRunResult | None = None
        for attempt in range(1, MAX_SUBSTRATE_RETRIES + 1):
            if attempt > 1 and model_tier and substrate_name:
                backoff = self.model_router.get_backoff_seconds(
                    model_tier, substrate_name
                )
                if backoff > 0:
                    await asyncio.sleep(backoff)

            result = await substrate.invoke(
                prompt=prompt,
                system_prompt=system_prompt,
                config=config,
                timeout_ms=timeout_ms,
                resume_session_id=resume_session_id,
            )

            if getattr(result, "authentication_failed", False):
                logger.warning(
                    "[%s] authentication_failed in stream-json — abort retries "
                    "(check API keys / `claude login` for Claude Code)",
                    label,
                )
                return result, attempt

            if result.exit_status == "success":
                if config.model:
                    self.model_router.report_success(config.model)
                return result, attempt

            detail = ""
            if result.stderr and result.stderr.strip():
                detail = result.stderr.strip()[:2000]
                logger.warning(
                    "[%s] attempt %d/%d failed (status=%s). stderr:\n%s",
                    label,
                    attempt,
                    MAX_SUBSTRATE_RETRIES,
                    result.exit_status,
                    detail,
                )
            else:
                logger.warning(
                    "[%s] attempt %d/%d failed (status=%s)",
                    label,
                    attempt,
                    MAX_SUBSTRATE_RETRIES,
                    result.exit_status,
                )
            if config.model and result.exit_status == "failure":
                _cli = (
                    "Claude Code (`claude`)"
                    if substrate_name in ("claude-code", "claude", "")
                    else "Cursor CLI (`agent`)"
                    if substrate_name == "cursor"
                    else f"substrate {substrate_name!r}"
                )
                logger.warning(
                    "[%s] If this repeats, check that `model: %s` is valid for %s "
                    "(or omit `model` in the skill to use the CLI default).",
                    label,
                    config.model,
                    _cli,
                )

            if model_tier and substrate_name and config.model:
                fallback = self.model_router.report_failure(
                    config.model, model_tier, substrate_name
                )
                if fallback and fallback != config.model:
                    config = SubstrateConfig(
                        model=fallback,
                        max_turns=config.max_turns,
                        max_budget_usd=config.max_budget_usd,
                        readonly=config.readonly,
                        allowed_tools=config.allowed_tools,
                        disallowed_tools=config.disallowed_tools,
                        permission_mode=config.permission_mode,
                        cwd=config.cwd,
                        additional_dirs=config.additional_dirs,
                        workspace_dir=config.workspace_dir,
                        env_overrides=config.env_overrides,
                        mcp_servers=config.mcp_servers,
                        strict_mcp=config.strict_mcp,
                        mode=config.mode,
                    )

        assert result is not None
        return result, MAX_SUBSTRATE_RETRIES

    def _extract_output(self, result: AgentRunResult) -> str:
        if result.parsed_output:
            if isinstance(result.parsed_output, dict):
                text = result.parsed_output.get("text", "")
                if text:
                    return strip_outer_fences(text)
                return yaml.dump(
                    result.parsed_output,
                    default_flow_style=False,
                    sort_keys=False,
                )
            return strip_outer_fences(str(result.parsed_output))
        return strip_outer_fences(result.raw_output)

    def _parse_review_verdict(self, result: AgentRunResult) -> dict | None:
        raw = self._extract_output(result)
        if (
            not raw
            and result.parsed_output
            and isinstance(result.parsed_output, dict)
        ):
            raw = result.parsed_output.get("text", "")
        cleaned = strip_outer_fences(raw).strip()

        pass_verdict = SkillRunner._parse_pass_json_verdict(cleaned)
        if pass_verdict is not None:
            return pass_verdict

        for prefix in ("verdict:", "verdict :"):
            idx = cleaned.find(prefix)
            if idx > 0:
                cleaned = cleaned[idx:]
                break

        parsed: dict | None = None
        try:
            result_yaml = yaml.safe_load(cleaned)
            if isinstance(result_yaml, dict) and "verdict" in result_yaml:
                parsed = result_yaml
        except yaml.YAMLError:
            pass

        if parsed is None:
            m = re.search(r"verdict:\s*(approve|request_changes)", cleaned)
            if not m:
                return None
            if m.group(1) == "approve":
                return {"verdict": "approve"}
            comments = self._extract_comments_fallback(cleaned)
            if comments:
                return {"verdict": "request_changes", "comments": comments}
            return {
                "verdict": "request_changes",
                "comments": [
                    {
                        "field": "unknown",
                        "problem": "Review requested changes (details in raw output)",
                        "fix": "",
                    }
                ],
            }

        verdict = str(parsed["verdict"]).strip().lower()
        if verdict == "approve":
            return {"verdict": "approve"}
        if verdict == "request_changes":
            comments = parsed.get("comments", [])
            if isinstance(comments, list) and comments:
                return {"verdict": "request_changes", "comments": comments}
            return {
                "verdict": "request_changes",
                "comments": [
                    {
                        "field": "unknown",
                        "problem": "Review requested changes (comments unparseable)",
                        "fix": "",
                    }
                ],
            }
        return None

    @staticmethod
    def _parse_pass_json_verdict(cleaned: str) -> dict | None:
        """Map ``shared.md`` validator output ``{"pass": true/false, ...}`` to approve / request_changes."""
        blob = SkillRunner._first_json_object(cleaned)
        if not blob:
            return None
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or "pass" not in data:
            return None
        if data.get("pass") is True:
            return {"verdict": "approve"}
        reason = ""
        if isinstance(data.get("reason"), str):
            reason = data["reason"]
        ex = data.get("example")
        if ex is not None and not isinstance(ex, str):
            ex = str(ex)
        comments: list[dict] = []
        if reason or ex:
            line = reason or "validation failed"
            if ex:
                line = f"{line} — example: {ex}"
            comments.append(
                {
                    "field": "validation",
                    "problem": line,
                    "fix": "",
                }
            )
        else:
            comments.append(
                {
                    "field": "validation",
                    "problem": "Validator reported pass: false (no reason text)",
                    "fix": "",
                }
            )
        return {"verdict": "request_changes", "comments": comments}

    @staticmethod
    def _first_json_object(text: str) -> str | None:
        """Return the first substring that ``json.JSONDecoder`` can parse as an object."""
        start = 0
        while True:
            i = text.find("{", start)
            if i < 0:
                return None
            try:
                _obj, end = json.JSONDecoder().raw_decode(text, i)
                return text[i:end]
            except json.JSONDecodeError:
                start = i + 1

    @staticmethod
    def _extract_comments_fallback(text: str) -> list[dict]:
        comments = []
        for m in re.finditer(
            r"-\s*field:\s*(.+?)\n\s*problem:\s*(.+?)(?:\n\s*fix:\s*(.+?))?(?=\n\s*-|\Z)",
            text,
            re.DOTALL,
        ):
            comments.append(
                {
                    "field": m.group(1).strip(),
                    "problem": m.group(2).strip(),
                    "fix": (m.group(3) or "").strip(),
                }
            )
        return comments
