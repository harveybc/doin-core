"""Tests for DOIN coin system — block rewards, distribution, balances."""

from __future__ import annotations

import pytest

from doin_core.models.coin import (
    EVALUATOR_POOL_FRACTION,
    GENERATOR_FEE_FRACTION,
    HALVING_INTERVAL,
    INITIAL_BLOCK_REWARD,
    MAX_SUPPLY,
    MIN_REWARD,
    OPTIMIZER_POOL_FRACTION,
    BalanceTracker,
    CoinbaseOutput,
    CoinbaseTransaction,
    ContributorWork,
    TransferTransaction,
    compute_block_reward,
    compute_total_supply_at,
    distribute_block_reward,
)


class TestBlockReward:

    def test_initial_reward(self):
        assert compute_block_reward(0) == INITIAL_BLOCK_REWARD
        assert compute_block_reward(1) == INITIAL_BLOCK_REWARD

    def test_first_halving(self):
        assert compute_block_reward(HALVING_INTERVAL - 1) == INITIAL_BLOCK_REWARD
        assert compute_block_reward(HALVING_INTERVAL) == INITIAL_BLOCK_REWARD / 2

    def test_second_halving(self):
        assert compute_block_reward(HALVING_INTERVAL * 2) == INITIAL_BLOCK_REWARD / 4

    def test_many_halvings_approaches_zero(self):
        reward = compute_block_reward(HALVING_INTERVAL * 30)
        assert reward < 0.001
        assert reward >= 0.0

    def test_64_halvings_is_zero(self):
        assert compute_block_reward(HALVING_INTERVAL * 64) == 0.0

    def test_total_supply_bounded(self):
        """Total supply should never exceed MAX_SUPPLY."""
        # At a very high block, total supply approaches but doesn't exceed max
        total = compute_total_supply_at(HALVING_INTERVAL * 64)
        assert total <= MAX_SUPPLY

    def test_total_supply_first_epoch(self):
        total = compute_total_supply_at(HALVING_INTERVAL - 1)
        expected = HALVING_INTERVAL * INITIAL_BLOCK_REWARD
        assert abs(total - expected) < 0.01

    def test_total_supply_monotonic(self):
        """Supply must be monotonically increasing."""
        prev = 0.0
        for height in [0, 100, 1000, 10000, 100000, HALVING_INTERVAL, HALVING_INTERVAL * 2]:
            total = compute_total_supply_at(height)
            assert total >= prev
            prev = total


