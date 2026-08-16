"""Proof-of-Optimization — the core consensus mechanism for DON.

TRUTH LABELS (work-plan document 40, doctrine alignment order 2026-08-15):
`implemented_prototype` | `trusted_consortium_current` |
`owner_directed_target` | `conditional_untrusted_research`.

[implemented_prototype] Instead of cryptographic proof of work, block
generation is triggered when the weighted sum of performance increments
across all domains exceeds a dynamic threshold, and the threshold adjusts
to maintain a target block time. Both mechanisms are code facts of the
prototype, not ratified production economics: the weighted raw sum has no
formal cross-domain numeraire (a cross-domain optimality claim would need
one; P14/P18 own that question), and the time-targeted threshold is
recorded drift relative to the owner-directed fixed progress-bin design
(document 40 §5/§7).

[implemented_prototype] `EVALUATION_SERVED` events are recorded on chain
and feed only the task-count statistic `observed_on_chain_task_share`;
the coinbase does not pay the node that served the inference.

[owner_directed_target] Under the inference-service boundary a node could
charge for timely hosted inference when it accepts a client's bid; that
payment path is not implemented here (document 40 §6).

[trusted_consortium_current] This consensus operates today inside a
trusted owner/consortium fleet; it does not provide Byzantine, Sybil,
collusion or permissionless economic security, and no current domain
qualifies for the conditional untrusted generated-gate profile.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from doin_core.models.block import Block, BlockHeader
from doin_core.models.domain import Domain
from doin_core.models.optimae import Optimae
from doin_core.models.transaction import Transaction, TransactionType
from doin_core.crypto.hashing import compute_merkle_root


@dataclass
class ConsensusState:
    """Tracks the current state of the proof-of-optimization consensus."""

    threshold: float = 1.0
    target_block_time_seconds: float = 600.0  # 10 minutes default
    last_block_time: float = field(default_factory=time.time)
    pending_increments: dict[str, float] = field(default_factory=dict)
    pending_transactions: list[Transaction] = field(default_factory=list)
    adjustment_factor: float = 0.25  # How aggressively to adjust threshold
    min_threshold: float = 0.001
    max_threshold: float = 1000.0


class ProofOfOptimization:
    """Implements the proof-of-optimization consensus mechanism.

    The core loop:
    1. Optimizers submit optimae with performance improvements.
    2. Each accepted optimae contributes its weighted performance increment.
    3. When the weighted sum exceeds the threshold, a new block can be generated.
    4. After each block, the threshold adjusts to maintain the target block time.
    """

    def __init__(
        self,
        target_block_time: float = 600.0,
        initial_threshold: float = 1.0,
    ) -> None:
        self.state = ConsensusState(
            threshold=initial_threshold,
            target_block_time_seconds=target_block_time,
        )
        self._domains: dict[str, Domain] = {}

    def register_domain(self, domain: Domain) -> None:
        """Register a domain for tracking performance increments."""
        self._domains[domain.id] = domain

    def record_optimae(self, optimae: Optimae) -> None:
        """Record an accepted optimae and its performance increment.

        Args:
            optimae: The accepted optimae with verified performance.
        """
        domain = self._domains.get(optimae.domain_id)
        if domain is None:
            msg = f"Unknown domain: {optimae.domain_id}"
            raise ValueError(msg)

        weighted_increment = optimae.performance_increment * domain.weight
        current = self.state.pending_increments.get(optimae.domain_id, 0.0)
        self.state.pending_increments[optimae.domain_id] = current + weighted_increment

        # Record transaction
        tx = Transaction(
            tx_type=TransactionType.OPTIMAE_ACCEPTED,
            domain_id=optimae.domain_id,
            peer_id=optimae.optimizer_id,
            payload={
                "optimae_id": optimae.id,
                "performance": optimae.verified_performance or optimae.reported_performance,
                "increment": optimae.performance_increment,
            },
        )
        self.state.pending_transactions.append(tx)

    def record_transaction(self, tx: Transaction) -> None:
        """Record any transaction for inclusion in the next block.

        All network events flow through here — optimae lifecycle,
        task lifecycle, evaluations served, etc.
        """
        self.state.pending_transactions.append(tx)

    def record_evaluation(
        self, domain_id: str, peer_id: str, request_id: str
    ) -> None:
        """Record a served evaluation request.

        [implemented_prototype] This writes an `EVALUATION_SERVED`
        transaction on chain. It feeds the task-count statistic
        `observed_on_chain_task_share` only; it does NOT pay the serving
        node — no coinbase output is created for served inference.

        [owner_directed_target] A paid hosted-inference path (node accepts
        a client's bid) would be a separate, later mechanism (P14); do not
        describe this method as present payment.
        """
        tx = Transaction(
            tx_type=TransactionType.EVALUATION_SERVED,
            domain_id=domain_id,
            peer_id=peer_id,
            payload={"request_id": request_id},
        )
        self.record_transaction(tx)

    @property
    def weighted_sum(self) -> float:
        """Current weighted sum of pending performance increments."""
        return sum(self.state.pending_increments.values())

    def can_generate_block(self) -> bool:
        """Check if the threshold is met for new block generation."""
        return self.weighted_sum >= self.state.threshold

    def generate_block(
        self,
        previous_block: Block,
        generator_id: str,
    ) -> Block | None:
        """Generate a new block if the threshold is met.

        Args:
            previous_block: The current chain tip.
            generator_id: Peer ID of the node generating the block.

        Returns:
            New Block if threshold met, None otherwise.
        """
        if not self.can_generate_block():
            return None

        transactions = list(self.state.pending_transactions)
        tx_hashes = [tx.id for tx in transactions]
        merkle_root = compute_merkle_root(tx_hashes)

        header = BlockHeader(
            index=previous_block.header.index + 1,
            previous_hash=previous_block.hash,
            merkle_root=merkle_root,
            generator_id=generator_id,
            weighted_performance_sum=self.weighted_sum,
            threshold=self.state.threshold,
        )

        block = Block(header=header, transactions=transactions)

        # Adjust threshold and reset state
        self._adjust_threshold()
        self.state.pending_increments.clear()
        self.state.pending_transactions.clear()
        self.state.last_block_time = time.time()

        return block

    def _adjust_threshold(self) -> None:
        """Adjust the threshold to maintain target block time.

        [implemented_prototype] If blocks are coming too fast, increase
        threshold; if too slow, DECREASE it — the quality bar eases to
        meet wall-clock cadence. Code fact; recorded drift relative to
        the owner-directed fixed progress-bin quality contract, which
        would not ease to meet cadence (document 40 §4/§5).
        """
        elapsed = time.time() - self.state.last_block_time
        target = self.state.target_block_time_seconds

        if elapsed <= 0 or target <= 0:
            return

        # Ratio > 1 means blocks are too slow, < 1 means too fast
        ratio = elapsed / target
        adjustment = 1.0 + (ratio - 1.0) * self.state.adjustment_factor

        # Invert: if blocks are slow (ratio > 1), decrease threshold
        new_threshold = self.state.threshold / adjustment

        self.state.threshold = max(
            self.state.min_threshold,
            min(self.state.max_threshold, new_threshold),
        )
