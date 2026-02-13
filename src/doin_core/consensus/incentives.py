"""Incentive model for verification rewards.

Handles the reality that verified performance on synthetic data will
naturally differ slightly from reported performance on training data.
A genuinely good model generalizes well (small gap); an overfitted
model fails badly (large gap).

The reward function is configurable per domain:

1. verified >= reported (within sign convention):
   - Full reward (the model is as good or better than claimed)

2. verified slightly below reported (within tolerance margin):
   - Partial reward, linearly scaled from full → minimum
   - This handles natural variance from different synthetic data

3. verified far below reported (outside tolerance):
   - Zero reward — the claimed performance was fraudulent

4. verified significantly ABOVE reported (beyond bonus threshold):
   - Capped reward — prevents gaming by under-reporting

Sign convention is configurable: some fitness functions are
"higher is better" (accuracy), others are "lower is better" (MSE).
The comparison logic adapts to the sign convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class IncentiveConfig:
    """Per-domain incentive configuration.

    All margins are expressed as absolute fractions of the reported value.
    E.g., tolerance_margin=0.10 means 10% below reported is the cutoff.
    """

    # Is higher performance better? (True for accuracy, False for MSE/MAE)
    higher_is_better: bool = True

    # Tolerance margin: how much worse verified can be vs reported
    # and still receive partial reward. Expressed as fraction of |reported|.
    tolerance_margin: float = 0.10  # 10% default

    # Bonus threshold: how much better verified can be vs reported
    # before reward is capped. Prevents under-reporting.
    bonus_threshold: float = 0.05  # 5% above reported → capped

    # Minimum reward fraction within tolerance band
    # At exactly tolerance_margin distance, reward = min_reward_fraction
    min_reward_fraction: float = 0.3

    # Maximum reward multiplier when verified exceeds reported
    # (between reported and bonus_threshold)
    max_bonus_multiplier: float = 1.2


def compute_reward_fraction(
    reported_performance: float,
    verified_performance: float,
    config: IncentiveConfig,
) -> float:
    """Compute the reward fraction [0.0, max_bonus_multiplier] for a verification.

    This determines how much of the base reward the optimizer receives.
    The base reward is the reputation + VUW weighted increment.

    Args:
        reported_performance: What the optimizer claimed.
        verified_performance: What the evaluator measured on synthetic data.
        config: Per-domain incentive configuration.

    Returns:
        Reward fraction:
          0.0                     → rejected (outside tolerance)
          min_reward_fraction..1.0 → partial reward (within tolerance)
          1.0                     → full reward (verified matches reported)
          1.0..max_bonus_multiplier → bonus (verified better than reported)
          max_bonus_multiplier    → capped (verified way better — suspicious)
    """
    # Compute the "gap": how much worse is verified vs reported?
    # Positive gap = verified is worse than reported
    # Negative gap = verified is better than reported
    if config.higher_is_better:
        # Higher is better: gap = reported - verified
        gap = reported_performance - verified_performance
    else:
        # Lower is better: gap = verified - reported
        gap = verified_performance - reported_performance

    # Normalize gap by |reported| (avoid division by zero)
    abs_reported = abs(reported_performance)
    if abs_reported > 1e-10:
        relative_gap = gap / abs_reported
    else:
        # Near-zero reported: use absolute gap
        relative_gap = gap

    # ── Case 1: Verified is better than reported (gap < 0) ──
    if relative_gap < 0:
        # Model performed BETTER on synthetic data than reported
        # This is good (genuine generalization), but cap the bonus
        # to prevent under-reporting gaming
        bonus_fraction = abs(relative_gap)
        if bonus_fraction <= config.bonus_threshold:
            # Linear interpolation: 0% over → 1.0, bonus_threshold over → max_bonus
            t = bonus_fraction / config.bonus_threshold if config.bonus_threshold > 0 else 0
            return 1.0 + t * (config.max_bonus_multiplier - 1.0)
        else:
            # Beyond bonus threshold → capped at max
            return config.max_bonus_multiplier

    # ── Case 2: Verified matches reported exactly (gap ≈ 0) ──
    if relative_gap <= 1e-10:
        return 1.0

    # ── Case 3: Verified is worse, within tolerance (0 < gap ≤ margin) ──
    if relative_gap <= config.tolerance_margin + 1e-9:  # Small epsilon for float precision
        # Linear scale from 1.0 (at gap=0) to min_reward_fraction (at gap=margin)
        t = relative_gap / config.tolerance_margin
        return 1.0 - t * (1.0 - config.min_reward_fraction)

    # ── Case 4: Outside tolerance → rejected ──
    return 0.0


def compute_effective_reward(
    raw_increment: float,
    domain_weight: float,
    reputation_factor: float,
    reward_fraction: float,
) -> float:
    """Compute the final effective increment for consensus.

    effective = raw_increment × domain_weight × reputation_factor × reward_fraction

    This is what actually counts toward the block threshold.
    """
    return raw_increment * domain_weight * reputation_factor * reward_fraction


@dataclass
class VerificationIncentiveResult:
    """Full result of incentive computation for a verification."""

    reward_fraction: float
    relative_gap: float
    reported_performance: float
    verified_performance: float
    within_tolerance: bool
    effective_increment: float = 0.0
    reason: str = ""

    @property
    def is_accepted(self) -> bool:
        return self.reward_fraction > 0.0


def evaluate_verification_incentive(
    reported_performance: float,
    verified_performance: float,
    raw_increment: float,
    domain_weight: float,
    reputation_factor: float,
    config: IncentiveConfig,
) -> VerificationIncentiveResult:
    """Full incentive evaluation for a single verification.

    Combines reward fraction computation with effective increment.
    """
    reward = compute_reward_fraction(
        reported_performance, verified_performance, config,
    )

    # Compute relative gap for diagnostics
    if config.higher_is_better:
        gap = reported_performance - verified_performance
    else:
        gap = verified_performance - reported_performance

    abs_reported = abs(reported_performance)
    relative_gap = gap / abs_reported if abs_reported > 1e-10 else gap

    within_tolerance = relative_gap <= config.tolerance_margin + 1e-9

    effective = compute_effective_reward(
        raw_increment, domain_weight, reputation_factor, reward,
    )

    if reward == 0.0:
        reason = f"rejected: gap {relative_gap:.2%} exceeds tolerance {config.tolerance_margin:.0%}"
    elif reward < 1.0:
        reason = f"partial reward {reward:.2f}: gap {relative_gap:.2%} within tolerance"
    elif reward == 1.0:
        reason = "full reward: verified matches reported"
    else:
        reason = f"bonus {reward:.2f}: verified exceeds reported by {abs(relative_gap):.2%}"

    return VerificationIncentiveResult(
        reward_fraction=reward,
        relative_gap=relative_gap,
        reported_performance=reported_performance,
        verified_performance=verified_performance,
        within_tolerance=within_tolerance,
        effective_increment=effective,
        reason=reason,
    )
