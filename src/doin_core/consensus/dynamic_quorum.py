"""Dynamic quorum sizing — scales evaluator requirements with network conditions."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DynamicQuorumConfig:
    """Tuning knobs for dynamic quorum sizing."""

    base: int = 3
    min_quorum: int = 3
    max_quorum_cap: int = 15
    # activity_bonus thresholds: (level_threshold, bonus)
    activity_thresholds: tuple[tuple[float, int], ...] = (
        (0.75, 3),
        (0.50, 2),
        (0.25, 1),
    )
    # reputation_discount thresholds: (rep_threshold, discount)
    reputation_thresholds: tuple[tuple[float, int], ...] = (
        (0.9, 2),
        (0.7, 1),
    )


class DynamicQuorum:
    """Compute quorum sizes that adapt to network state.

    Formula::

        quorum = clamp(
            base + floor(log2(active_evaluators)) + activity_bonus - reputation_discount,
            min_quorum,
            max_quorum,
        )

    Where ``max_quorum = min(max_quorum_cap, active_evaluators // 2)``.
    """

    def __init__(self, config: DynamicQuorumConfig | None = None) -> None:
        self.config = config or DynamicQuorumConfig()

    # ------------------------------------------------------------------
    def compute_quorum_size(
        self,
        domain_id: str,
        optimizer_reputation: float,
        active_evaluator_count: int,
        domain_activity_level: float,
    ) -> int:
        """Return the required number of evaluators for a quorum.

        Parameters
        ----------
        domain_id:
            Identifier of the domain (unused in sizing today, but passed
            through for future per-domain overrides / logging).
        optimizer_reputation:
            Normalised reputation score in ``[0, 1]``.
        active_evaluator_count:
            Number of evaluators currently online.
        domain_activity_level:
            Normalised activity metric in ``[0, 1]``.
        """
        cfg = self.config

        if active_evaluator_count <= 0:
            return cfg.min_quorum

        max_quorum = min(cfg.max_quorum_cap, active_evaluator_count // 2)
        # Ensure max never drops below min (liveness over cap).
        max_quorum = max(max_quorum, cfg.min_quorum)

        log_component = int(math.log2(active_evaluator_count))
        activity_bonus = self._activity_bonus(domain_activity_level)
        reputation_discount = self._reputation_discount(optimizer_reputation)

        raw = cfg.base + log_component + activity_bonus - reputation_discount
        return self._clamp(raw, cfg.min_quorum, max_quorum)

    # ------------------------------------------------------------------
    def get_quorum_params(self) -> dict:
        """Return current configuration as a plain dict for status APIs."""
        cfg = self.config
        return {
            "base": cfg.base,
            "min_quorum": cfg.min_quorum,
            "max_quorum_cap": cfg.max_quorum_cap,
            "activity_thresholds": list(cfg.activity_thresholds),
            "reputation_thresholds": list(cfg.reputation_thresholds),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _activity_bonus(self, level: float) -> int:
        for threshold, bonus in self.config.activity_thresholds:
            if level >= threshold:
                return bonus
        return 0

    def _reputation_discount(self, rep: float) -> int:
        for threshold, discount in self.config.reputation_thresholds:
            if rep >= threshold:
                return discount
        return 0

    @staticmethod
    def _clamp(value: int, lo: int, hi: int) -> int:
        return max(lo, min(value, hi))
