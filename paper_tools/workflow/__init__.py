"""Workflow: config, orchestration, skill runner, and skill specs."""

from __future__ import annotations

from typing import Any

from paper_tools.workflow.skill_runner import (
    DisagreementReport,
    ReviewRound,
    SkillResult,
    SkillRunner,
)
from paper_tools.workflow.skill_spec import (
    SkillSpec,
    inject_placeholders,
    load_skill_spec,
    parse_skill_file,
)

__all__ = [
    "DisagreementReport",
    "ReviewRound",
    "SkillResult",
    "SkillRunner",
    "SkillSpec",
    "WorkflowConfig",
    "inject_placeholders",
    "load_skill_spec",
    "parse_config_dict",
    "parse_skill_file",
    "run_workflow",
]


def __getattr__(name: str) -> Any:
    """Lazy imports so ``import paper_tools.workflow`` does not load PDF/HTML converters."""
    if name == "run_workflow":
        from paper_tools.workflow.orchestrator import run_workflow

        return run_workflow
    if name == "WorkflowConfig":
        from paper_tools.workflow.schema import WorkflowConfig

        return WorkflowConfig
    if name == "parse_config_dict":
        from paper_tools.workflow.schema import parse_config_dict

        return parse_config_dict
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
