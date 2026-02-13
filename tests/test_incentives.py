"""Tests for the verification incentive model."""

import pytest

from doin_core.consensus.incentives import (
    IncentiveConfig,
    VerificationIncentiveResult,
    compute_reward_fraction,
    evaluate_verification_incentive,
)


class TestRewardFractionHigherIsBetter:
    """Test with higher_is_better=True (e.g. accuracy, -fitness)."""

    def setup_method(self):
        self.config = IncentiveConfig(
            higher_is_better=True,
            tolerance_margin=0.10,      # 10%
            bonus_threshold=0.05,       # 5%
            min_reward_fraction=0.3,
            max_bonus_multiplier=1.2,
        )

    def test_exact_match(self):
        """Verified == reported → full reward."""
        r = compute_reward_fraction(-0.50, -0.50, self.config)
        assert r == 1.0

    def test_slightly_worse(self):
        """Verified 5% worse → partial reward (between 0.3 and 1.0)."""
        reported = -0.50
        verified = -0.525  # 5% worse (higher-is-better, so -0.525 < -0.50)
        r = compute_reward_fraction(reported, verified, self.config)
        assert 0.3 < r < 1.0

    def test_at_tolerance_boundary(self):
        """Verified exactly at tolerance margin → min reward fraction."""
        reported = -0.50
        verified = -0.55  # 10% worse
        r = compute_reward_fraction(reported, verified, self.config)
        assert abs(r - 0.3) < 0.01

    def test_outside_tolerance(self):
        """Verified 15% worse → rejected (zero reward)."""
        reported = -0.50
        verified = -0.575  # 15% worse
        r = compute_reward_fraction(reported, verified, self.config)
        assert r == 0.0

    def test_verified_better_than_reported(self):
        """Verified better → bonus reward."""
        reported = -0.50
        verified = -0.48  # 4% better
        r = compute_reward_fraction(reported, verified, self.config)
        assert 1.0 < r <= 1.2

    def test_verified_way_better_capped(self):
        """Verified much better → capped at max bonus."""
        reported = -0.50
        verified = -0.30  # 40% better
        r = compute_reward_fraction(reported, verified, self.config)
        assert r == 1.2

    def test_linear_scaling_within_tolerance(self):
        """Reward scales linearly within tolerance band."""
        reported = -0.50
        # At 0% gap → 1.0
        # At 5% gap → 0.65
        # At 10% gap → 0.3
        r_0 = compute_reward_fraction(reported, -0.50, self.config)
        r_5 = compute_reward_fraction(reported, -0.525, self.config)
        r_10 = compute_reward_fraction(reported, -0.55, self.config)
        assert r_0 > r_5 > r_10
        assert abs(r_0 - 1.0) < 0.01
        assert abs(r_10 - 0.3) < 0.01


class TestRewardFractionLowerIsBetter:
    """Test with higher_is_better=False (e.g. MSE, MAE, raw fitness)."""

    def setup_method(self):
        self.config = IncentiveConfig(
            higher_is_better=False,
            tolerance_margin=0.10,
            bonus_threshold=0.05,
            min_reward_fraction=0.3,
            max_bonus_multiplier=1.2,
        )

    def test_exact_match(self):
        r = compute_reward_fraction(0.50, 0.50, self.config)
        assert r == 1.0

    def test_slightly_worse_lower_is_better(self):
        """Verified 5% worse means HIGHER value when lower-is-better."""
        reported = 0.50
        verified = 0.525  # 5% higher = 5% worse
        r = compute_reward_fraction(reported, verified, self.config)
        assert 0.3 < r < 1.0

    def test_outside_tolerance_lower_is_better(self):
        reported = 0.50
        verified = 0.60  # 20% higher = 20% worse
        r = compute_reward_fraction(reported, verified, self.config)
        assert r == 0.0

    def test_verified_better_lower_is_better(self):
        """Verified lower (better) → bonus."""
        reported = 0.50
        verified = 0.48  # 4% lower = 4% better
        r = compute_reward_fraction(reported, verified, self.config)
        assert 1.0 < r <= 1.2