class TestRewardDistribution:

    def test_generator_gets_fee(self):
        """Block generator gets GENERATOR_FEE_FRACTION."""
        coinbase = distribute_block_reward(
            block_index=1,
            generator_id="gen-1",
            contributors=[],
        )
        assert coinbase.block_reward == INITIAL_BLOCK_REWARD
        # Generator gets at least the fee fraction
        gen_outputs = [o for o in coinbase.outputs if o.recipient == "gen-1"]
        assert len(gen_outputs) >= 1
        assert gen_outputs[0].amount > 0

    def test_optimizer_gets_proportional_share(self):
        """Optimizers split their pool proportional to work."""
        contributors = [
            ContributorWork(
                peer_id="opt-1", role="optimizer", domain_id="d1",
                effective_increment=3.0, reward_fraction=1.0,
            ),
            ContributorWork(
                peer_id="opt-2", role="optimizer", domain_id="d1",
                effective_increment=1.0, reward_fraction=1.0,
            ),
        ]
        coinbase = distribute_block_reward(1, "gen-1", contributors)

        opt1_reward = sum(o.amount for o in coinbase.outputs if o.recipient == "opt-1")
        opt2_reward = sum(o.amount for o in coinbase.outputs if o.recipient == "opt-2")

        # opt-1 did 3× more work → gets 3× more
        assert opt1_reward > 0
        assert opt2_reward > 0
        assert abs(opt1_reward / opt2_reward - 3.0) < 0.01

    def test_evaluator_gets_share(self):
        contributors = [
            ContributorWork(
                peer_id="eval-1", role="evaluator", domain_id="d1",
                evaluations_completed=2, agreed_with_quorum=True,
            ),
            ContributorWork(
                peer_id="eval-2", role="evaluator", domain_id="d1",
                evaluations_completed=1, agreed_with_quorum=True,
            ),
        ]
        coinbase = distribute_block_reward(1, "gen-1", contributors)

        eval1 = sum(o.amount for o in coinbase.outputs if o.recipient == "eval-1")
        eval2 = sum(o.amount for o in coinbase.outputs if o.recipient == "eval-2")

        assert eval1 > 0
        assert eval2 > 0
        assert eval1 > eval2  # More work → more reward

    def test_dishonest_evaluator_gets_nothing(self):
        contributors = [
            ContributorWork(
                peer_id="eval-honest", role="evaluator",
                evaluations_completed=1, agreed_with_quorum=True,
            ),
            ContributorWork(
                peer_id="eval-dishonest", role="evaluator",
                evaluations_completed=1, agreed_with_quorum=False,
            ),
        ]
        coinbase = distribute_block_reward(1, "gen-1", contributors)

        dishonest = sum(o.amount for o in coinbase.outputs if o.recipient == "eval-dishonest")
        assert dishonest == 0

    def test_reward_fraction_affects_optimizer_share(self):
        """Partial reward (from incentive model) reduces optimizer payout
        relative to other optimizers."""
        # Two optimizers: one full reward, one partial
        coinbase = distribute_block_reward(1, "gen", [
            ContributorWork(
                peer_id="opt-full", role="optimizer",
                effective_increment=1.0, reward_fraction=1.0,
            ),
            ContributorWork(
                peer_id="opt-partial", role="optimizer",
                effective_increment=1.0, reward_fraction=0.3,
            ),
        ])

        full_amt = sum(o.amount for o in coinbase.outputs if o.recipient == "opt-full")
        partial_amt = sum(o.amount for o in coinbase.outputs if o.recipient == "opt-partial")

        # Full reward optimizer gets ~3.3× more (weight 1.0 vs 0.3)
        assert full_amt > 0
        assert partial_amt > 0
        assert abs(full_amt / partial_amt - (1.0 / 0.3)) < 0.1

    def test_total_distributed_equals_reward(self):
        """All minted coins must be distributed (no coins lost)."""
        contributors = [
            ContributorWork("opt-1", "optimizer", "d1", effective_increment=1.0, reward_fraction=1.0),
            ContributorWork("eval-1", "evaluator", "d1", evaluations_completed=2, agreed_with_quorum=True),
        ]
        coinbase = distribute_block_reward(1, "gen-1", contributors)

        total = sum(o.amount for o in coinbase.outputs)
        assert abs(total - coinbase.block_reward) < 0.01

    def test_tx_fees_go_to_generator(self):
        """Transaction fees are added to generator reward."""
        no_fees = distribute_block_reward(1, "gen", [], tx_fees=0.0)
        with_fees = distribute_block_reward(1, "gen", [], tx_fees=10.0)

        gen_no_fees = sum(o.amount for o in no_fees.outputs if o.recipient == "gen")
        gen_with_fees = sum(o.amount for o in with_fees.outputs if o.recipient == "gen")

        assert gen_with_fees > gen_no_fees + 9.0  # Fees went to generator

    def test_empty_block_reward_still_distributes(self):
        coinbase = distribute_block_reward(1, "gen-1", [])
        assert coinbase.block_reward == INITIAL_BLOCK_REWARD
        assert len(coinbase.outputs) >= 1

    def test_halved_block_distributes_less(self):
        early = distribute_block_reward(1, "gen", [])
        late = distribute_block_reward(HALVING_INTERVAL + 1, "gen", [])
        early_total = sum(o.amount for o in early.outputs)
        late_total = sum(o.amount for o in late.outputs)
        assert early_total > late_total


