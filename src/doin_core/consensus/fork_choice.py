"""Fork choice rule — determines the canonical chain among competing forks.

In DON, the "heaviest" chain wins — not longest, but the chain with
the most accumulated verified optimization work.  This is the
Proof-of-Optimization equivalent of Bitcoin's most-work chain.

Fork choice criteria (in order):
1. Chain must be consistent with finality checkpoints
2. Chain with higher cumulative effective optimization increment
3. On tie: chain with more accepted optimae
4. On tie: chain with lower block hash (deterministic tiebreak)

This prevents attack #3 (selfish mining / fork manipulation) because
an attacker would need to produce more verified optimization work
than the honest network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChainScore:
    """Score for a chain fork, used by fork choice rule."""

    tip_hash: str
    height: int
    cumulative_increment: float = 0.0
    optimae_accepted_count: int = 0
    is_checkpoint_consistent: bool = True

    def __lt__(self, other: ChainScore) -> bool:
        """Less-than for sorting (higher is better)."""
        if self.is_checkpoint_consistent != other.is_checkpoint_consistent:
            return not self.is_checkpoint_consistent  # Consistent > inconsistent

        if abs(self.cumulative_increment - other.cumulative_increment) > 1e-10:
            return self.cumulative_increment < other.cumulative_increment

        if self.optimae_accepted_count != other.optimae_accepted_count:
            return self.optimae_accepted_count < other.optimae_accepted_count

        # Deterministic tiebreak: lower hash wins
        return self.tip_hash > other.tip_hash


class ForkChoiceRule:
    """Selects the canonical chain from competing forks.

    Nodes call `score_chain()` for each fork they know about, then
    `select_best()` to determine which to follow.
    """

    def __init__(self) -> None:
        self._candidates: dict[str, ChainScore] = {}

    def score_chain(
        self,
        tip_hash: str,
        height: int,
        blocks: list[dict[str, Any]],
        finalized_height: int = -1,
        finalized_hash: str | None = None,
    ) -> ChainScore:
        """Score a chain fork from its blocks.

        Args:
            tip_hash: Hash of the chain tip.
            height: Chain height.
            blocks: List of block dicts with 'transactions' lists.
            finalized_height: Height of latest finality checkpoint.
            finalized_hash: Hash at finalized height (for consistency check).

        Returns:
            ChainScore for this fork.
        """
        cumulative = 0.0
        accepted_count = 0
        checkpoint_consistent = True

        for block in blocks:
            block_height = block.get("height", 0)
            block_hash = block.get("hash", "")

            # Check finality consistency
            if (
                finalized_hash is not None
                and block_height == finalized_height
                and block_hash != finalized_hash
            ):
                checkpoint_consistent = False

            for tx in block.get("transactions", []):
                tx_type = tx.get("tx_type", "")
                payload = tx.get("payload", {})

                if tx_type == "optimae_accepted":
                    accepted_count += 1
                    cumulative += abs(payload.get("effective_increment", 0.0))

        score = ChainScore(
            tip_hash=tip_hash,
            height=height,
            cumulative_increment=cumulative,
            optimae_accepted_count=accepted_count,
            is_checkpoint_consistent=checkpoint_consistent,
        )
        self._candidates[tip_hash] = score
        return score

    def select_best(self) -> ChainScore | None:
        """Select the best chain from scored candidates."""
        if not self._candidates:
            return None

        # Sort descending (highest score first); __lt__ defines the order
        ranked = sorted(self._candidates.values(), reverse=True)
        return ranked[0]

    def clear(self) -> None:
        self._candidates.clear()

    @property
    def candidate_count(self) -> int:
        return len(self._candidates)
