"""Verified Utility Weighting (VUW) — dynamic domain weight calculation.

TRUTH LABELS (work-plan document 40, doctrine alignment order 2026-08-15):
`implemented_prototype` | `trusted_consortium_current` |
`owner_directed_target` | `conditional_untrusted_research`.

[implemented_prototype] Domain weights determine how much each model's
optimization contributes to block generation. Computed entirely from
blockchain data as coded:

weight(domain) = base_weight × demand_factor × (1 + progress_factor) × verification_strength

Where:
- demand_factor: derived from `observed_on_chain_task_share`, the
  proportion of served inference tasks recorded on chain. That share is a
  censored operational statistic — it is NOT a price and NOT evidence of
  willingness to pay (document 40 §6).
- progress_factor: recent performance improvements relative to history.
- verification_strength: 1.0 with synthetic verification, 0.5 without it.

[implemented_prototype] The unconditional 0.5 fallback for domains without
synthetic data is a code fact. It contradicts the SyntheticDataPlugin ABC
docstring in `doin_core/plugins/base.py`, which states such domains get
ZERO consensus weight — a recorded contradiction (document 40 §5), noted
here and resolved separately.

[trusted_consortium_current] In the operating trusted-consortium profile,
skipping synthetic re-evaluation is a named profile capability of an
operator that accepts reports; identity, ancestry, artifact and lineage
verification still run.

[conditional_untrusted_research] Under the untrusted generated-gate
profile, a domain without an admitted content-addressed generator would
have ZERO authority; the unconditional 0.5 fallback would be unsafe there
and is recorded drift relative to that profile. No current domain passes
document 39's admission program.

[implemented_prototype] The weighted raw sum of domain increments has no
formal cross-domain numeraire. It is a configured scheduling statistic; a
claim of economically optimal cross-domain allocation would require a
normalization or exchange-derived numeraire that survives adversarial
analysis (open question owned by P14/P18).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DomainStats:
    """Statistics for a domain computed from blockchain history."""

    domain_id: str
    base_weight: float = 1.0
    has_synthetic_data: bool = False

    # From blockchain (last N blocks)
    inference_tasks_completed: int = 0
    verification_tasks_completed: int = 0
    optimae_accepted: int = 0
    optimae_rejected: int = 0
    total_performance_increment: float = 0.0
    evaluator_count: int = 0  # Nodes that can evaluate this domain


@dataclass
class WeightConfig:
    """Configuration for the weight calculator."""

    lookback_blocks: int = 100  # How many recent blocks to analyze
    demand_smoothing: float = 0.1  # Minimum demand factor (prevents zero)
    progress_cap: float = 2.0  # Cap progress factor to prevent runaway


class VerifiedUtilityWeights:
    """Computes dynamic domain weights from blockchain data.

    Called after each block to update weights for the next round.
    """

    def __init__(self, config: WeightConfig | None = None) -> None:
        self.config = config or WeightConfig()
        self._stats: dict[str, DomainStats] = {}

    def register_domain(
        self,
        domain_id: str,
        base_weight: float = 1.0,
        has_synthetic_data: bool = False,
    ) -> None:
        self._stats[domain_id] = DomainStats(
            domain_id=domain_id,
            base_weight=base_weight,
            has_synthetic_data=has_synthetic_data,
        )

    def update_from_block(self, transactions: list[dict[str, Any]]) -> None:
        """Update stats from a block's transactions.

        Called for each block in the lookback window.
        """
        for tx in transactions:
            tx_type = tx.get("tx_type", "")
            domain_id = tx.get("domain_id", "")
            payload = tx.get("payload", {})

            stats = self._stats.get(domain_id)
            if stats is None:
                continue

            if tx_type == "task_completed":
                task_type = payload.get("task_type", "")
                if task_type == "inference_request":
                    stats.inference_tasks_completed += 1
                elif task_type == "optimae_verification":
                    stats.verification_tasks_completed += 1

            elif tx_type == "optimae_accepted":
                stats.optimae_accepted += 1
                increment = payload.get("increment", 0.0)
                stats.total_performance_increment += abs(increment)

            elif tx_type == "optimae_rejected":
                stats.optimae_rejected += 1

    def compute_weights(self) -> dict[str, float]:
        """Compute current weights for all domains.

        Returns:
            Dict mapping domain_id → weight.
        """
        if not self._stats:
            return {}

        # Total inference demand across all domains
        total_inference = sum(
            s.inference_tasks_completed for s in self._stats.values()
        )

        weights: dict[str, float] = {}

        for domain_id, stats in self._stats.items():
            # Verification strength — synthetic data gives higher trust
            if stats.has_synthetic_data:
                verification_strength = 1.0
            else:
                # [implemented_prototype] Without synthetic data validation
                # the code still allows block generation at reduced trust; a
                # weight of zero would prevent ANY blocks from ever being
                # created (chicken-and-egg). Code fact: this contradicts the
                # plugins/base.py ABC docstring ("ZERO consensus weight").
                # [conditional_untrusted_research] Under the untrusted
                # generated-gate profile this fallback would grant zero
                # authority, not 0.5 (document 40 §2.2/§5).
                verification_strength = 0.5

            # Demand factor — observed_on_chain_task_share: the on-chain
            # proportion of served inference tasks. [implemented_prototype]
            # A censored operational statistic, not a price and not market
            # demand (document 40 §6).
            if total_inference > 0:
                demand = stats.inference_tasks_completed / total_inference
            else:
                demand = 1.0 / len(self._stats)  # Equal if no demand yet
            demand_factor = max(self.config.demand_smoothing, demand)

            # Progress factor — are we actually improving?
            if stats.optimae_accepted > 0:
                # Average increment per accepted optimae
                avg_increment = stats.total_performance_increment / stats.optimae_accepted
                progress_factor = min(avg_increment, self.config.progress_cap)
            else:
                progress_factor = 0.0

            weight = (
                stats.base_weight
                * demand_factor
                * (1.0 + progress_factor)
                * verification_strength
            )

            weights[domain_id] = weight

        return weights

    def get_effective_increment(
        self,
        domain_id: str,
        raw_increment: float,
        contributor_reputation: float,
    ) -> float:
        """Compute the effective increment for consensus threshold.

        effective = raw_increment × domain_weight × contributor_reputation_factor

        Args:
            domain_id: The domain of the optimae.
            raw_increment: The raw performance improvement.
            contributor_reputation: The optimizer node's reputation score.

        Returns:
            Effective increment that counts toward block generation threshold.
        """
        weights = self.compute_weights()
        domain_weight = weights.get(domain_id, 0.0)

        if domain_weight == 0.0:
            return 0.0

        # Reputation factor: logarithmic scaling to prevent whales
        # rep=0 → factor=0, rep=2 (min threshold) → factor≈0.5, rep=10 → factor≈1.0
        import math
        if contributor_reputation <= 0:
            rep_factor = 0.0
        else:
            rep_factor = min(1.0, math.log1p(contributor_reputation) / math.log1p(10.0))

        return raw_increment * domain_weight * rep_factor

    def reset_stats(self) -> None:
        """Reset rolling stats (called after weight recalculation window)."""
        for stats in self._stats.values():
            stats.inference_tasks_completed = 0
            stats.verification_tasks_completed = 0
            stats.optimae_accepted = 0
            stats.optimae_rejected = 0
            stats.total_performance_increment = 0.0

    def get_stats(self, domain_id: str) -> DomainStats | None:
        return self._stats.get(domain_id)

    @property
    def domain_count(self) -> int:
        return len(self._stats)