class TestBalanceTracker:

    def test_coinbase_credits_balance(self):
        tracker = BalanceTracker()
        coinbase = CoinbaseTransaction(
            block_index=1,
            block_reward=50.0,
            outputs=[
                CoinbaseOutput(recipient="alice", amount=30.0, reason="optimizer"),
                CoinbaseOutput(recipient="bob", amount=20.0, reason="evaluator"),
            ],
        )
        tracker.apply_coinbase(coinbase)
        assert tracker.get_balance("alice") == 30.0
        assert tracker.get_balance("bob") == 20.0
        assert tracker.total_supply == 50.0

    def test_transfer_moves_coins(self):
        tracker = BalanceTracker()
        tracker.apply_coinbase(CoinbaseTransaction(
            block_index=1, block_reward=50.0,
            outputs=[CoinbaseOutput(recipient="alice", amount=50.0)],
        ))

        tx = TransferTransaction(
            sender="alice", recipient="bob", amount=20.0, nonce=1,
        )
        ok, reason = tracker.apply_transfer(tx)
        assert ok, reason
        assert tracker.get_balance("alice") == 30.0
        assert tracker.get_balance("bob") == 20.0

    def test_transfer_insufficient_balance(self):
        tracker = BalanceTracker()
        tracker.apply_coinbase(CoinbaseTransaction(
            block_index=1, block_reward=10.0,
            outputs=[CoinbaseOutput(recipient="alice", amount=10.0)],
        ))

        tx = TransferTransaction(
            sender="alice", recipient="bob", amount=20.0, nonce=1,
        )
        ok, reason = tracker.apply_transfer(tx)
        assert not ok
        assert "Insufficient" in reason

    def test_transfer_with_fee(self):
        tracker = BalanceTracker()
        tracker.apply_coinbase(CoinbaseTransaction(
            block_index=1, block_reward=50.0,
            outputs=[CoinbaseOutput(recipient="alice", amount=50.0)],
        ))

        tx = TransferTransaction(
            sender="alice", recipient="bob", amount=20.0, fee=1.0, nonce=1,
        )
        ok, _ = tracker.apply_transfer(tx)
        assert ok
        assert tracker.get_balance("alice") == 29.0  # 50 - 20 - 1

    def test_nonce_replay_protection(self):
        tracker = BalanceTracker()
        tracker.apply_coinbase(CoinbaseTransaction(
            block_index=1, block_reward=50.0,
            outputs=[CoinbaseOutput(recipient="alice", amount=50.0)],
        ))

        # First transfer with nonce=1: ok
        ok, _ = tracker.apply_transfer(TransferTransaction(
            sender="alice", recipient="bob", amount=5.0, nonce=1,
        ))
        assert ok

        # Replay same nonce=1: rejected
        ok, reason = tracker.apply_transfer(TransferTransaction(
            sender="alice", recipient="bob", amount=5.0, nonce=1,
        ))
        assert not ok
        assert "nonce" in reason.lower()

        # Next nonce=2: ok
        ok, _ = tracker.apply_transfer(TransferTransaction(
            sender="alice", recipient="bob", amount=5.0, nonce=2,
        ))
        assert ok

    def test_multiple_coinbases_accumulate(self):
        tracker = BalanceTracker()
        for i in range(3):
            tracker.apply_coinbase(CoinbaseTransaction(
                block_index=i, block_reward=50.0,
                outputs=[CoinbaseOutput(recipient="miner", amount=50.0)],
            ))
        assert tracker.get_balance("miner") == 150.0
        assert tracker.total_supply == 150.0

    def test_top_holders(self):
        tracker = BalanceTracker()
        tracker.apply_coinbase(CoinbaseTransaction(
            block_index=1, block_reward=100.0,
            outputs=[
                CoinbaseOutput(recipient="whale", amount=60.0),
                CoinbaseOutput(recipient="fish", amount=30.0),
                CoinbaseOutput(recipient="shrimp", amount=10.0),
            ],
        ))
        top = tracker.top_holders(2)
        assert top[0] == ("whale", 60.0)
        assert top[1] == ("fish", 30.0)
