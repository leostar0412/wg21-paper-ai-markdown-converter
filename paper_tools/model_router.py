"""Model router — forked from pragma-agent ``core/config/model_router.py``."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from paper_tools.model_registry import resolve_all

logger = logging.getLogger(__name__)

_CIRCUIT_FAILURE_THRESHOLD = 3
_CIRCUIT_COOLDOWN_SECONDS = 120
_BACKOFF_BASE_SECONDS = 2.0
_BACKOFF_MAX_SECONDS = 60.0


@dataclass
class _CircuitState:
    consecutive_failures: int = 0
    unavailable_since: float | None = None


@dataclass
class ModelRouter:
    """Model selection with fallback rotation per tier+substrate (same as pragma-agent)."""

    _circuits: dict[str, _CircuitState] = field(default_factory=dict)
    _rotation_index: dict[str, int] = field(default_factory=dict)
    _full_rotation_count: dict[str, int] = field(default_factory=dict)

    def get_model(self, tier: str, substrate: str) -> str | None:
        models = resolve_all(tier, substrate)
        if not models:
            return None

        key = f"{tier}:{substrate}"
        for _ in range(len(models)):
            idx = self._rotation_index.get(key, 0) % len(models)
            candidate = models[idx]
            if self._is_available(candidate):
                return candidate
            self._rotation_index[key] = idx + 1

        logger.warning(
            "All models unavailable for %s/%s -- returning primary %s",
            tier, substrate, models[0],
        )
        self._circuits.pop(models[0], None)
        return models[0]

    def report_success(self, model: str) -> None:
        state = self._circuits.get(model)
        if state:
            state.consecutive_failures = 0
            state.unavailable_since = None

    def report_failure(self, model: str, tier: str, substrate: str) -> str | None:
        state = self._circuits.setdefault(model, _CircuitState())
        state.consecutive_failures += 1

        if state.consecutive_failures >= _CIRCUIT_FAILURE_THRESHOLD:
            state.unavailable_since = time.monotonic()
            logger.info(
                "Circuit open for model %s after %d consecutive failures",
                model, state.consecutive_failures,
            )

        key = f"{tier}:{substrate}"
        models = resolve_all(tier, substrate)
        if not models:
            return None

        idx = self._rotation_index.get(key, 0)
        next_idx = idx + 1
        self._rotation_index[key] = next_idx

        if next_idx >= len(models):
            rotation = self._full_rotation_count.get(key, 0) + 1
            self._full_rotation_count[key] = rotation
            self._rotation_index[key] = 0

        effective_idx = next_idx % len(models)
        return models[effective_idx]

    def get_backoff_seconds(self, tier: str, substrate: str) -> float:
        key = f"{tier}:{substrate}"
        rotations = self._full_rotation_count.get(key, 0)
        if rotations == 0:
            return 0.0
        delay = min(
            _BACKOFF_BASE_SECONDS * (2 ** (rotations - 1)),
            _BACKOFF_MAX_SECONDS,
        )
        return delay

    def _is_available(self, model: str) -> bool:
        state = self._circuits.get(model)
        if state is None:
            return True
        if state.unavailable_since is None:
            return True
        elapsed = time.monotonic() - state.unavailable_since
        if elapsed >= _CIRCUIT_COOLDOWN_SECONDS:
            state.unavailable_since = None
            state.consecutive_failures = 0
            return True
        return False