class TestEvaluateVerificationIncentive:
    def test_full_evaluation(self):
        config = IncentiveConfig(higher_is_better=True, tolerance_margin=0.10)
        result = evaluate_verification_incentive(
            reported_performance=-0.50,
            verified_performance=-0.52,  # 4% worse
            raw_increment=0.05,
            domain_weight=1.0,
            reputation_factor=0.8,
            config=config,
        )
        assert result.is_accepted
        assert result.reward_fraction > 0
        assert result.effective_increment > 0
        assert result.within_tolerance

    def test_rejected_outside_tolerance(self):
        config = IncentiveConfig(higher_is_better=True, tolerance_margin=0.10)
        result = evaluate_verification_incentive(
            reported_performance=-0.50,
            verified_performance=-0.70,  # 40% worse
            raw_increment=0.05,
            domain_weight=1.0,
            reputation_factor=0.8,
            config=config,
        )
        assert not result.is_accepted
        assert result.reward_fraction == 0.0
        assert result.effective_increment == 0.0
        assert not result.within_tolerance

    def test_bonus_reward(self):
        config = IncentiveConfig(
            higher_is_better=True,
            bonus_threshold=0.05,
            max_bonus_multiplier=1.2,
        )
        result = evaluate_verification_incentive(
            reported_performance=-0.50,
            verified_performance=-0.48,  # 4% better
            raw_increment=0.05,
            domain_weight=1.0,
            reputation_factor=0.8,
            config=config,
        )
        assert result.is_accepted
        assert result.reward_fraction > 1.0
        assert "bonus" in result.reason

    def test_zero_reported_performance(self):
        """Edge case: reported performance is zero."""
        config = IncentiveConfig(higher_is_better=True, tolerance_margin=0.10)
        result = evaluate_verification_incentive(
            reported_performance=0.0,
            verified_performance=-0.01,
            raw_increment=0.05,
            domain_weight=1.0,
            reputation_factor=0.8,
            config=config,
        )
        # Should not crash
        assert isinstance(result.reward_fraction, float)


class TestPerEvaluatorSyntheticSeeds:
    """Test that evaluator-specific seeds are unpredictable to optimizer."""

    def test_different_evaluators_get_different_seeds(self):
        from doin_core.consensus.deterministic_seed import DeterministicSeedPolicy

        policy = DeterministicSeedPolicy()
        s1 = policy.get_seed_for_synthetic_data("commit", "domain", "eval-1", "tip")
        s2 = policy.get_seed_for_synthetic_data("commit", "domain", "eval-2", "tip")
        assert s1 != s2

    def test_different_chain_tips_get_different_seeds(self):
        from doin_core.consensus.deterministic_seed import DeterministicSeedPolicy

        policy = DeterministicSeedPolicy()
        s1 = policy.get_seed_for_synthetic_data("commit", "domain", "eval-1", "tip-A")
        s2 = policy.get_seed_for_synthetic_data("commit", "domain", "eval-1", "tip-B")
        assert s1 != s2

    def test_optimizer_seed_differs_from_evaluator_seed(self):
        from doin_core.consensus.deterministic_seed import DeterministicSeedPolicy

        policy = DeterministicSeedPolicy()
        opt_seed = policy.get_seed_for_optimae("commit", "domain")
        eval_seed = policy.get_seed_for_synthetic_data("commit", "domain", "eval-1", "tip")
        assert opt_seed != eval_seed

    def test_same_evaluator_same_seed_reproducible(self):
        from doin_core.consensus.deterministic_seed import DeterministicSeedPolicy

        policy = DeterministicSeedPolicy()
        s1 = policy.get_seed_for_synthetic_data("commit", "domain", "eval-1", "tip")
        s2 = policy.get_seed_for_synthetic_data("commit", "domain", "eval-1", "tip")
        assert s1 == s2
