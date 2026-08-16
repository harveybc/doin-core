"""WP2 tests — legacy replay preservation.

The typed-profile spike is ADDITIVE: existing chain databases must still
load, hash and verify exactly as before. These tests pin:

* the genesis block hash (byte-identical across the spike);
* the legacy Block/BlockHeader/Transaction field surfaces (no schema drift);
* round-trip JSON serialization with stable hashes and merkle roots;
* BalanceTracker replay of legacy coinbase/transfer history;
* the legacy prototype reward distribution for a normal contributor block
  (pinned as an implemented_prototype code fact, not as ratified economics).
"""

from __future__ import annotations

import pytest

# Importing the new spike modules FIRST, so any interference with legacy
# models would surface in the assertions below.
import doin_core.models.generator_identity  # noqa: F401
import doin_core.models.progress_certificates  # noqa: F401
import doin_core.models.trust_profiles  # noqa: F401
from doin_core.crypto.hashing import compute_merkle_root
from doin_core.models.block import Block, BlockHeader
from doin_core.models.coin import (
    BalanceTracker,
    CoinbaseOutput,
    CoinbaseTransaction,
    ContributorWork,
    TransferTransaction,
    distribute_block_reward,
)
from doin_core.models.transaction import Transaction, TransactionType

# Pinned BEFORE this spike (master @ 9c39df4). If this changes, replay of
# every existing chain database breaks.
GENESIS_HASH = "4e19257e8941caec2ec6a4d581a981a533ab5728c11e58c3d13040049e3cd6d5"

LEGACY_TRANSACTION_FIELDS = {
    "id", "tx_type", "domain_id", "peer_id", "payload", "timestamp",
}
LEGACY_BLOCK_FIELDS = {"header", "transactions", "hash"}
LEGACY_HEADER_FIELDS = {
    "index", "previous_hash", "timestamp", "merkle_root", "generator_id",
    "weighted_performance_sum", "threshold",
}


def make_legacy_block() -> Block:
    genesis = Block.genesis()
    txs = [
        Transaction(
            tx_type=TransactionType.OPTIMAE_ACCEPTED,
            domain_id="dom-1",
            peer_id="opt-1",
            payload={"optimae_id": "o1", "performance": 0.9, "increment": 0.1},
        ),
        Transaction(
            tx_type=TransactionType.EVALUATION_SERVED,
            domain_id="dom-1",
            peer_id="eval-1",
            payload={"request_id": "r1"},
        ),
        Transaction(
            tx_type=TransactionType.TASK_COMPLETED,
            domain_id="dom-1",
            peer_id="eval-1",
            payload={"task_type": "optimae_verification"},
        ),
    ]
    header = BlockHeader(
        index=1,
        previous_hash=genesis.hash,
        merkle_root=compute_merkle_root([tx.id for tx in txs]),
        generator_id="gen-1",
        weighted_performance_sum=1.2,
        threshold=1.0,
    )
    return Block(header=header, transactions=txs)


class TestLegacyReplay:
    def test_genesis_hash_is_unchanged(self):
        assert Block.genesis().hash == GENESIS_HASH

    def test_legacy_schemas_have_no_field_drift(self):
        """The spike adds NEW modules only — legacy models keep their exact
        field surfaces, so persisted JSON round-trips unchanged."""
        assert set(Transaction.model_fields) == LEGACY_TRANSACTION_FIELDS
        assert set(Block.model_fields) == LEGACY_BLOCK_FIELDS
        assert set(BlockHeader.model_fields) == LEGACY_HEADER_FIELDS

    def test_legacy_block_round_trips_with_stable_hashes(self):
        block = make_legacy_block()
        raw = block.model_dump_json()
        reloaded = Block.model_validate_json(raw)

        assert reloaded.hash == block.hash
        assert reloaded.header.compute_hash() == block.hash
        assert reloaded.header.merkle_root == compute_merkle_root(
            [tx.id for tx in reloaded.transactions]
        )
        for original, restored in zip(block.transactions, reloaded.transactions):
            assert restored.id == original.id
            assert restored.compute_id() == original.id

    def test_legacy_chain_linkage_still_verifies(self):
        genesis = Block.genesis()
        block = make_legacy_block()
        assert block.header.previous_hash == genesis.hash
        assert block.header.index == genesis.header.index + 1

    def test_balance_tracker_replays_legacy_history(self):
        coinbase = CoinbaseTransaction(
            block_index=1,
            block_reward=50.0,
            outputs=[
                CoinbaseOutput(
                    recipient="gen-1", amount=4.875, reason="block_generator"
                ),
                CoinbaseOutput(recipient="opt-1", amount=30.875, reason="optimizer"),
                CoinbaseOutput(recipient="eval-1", amount=14.25, reason="evaluator"),
            ],
        )
        transfer = TransferTransaction(
            sender="opt-1", recipient="eval-1", amount=10.0, fee=0.5, nonce=1,
        )
        tracker = BalanceTracker()
        tracker.rebuild_from_chain([coinbase], [transfer])

        assert tracker.get_balance("gen-1") == pytest.approx(4.875)
        assert tracker.get_balance("opt-1") == pytest.approx(30.875 - 10.5)
        assert tracker.get_balance("eval-1") == pytest.approx(14.25 + 10.0)
        assert tracker.total_supply == pytest.approx(50.0)

    def test_prototype_distribution_unchanged_for_normal_block(self):
        """Pinned implemented_prototype behavior (doc 40 §5 code fact):
        block 0, one optimizer + one evaluator, no fees.  NOT ratified
        economics — replay preservation only."""
        coinbase = distribute_block_reward(
            block_index=0,
            generator_id="gen-1",
            contributors=[
                ContributorWork(
                    peer_id="opt-1",
                    role="optimizer",
                    effective_increment=1.0,
                    reward_fraction=1.0,
                ),
                ContributorWork(
                    peer_id="eval-1",
                    role="evaluator",
                    evaluations_completed=1,
                    agreed_with_quorum=True,
                ),
            ],
            tx_fees=0.0,
        )
        by_recipient = {o.recipient: o.amount for o in coinbase.outputs}
        assert by_recipient["gen-1"] == pytest.approx(4.875)
        assert by_recipient["opt-1"] == pytest.approx(30.875)
        assert by_recipient["eval-1"] == pytest.approx(14.25)
        assert coinbase.total_distributed == pytest.approx(50.0)
        assert coinbase.block_reward == 50.0
