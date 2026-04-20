"""Parse unified pragma-style skill .md files (forked from pragma-agent)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_SECTION_MARKER = re.compile(r"<!--\s*([\w]+)\s*-->")
_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


@dataclass
class SkillSpec:
    """Parsed skill definition from a unified .md file."""

    name: str = ""
    author_substrate: str = "claude-code"
    author_model: str = ""
    author_model_tier: str = ""
    author_allowed_tools: list[str] | None = None
    author_disallowed_tools: list[str] | None = None
    author_permission_mode: str | None = None
    author_max_turns: int | None = None
    author_timeout_ms: int | None = None
    reviewer_substrate: str | None = "cursor"
    reviewer_model: str = ""
    reviewer_model_tier: str = ""
    reviewer_allowed_tools: list[str] | None = None
    reviewer_disallowed_tools: list[str] | None = None
    reviewer_readonly: bool = True
    reviewer_max_turns: int | None = None
    reviewer_timeout_ms: int | None = None
    max_review_rounds: int = 3
    context_injections: list[dict] = field(default_factory=list)
    author_mcp_servers: list[str] | None = None
    reviewer_mcp_servers: list[str] | None = None
    author_mode: str | None = None
    reviewer_mode: str | None = None

    author_prompt: str = ""
    reviewer_prompt: str = ""
    templates: dict[str, str] = field(default_factory=dict)


def parse_skill_file(text: str) -> tuple[dict, dict[str, str]]:
    """Parse a unified skill .md file."""
    fm_match = _FRONTMATTER.match(text)
    if not fm_match:
        raise ValueError("Skill file missing YAML frontmatter (---...---)")
    frontmatter = yaml.safe_load(fm_match.group(1))
    if not isinstance(frontmatter, dict):
        raise ValueError("Skill frontmatter is not a YAML mapping")
    body = text[fm_match.end() :]

    parts = _SECTION_MARKER.split(body)
    sections: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        name = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections[name] = content

    return frontmatter, sections


def _load_shared_sections(search_dirs: list[Path]) -> dict[str, str]:
    """Load ``shared.md`` (fix_system / validate_system / fix_retry_guide) if present."""
    for d in search_dirs:
        candidate = d / "shared.md"
        if candidate.is_file():
            try:
                _, sections = parse_skill_file(candidate.read_text(encoding="utf-8"))
                return sections
            except ValueError:
                return {}
    return {}


def _assemble_default_author_prompt(
    templates: dict[str, str], shared: dict[str, str]
) -> str:
    parts = [
        shared.get("fix_system", "").strip(),
        templates.get("fix", "").strip(),
        shared.get("fix_retry_guide", "").strip(),
    ]
    return "\n\n".join(p for p in parts if p)


def _assemble_default_reviewer_prompt(
    templates: dict[str, str], shared: dict[str, str]
) -> str:
    parts = [
        shared.get("validate_system", "").strip(),
        templates.get("validate", "").strip(),
    ]
    return "\n\n".join(p for p in parts if p)


def load_skill_spec(
    skills_dir: Path | list[Path],
    skill_name: str,
    *,
    orchestrator_tier: str | None = None,
    author_substrate_override: str | None = None,
    reviewer_substrate_override: str | None = None,
) -> SkillSpec:
    """Load and parse a unified skill definition."""
    search_dirs = [skills_dir] if isinstance(skills_dir, Path) else skills_dir
    skill_path: Path | None = None
    for d in search_dirs:
        candidate = d / f"{skill_name}.md"
        if candidate.exists():
            skill_path = candidate
            break
    if skill_path is None:
        searched = ", ".join(str(d) for d in search_dirs)
        raise FileNotFoundError(
            f"Skill definition not found: {skill_name}.md (searched: {searched})"
        )

    text = skill_path.read_text(encoding="utf-8")
    fm, sections = parse_skill_file(text)

    # Default author/reviewer when omitted (unified skill body still has <!-- author --> / <!-- reviewer --> sections).
    if "author" not in fm:
        author = {"substrate": "claude-code"}
    else:
        a = fm.get("author")
        author = a if isinstance(a, dict) else {}

    reviewer_raw = fm.get("reviewer", {"substrate": "cursor", "readonly": True})
    reviewer_disabled = reviewer_raw is False
    reviewer = reviewer_raw if isinstance(reviewer_raw, dict) else {}

    templates: dict[str, str] = {}
    for key, value in sections.items():
        if key not in ("author", "reviewer"):
            templates[key] = value

    author_substrate = author.get("substrate", "claude-code")
    reviewer_substrate: str | None = (
        None if reviewer_disabled else reviewer.get("substrate", "cursor")
    )

    if author_substrate_override:
        author_substrate = author_substrate_override.strip()
    if reviewer_substrate_override is not None:
        rs = reviewer_substrate_override.strip()
        reviewer_substrate = rs or None

    author_model = author.get("model", "")
    reviewer_model = reviewer.get("model", "") if not reviewer_disabled else ""

    author_tier = author.get("model_tier", "")
    reviewer_tier = reviewer.get("model_tier", "") if not reviewer_disabled else ""

    if orchestrator_tier:
        author_tier = orchestrator_tier
        if not reviewer_disabled:
            reviewer_tier = orchestrator_tier

    # Same as pragma-agent: resolve tier → concrete model when model is omitted.
    if author_tier or reviewer_tier:
        from paper_tools.model_registry import resolve

        if author_tier and not author_model:
            author_model = resolve(author_tier, author_substrate) or ""
        if reviewer_tier and reviewer_substrate and not reviewer_model:
            reviewer_model = resolve(reviewer_tier, reviewer_substrate) or ""

    shared = _load_shared_sections(search_dirs)
    author_prompt = (sections.get("author") or "").strip()
    if not author_prompt:
        author_prompt = _assemble_default_author_prompt(templates, shared)

    reviewer_prompt = (sections.get("reviewer") or "").strip()
    if not reviewer_prompt and not reviewer_disabled:
        reviewer_prompt = _assemble_default_reviewer_prompt(templates, shared)

    return SkillSpec(
        name=fm.get("skill", skill_name),
        author_substrate=author_substrate,
        author_model=author_model,
        author_model_tier=author_tier,
        author_allowed_tools=author.get("allowed_tools"),
        author_disallowed_tools=author.get("disallowed_tools"),
        author_permission_mode=author.get("permission_mode"),
        author_max_turns=author.get("max_turns"),
        author_timeout_ms=author.get("timeout_ms"),
        reviewer_substrate=reviewer_substrate,
        reviewer_model=reviewer_model,
        reviewer_model_tier=reviewer_tier,
        reviewer_allowed_tools=reviewer.get("allowed_tools") if not reviewer_disabled else None,
        reviewer_disallowed_tools=reviewer.get("disallowed_tools") if not reviewer_disabled else None,
        reviewer_readonly=reviewer.get("readonly", True) if not reviewer_disabled else True,
        reviewer_max_turns=reviewer.get("max_turns") if not reviewer_disabled else None,
        reviewer_timeout_ms=reviewer.get("timeout_ms") if not reviewer_disabled else None,
        max_review_rounds=fm.get("max_review_rounds", 3),
        context_injections=fm.get("context_injections", []),
        author_mcp_servers=author.get("mcp_servers"),
        reviewer_mcp_servers=reviewer.get("mcp_servers") if not reviewer_disabled else None,
        author_mode=author.get("mode"),
        reviewer_mode=reviewer.get("mode") if not reviewer_disabled else None,
        author_prompt=author_prompt,
        reviewer_prompt=reviewer_prompt,
        templates=templates,
    )


def inject_placeholders(text: str, replacements: dict[str, str]) -> str:
    """Replace {placeholder} tokens in text with provided values."""
    result = text
    for key, value in replacements.items():
        result = result.replace(f"{{{key}}}", value)
    return result
