"""Tests for deterministic seed policy."""

from doin_core.consensus.deterministic_seed import (
    DeterministicSeedPolicy,
    derive_seed,
    verify_seed,
)


class TestDeriveSeed:
    def test_deterministic(self):
        s1 = derive_seed("abc", "domain1")
        s2 = derive_seed("abc", "domain1")
        assert s1 == s2

    def test_different_commitment_different_seed(self):
        s1 = derive_seed("abc", "domain1")
        s2 = derive_seed("def", "domain1")
        assert s1 != s2

    def test_different_domain_different_seed(self):
        s1 = derive_seed("abc", "domain1")
        s2 = derive_seed("abc", "domain2")
        assert s1 != s2

    def test_salt_changes_seed(self):
        s1 = derive_seed("abc", "d", salt="0")
        s2 = derive_seed("abc", "d", salt="1")
        assert s1 != s2

    def test_returns_32bit_int(self):
        s = derive_seed("abc", "d")
        assert 0 <= s < 2**32

    def test_verify_seed_correct(self):
        s = derive_seed("abc", "d")
        assert verify_seed("abc", "d", s)

    def test_verify_seed_wrong(self):
        assert not verify_seed("abc", "d", 12345)


class TestDeterministicSeedPolicy:
    def test_validate_correct_seed(self):
        policy = DeterministicSeedPolicy()
        seed = derive_seed("commit_hash", "domain1")
        ok, reason = policy.validate_submission("commit_hash", "domain1", seed)
        assert ok

    def test_validate_wrong_seed(self):
        policy = DeterministicSeedPolicy()
        ok, reason = policy.validate_submission("commit_hash", "domain1", 99999)
        assert not ok
        assert "does not match" in reason

    def test_validate_missing_seed(self):
        policy = DeterministicSeedPolicy()
        ok, reason = policy.validate_submission("h", "d", None)
        assert not ok

    def test_policy_disabled(self):
        policy = DeterministicSeedPolicy(require_seed=False)
        ok, _ = policy.validate_submission("h", "d", None)
        assert ok

    def test_evaluation_seeds_differ_per_round(self):
        policy = DeterministicSeedPolicy()
        s0 = policy.get_seed_for_evaluation("h", "d", evaluation_round=0)
        s1 = policy.get_seed_for_evaluation("h", "d", evaluation_round=1)
        assert s0 != s1

    def test_synthetic_seed_differs_from_optimizer_seed(self):
        """Synthetic data seed includes evaluator_id and chain_tip,
        so it's unpredictable to the optimizer."""
        policy = DeterministicSeedPolicy()
        opt_seed = policy.get_seed_for_optimae("h", "d")
        synth_seed = policy.get_seed_for_synthetic_data("h", "d", "eval-1", "tip")
        assert opt_seed != synth_seed

    def test_different_evaluators_get_different_synthetic_seeds(self):
        policy = DeterministicSeedPolicy()
        s1 = policy.get_seed_for_synthetic_data("h", "d", "eval-1", "tip")
        s2 = policy.get_seed_for_synthetic_data("h", "d", "eval-2", "tip")
        assert s1 != s2
