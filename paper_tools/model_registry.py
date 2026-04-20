"""Model tier registry — forked from pragma-agent ``core/model_registry.py``."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_tiers: dict[str, TierRecord] = {}
_alias_map: dict[str, str] = {}


@dataclass
class TierRecord:
    tier_id: str
    name: str
    intelligence: int
    cost: str
    models: dict[str, list[str]] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)


def load_registry(project_root: Path) -> dict[str, TierRecord]:
    global _tiers, _alias_map

    registry_path = project_root / "model-registry.yaml"
    if not registry_path.exists():
        logger.warning("No model-registry.yaml found at %s", registry_path)
        return _tiers

    data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    tiers_data = data.get("tiers", {})

    _tiers = {}
    _alias_map = {}

    for tier_id, tier_info in tiers_data.items():
        raw_models = tier_info.get("models", {})
        normalised: dict[str, list[str]] = {}
        for substrate, val in raw_models.items():
            if isinstance(val, list):
                normalised[substrate] = val
            else:
                normalised[substrate] = [val]
        record = TierRecord(
            tier_id=str(tier_id),
            name=tier_info.get("name", tier_id),
            intelligence=tier_info.get("intelligence", 0),
            cost=tier_info.get("cost", "unknown"),
            models=normalised,
            aliases=tier_info.get("aliases", []),
        )
        _tiers[str(tier_id)] = record
        for alias in record.aliases:
            _alias_map[alias.lower()] = str(tier_id)

    logger.debug(
        "Loaded %d model tiers from %s",
        len(_tiers),
        registry_path,
    )
    return _tiers


def _registry_root() -> Path:
    """Repo root: parent of ``paper_tools/``."""
    return Path(__file__).resolve().parents[1]


def _ensure_loaded() -> None:
    if not _tiers:
        load_registry(_registry_root())


def resolve(tier: str, substrate: str) -> str | None:
    """Resolve a tier + substrate to the primary (first) model name."""
    models = resolve_all(tier, substrate)
    return models[0] if models else None


def resolve_all(tier: str, substrate: str) -> list[str]:
    """Return primary + fallback model names for a tier + substrate."""
    _ensure_loaded()
    tier_id = _alias_map.get(tier.lower(), tier)
    record = _tiers.get(tier_id)
    if not record:
        logger.warning("Unknown model tier: %s", tier)
        return []

    models = record.models.get(substrate, [])
    if not models:
        logger.warning("No model for substrate %s in tier %s", substrate, tier_id)
    return models
