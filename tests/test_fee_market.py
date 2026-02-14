"""Tests for the DOIN fee market and spam protection."""

from __future__ import annotations

import pytest

from doin_core.models.fee_market import (
    FeeConfig,
    FeeMarket,
    MIN_BASE_FEE,
    RATE_LIMIT_MAX_OPTIMAE,
    RATE_LIMIT_MAX_TX,
)


class TestBaseFee:

    def test_initial_base_fee(self):
        fm = FeeMarket()
        assert fm.base_fee == MIN_BASE_FEE

    def test_overfull_block_increases_fee(self):
        fm = FeeMarket(FeeConfig(target_block_size=100))
        initial = fm.base_fee
        fm.adjust_base_fee(150)  # 150% full
        assert fm.base_fee > initial

    def test_underfull_block_decreases_fee(self):
        fm = FeeMarket(FeeConfig(target_block_size=100, min_base_fee=0.0001))
        # First increase the fee
        for _ in range(10):
            fm.adjust_base_fee(200)
        high_fee = fm.base_fee

        # Then underfull blocks
        fm.adjust_base_fee(10)
        assert fm.base_fee < high_fee

    def test_perfect_block_no_change(self):
        fm = FeeMarket(FeeConfig(target_block_size=100))
        fm._base_fee = 1.0
        fm.adjust_base_fee(100)  # Exactly target
        assert fm.base_fee == 1.0

    def test_fee_bounded_by_min(self):
        fm = FeeMarket(FeeConfig(min_base_fee=0.001))
        for _ in range(100):
            fm.adjust_base_fee(0)  # Empty blocks
        assert fm.base_fee >= 0.001

    def test_fee_bounded_by_max(self):
        fm = FeeMarket(FeeConfig(max_base_fee=10.0, target_block_size=10))
        for _ in range(100):
            fm.adjust_base_fee(1000)  # Massively overfull
        assert fm.base_fee <= 10.0

    def test_fee_converges_to_equilibrium(self):
        """Alternating full/empty blocks → fee stabilizes."""
        fm = FeeMarket(FeeConfig(target_block_size=100))
        fm._base_fee = 1.0

        for _ in range(50):
            fm.adjust_base_fee(100)  # Perfect blocks

        assert 0.9 < fm.base_fee < 1.1


class TestFeeValidation:

    def test_valid_fee_accepted(self):
        fm = FeeMarket()
        ok, _ = fm.validate_fee(fm.base_fee)
        assert ok

    def test_low_fee_rejected(self):
        fm = FeeMarket()
        ok, reason = fm.validate_fee(fm.base_fee * 0.5)
        assert not ok
        assert "below base fee" in reason

    def test_optimae_needs_higher_stake(self):
        fm = FeeMarket()
        # Regular fee passes
        ok, _ = fm.validate_fee(fm.base_fee)
        assert ok

        # Same fee fails for optimae (needs 5× base)
        ok, reason = fm.validate_fee(fm.base_fee, is_optimae=True)
        assert not ok
        assert "stake" in reason.lower()

    def test_optimae_valid_stake(self):
        fm = FeeMarket()
        stake = fm.base_fee * 5
        ok, _ = fm.validate_fee(stake, is_optimae=True)
        assert ok


class TestRateLimiting:

    def test_within_limit_passes(self):
        fm = FeeMarket()
        for i in range(RATE_LIMIT_MAX_TX):
            ok, _ = fm.check_rate_limit("peer-1")
            assert ok, f"Failed at tx {i}"

    def test_exceeds_limit_rejected(self):
        fm = FeeMarket()
        for _ in range(RATE_LIMIT_MAX_TX):
            fm.check_rate_limit("peer-1")

        ok, reason = fm.check_rate_limit("peer-1")
        assert not ok
        assert "Rate limit" in reason

    def test_different_peers_independent(self):
        fm = FeeMarket()
        for _ in range(RATE_LIMIT_MAX_TX):
            fm.check_rate_limit("peer-1")

        # peer-2 should still be fine
        ok, _ = fm.check_rate_limit("peer-2")
        assert ok

    def test_optimae_has_lower_limit(self):
        fm = FeeMarket()
        for i in range(RATE_LIMIT_MAX_OPTIMAE):
            ok, _ = fm.check_rate_limit("peer-1", is_optimae=True)
            assert ok

        ok, _ = fm.check_rate_limit("peer-1", is_optimae=True)
        assert not ok


