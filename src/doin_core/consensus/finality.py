"""Finality checkpoints — prevents long-range chain rewriting attacks.

Once a block reaches finality (enough confirmations or explicit checkpoint),
no reorganization is allowed past that point.  This bounds the depth of
any possible reorg and makes the chain immune to long-range history
rewrite (attack #8 from threat model).

Two mechanisms:
  1. Implicit finality: a block is final after `confirmation_depth` successors.
  2. Explicit checkpoints: operators can pin a block hash as irrevocable.

External anchoring (attack #2 defense) is layered on top — see
`ExternalAnchor` for periodic hash publication to an external ledger.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field


@dataclass
class Checkpoint:
    """An irrevocable checkpoint."""

    block_height: int
    block_hash: str
    timestamp: float = field(default_factory=time.time)
    source: str = "implicit"  # "implicit" | "explicit" | "external"


class FinalityManager:
    """Manages finality checkpoints for the chain.

    Blocks at or below the latest checkpoint cannot be reverted.
    """

    def __init__(self, confirmation_depth: int = 6) -> None:
        self._confirmation_depth = confirmation_depth
        self._checkpoints: list[Checkpoint] = []

    @property
    def confirmation_depth(self) -> int:
        return self._confirmation_depth

    @property
    def latest_checkpoint(self) -> Checkpoint | None:
        return self._checkpoints[-1] if self._checkpoints else None

    @property
    def finalized_height(self) -> int:
        """The highest finalized block height."""
        cp = self.latest_checkpoint
        return cp.block_height if cp else -1

    def add_checkpoint(
        self,
        block_height: int,
        block_hash: str,
        source: str = "explicit",
    ) -> Checkpoint:
        """Add an explicit checkpoint.

        Raises ValueError if the checkpoint would revert a previous one.
        """
        if self._checkpoints and block_height <= self._checkpoints[-1].block_height:
            raise ValueError(
                f"Cannot checkpoint height {block_height} — "
                f"already finalized up to {self._checkpoints[-1].block_height}"
            )

        cp = Checkpoint(
            block_height=block_height,
            block_hash=block_hash,
            source=source,
        )
        self._checkpoints.append(cp)
        return cp

    def on_new_block(self, chain_height: int, block_hash_at_depth: str | None) -> Checkpoint | None:
        """Called when a new block is added to the chain.

        If chain_height exceeds finalized + confirmation_depth, a new
        implicit checkpoint is created.

        Args:
            chain_height: Current chain height after new block.
            block_hash_at_depth: Hash of the block at
                (chain_height - confirmation_depth).  None if chain
                is too short.

        Returns:
            New Checkpoint if one was created, else None.
        """
        if block_hash_at_depth is None:
            return None

        candidate_height = chain_height - self._confirmation_depth
        if candidate_height <= self.finalized_height:
            return None

        cp = Checkpoint(
            block_height=candidate_height,
            block_hash=block_hash_at_depth,
            source="implicit",
        )
        self._checkpoints.append(cp)
        return cp

    def is_reorg_allowed(self, reorg_depth: int, chain_height: int) -> bool:
        """Check if a reorganization of `reorg_depth` blocks is allowed.

        A reorg is forbidden if it would undo a finalized block.
        """
        reorg_to = chain_height - reorg_depth
        return reorg_to > self.finalized_height

    def validate_block_ancestry(self, block_height: int, block_hash: str) -> bool:
        """Verify a block is consistent with finalized checkpoints.

        If the block_height matches a checkpoint height, its hash must
        match the checkpoint hash.
        """
        for cp in self._checkpoints:
            if block_height == cp.block_height and block_hash != cp.block_hash:
                return False
        return True

    @property
    def all_checkpoints(self) -> list[Checkpoint]:
        return list(self._checkpoints)


@dataclass
class ExternalAnchor:
    """External checkpoint anchor — publishes chain hashes to external ledger.

    Defense against attack #2 (external validation).  Periodically anchors
    the chain state to an external system (e.g. Bitcoin OP_RETURN, Ethereum
    log, IPFS, or even a public git repo).
    """

    block_height: int
    block_hash: str
    chain_state_hash: str  # Hash of full chain state at this height
    external_tx_id: str = ""  # Transaction ID on external ledger
    external_ledger: str = ""  # e.g. "bitcoin", "ethereum", "ipfs"
    timestamp: float = field(default_factory=time.time)


class ExternalAnchorManager:
    """Manages periodic external anchoring of chain state.

    Nodes can verify their chain matches published anchors from
    any external source — no trust in DON network required.
    """

    def __init__(self, anchor_interval_blocks: int = 100) -> None:
        self._interval = anchor_interval_blocks
        self._anchors: list[ExternalAnchor] = []

    @property
    def anchor_interval(self) -> int:
        return self._interval

    @property
    def latest_anchor(self) -> ExternalAnchor | None:
        return self._anchors[-1] if self._anchors else None

    def should_anchor(self, block_height: int) -> bool:
        """Check if this block height should be anchored externally."""
        return block_height > 0 and block_height % self._interval == 0

    def create_anchor(
        self,
        block_height: int,
        block_hash: str,
        chain_state_hash: str,
    ) -> ExternalAnchor:
        """Create an anchor to be published externally.

        The actual publishing is handled by the transport layer —
        this just creates the data structure.
        """
        anchor = ExternalAnchor(
            block_height=block_height,
            block_hash=block_hash,
            chain_state_hash=chain_state_hash,
        )
        self._anchors.append(anchor)
        return anchor

    def record_publication(
        self,
        block_height: int,
        external_tx_id: str,
        external_ledger: str,
    ) -> bool:
        """Record that an anchor was published to an external ledger."""
        for anchor in self._anchors:
            if anchor.block_height == block_height:
                anchor.external_tx_id = external_tx_id
                anchor.external_ledger = external_ledger
                return True
        return False

    def verify_chain_against_anchor(
        self,
        block_height: int,
        block_hash: str,
        chain_state_hash: str,
    ) -> bool | None:
        """Verify local chain matches an external anchor.

        Returns True if matches, False if diverges, None if no anchor
        exists for this height.
        """
        for anchor in self._anchors:
            if anchor.block_height == block_height:
                return (
                    anchor.block_hash == block_hash
                    and anchor.chain_state_hash == chain_state_hash
                )
        return None

    @property
    def all_anchors(self) -> list[ExternalAnchor]:
        return list(self._anchors)

    def compute_chain_state_hash(self, block_hashes: list[str]) -> str:
        """Compute a hash of the entire chain state up to a point.

        Simple: SHA256 of concatenated block hashes in order.
        """
        combined = ":".join(block_hashes)
        return hashlib.sha256(combined.encode()).hexdigest()
