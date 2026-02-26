"""Block — the fundamental unit of the DON blockchain."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from doin_core.models.transaction import Transaction


class BlockHeader(BaseModel):
    """Block header containing consensus-critical fields."""

    index: int = Field(
        description="Block height in the chain",
    )
    previous_hash: str = Field(
        description="Hash of the previous block",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this block was generated",
    )
    merkle_root: str = Field(
        description="Merkle root of the block's transactions",
    )
    generator_id: str = Field(
        description="Peer ID of the node that generated this block",
    )
    weighted_performance_sum: float = Field(
        description="Weighted sum of performance increments that triggered this block",
    )
    threshold: float = Field(
        description="The proof-of-optimization threshold at the time of generation",
    )

    def compute_hash(self) -> str:
        """Compute the block header hash."""
        payload = json.dumps(
            {
                "index": self.index,
                "previous_hash": self.previous_hash,
                "timestamp": self.timestamp.isoformat(),
                "merkle_root": self.merkle_root,
                "generator_id": self.generator_id,
                "weighted_performance_sum": self.weighted_performance_sum,
                "threshold": self.threshold,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


class Block(BaseModel):
    """A block in the DON blockchain.

    A new block is generated when the weighted sum of performance increments
    across all domains exceeds the current threshold. The threshold adjusts
    dynamically to maintain the target block time.
    """

    header: BlockHeader = Field(
        description="Block header with consensus fields",
    )
    transactions: list[Transaction] = Field(
        default_factory=list,
        description="Ordered list of transactions in this block",
    )
    hash: str = Field(
        default="",
        description="Hash of this block's header",
    )

    def model_post_init(self, __context: Any) -> None:
        """Compute block hash if not set."""
        if not self.hash:
            self.hash = self.header.compute_hash()

    @staticmethod
    def genesis(generator_id: str = "genesis") -> Block:
        """Create the genesis block.

        Uses a fixed timestamp (Unix epoch) so every node produces an
        identical genesis block with the same hash.
        """
        header = BlockHeader(
            index=0,
            previous_hash="0" * 64,
            timestamp=datetime(1970, 1, 1, tzinfo=timezone.utc),
            merkle_root="0" * 64,
            generator_id=generator_id,
            weighted_performance_sum=0.0,
            threshold=0.0,
        )
        return Block(header=header, transactions=[])