class TestMempool:

    def test_add_and_get(self):
        fm = FeeMarket()
        ok, _ = fm.add_to_mempool("tx-1", 0.1, {"data": "test"})
        assert ok
        assert fm.mempool_size == 1

    def test_low_fee_rejected(self):
        fm = FeeMarket()
        fm._base_fee = 1.0
        ok, reason = fm.add_to_mempool("tx-1", 0.001, {"data": "test"})
        assert not ok
        assert "below base fee" in reason

    def test_highest_fee_first(self):
        fm = FeeMarket()
        fm._base_fee = 0.001
        fm.add_to_mempool("tx-low", 0.01, {"type": "low"})
        fm.add_to_mempool("tx-high", 1.0, {"type": "high"})
        fm.add_to_mempool("tx-mid", 0.1, {"type": "mid"})

        txs = fm.get_block_transactions(max_count=3)
        assert len(txs) == 3
        assert txs[0]["type"] == "high"
        assert txs[1]["type"] == "mid"
        assert txs[2]["type"] == "low"

    def test_rate_limited_in_mempool(self):
        fm = FeeMarket()
        for i in range(RATE_LIMIT_MAX_TX):
            fm.add_to_mempool(f"tx-{i}", 0.1, {}, peer_id="spammer")

        ok, reason = fm.add_to_mempool("tx-extra", 0.1, {}, peer_id="spammer")
        assert not ok
        assert "Rate limit" in reason


class TestOptimaeStaking:

    def test_accepted_optimae_full_refund(self):
        fm = FeeMarket()
        fm.stake_for_optimae("opt-1", 5.0)
        refund = fm.resolve_optimae("opt-1", accepted=True)
        assert refund == 5.0
        assert fm.total_burned == 0.0

    def test_rejected_optimae_partial_burn(self):
        fm = FeeMarket()
        fm.stake_for_optimae("opt-1", 10.0)
        refund = fm.resolve_optimae("opt-1", accepted=False)
        # 20% burned by default
        assert refund == 8.0
        assert fm.total_burned == 2.0

    def test_unknown_optimae_returns_zero(self):
        fm = FeeMarket()
        refund = fm.resolve_optimae("nonexistent", accepted=True)
        assert refund == 0.0

    def test_multiple_stakes_tracked(self):
        fm = FeeMarket()
        fm.stake_for_optimae("opt-1", 5.0)
        fm.stake_for_optimae("opt-2", 10.0)

        fm.resolve_optimae("opt-1", accepted=True)
        fm.resolve_optimae("opt-2", accepted=False)

        assert fm.total_burned == 2.0  # Only opt-2's 20%


class TestSuggestedFees:

    def test_suggested_fees_structure(self):
        fm = FeeMarket()
        fees = fm.get_suggested_fee("normal")
        assert "base_fee" in fees
        assert "tip" in fees
        assert "total" in fees
        assert "optimae_stake" in fees
        assert fees["total"] == fees["base_fee"] + fees["tip"]

    def test_priority_levels(self):
        fm = FeeMarket()
        low = fm.get_suggested_fee("low")
        normal = fm.get_suggested_fee("normal")
        high = fm.get_suggested_fee("high")
        urgent = fm.get_suggested_fee("urgent")

        assert low["total"] < normal["total"] < high["total"] < urgent["total"]


class TestStats:

    def test_stats_structure(self):
        fm = FeeMarket()
        stats = fm.get_stats()
        assert "base_fee" in stats
        assert "mempool_size" in stats
        assert "total_burned" in stats
        assert "suggested_fees" in stats
