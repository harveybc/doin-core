"""Reputation — on-chain track record for nodes.

Reputation is earned through verified compute (accepted optimae,
completed evaluations) and decays over time (EMA). Penalties are
asymmetric: one dishonest act costs more than many honest acts earn.

All reputation data is computable from blockchain history alone —
no external oracle needed.
"""

from __future__ import annotations

import math
import time
from typing import Any

from pydantic import BaseModel, Field


class ReputationScore(BaseModel):
    """A node's reputation across all domains."""

    peer_id: str
    score: float = Field(default=0.0, description="Current composite reputation [0, ∞)")
    optimae_accepted: int = Field(default=0, description="Total optimae accepted by network")
    optimae_rejected: int = Field(default=0, description="Total optimae rejected by network")
    evaluations_completed: int = Field(default=0, description="Total verification tasks completed")
    evaluations_divergent: int = Field(default=0, description="Evaluations that diverged from quorum")
    last_activity: float = Field(default_factory=time.time)

    @property
    def acceptance_rate(self) -> float:
        total = self.optimae_accepted + self.optimae_rejected
        return self.optimae_accepted / total if total > 0 else 0.0

    @property
    def evaluation_accuracy(self) -> float:
        total = self.evaluations_completed
        if total == 0:
            return 0.0
        return (total - self.evaluations_divergent) / total


# ── Reputation constants ────────────────────────────────────────────

# Earning rates
REWARD_OPTIMAE_ACCEPTED = 1.0
REWARD_EVALUATION_COMPLETED = 0.3
REWARD_EVALUATION_AGREED_WITH_QUORUM = 0.1

# Penalty rates (asymmetric — losing is faster than earning)
PENALTY_OPTIMAE_REJECTED = 3.0
PENALTY_EVALUATION_DIVERGENT = 2.0
PENALTY_DOUBLE_SIGN = 10.0  # signing blocks on multiple forks

# Decay
DECAY_HALF_LIFE_SECONDS = 7 * 24 * 3600  # 1 week half-life

# Minimum reputation to have optimae count toward consensus
MIN_REPUTATION_FOR_CONSENSUS = 2.0


class ReputationTracker:
    """Tracks and updates reputation for all nodes.

    Reputation is an EMA that decays toward zero over time.
    Computed from on-chain events — can be rebuilt from blockchain.
    """

    def __init__(self, half_life: float = DECAY_HALF_LIFE_SECONDS) -> None:
        self._scores: dict[str, ReputationScore] = {}
        self._half_life = half_life

    def get(self, peer_id: str) -> ReputationScore:
        """Get or create a reputation score for a peer."""
        if peer_id not in self._scores:
            self._scores[peer_id] = ReputationScore(peer_id=peer_id)
        return self._scores[peer_id]

    def get_score(self, peer_id: str) -> float:
        """Get the current decayed reputation score."""
        rep = self.get(peer_id)
        return self._apply_decay(rep)

    def record_optimae_accepted(self, peer_id: str) -> None:
        rep = self.get(peer_id)
        self._apply_decay(rep)
        rep.score += REWARD_OPTIMAE_ACCEPTED
        rep.optimae_accepted += 1
        rep.last_activity = time.time()

    def record_optimae_rejected(self, peer_id: str) -> None:
        rep = self.get(peer_id)
        self._apply_decay(rep)
        rep.score = max(0.0, rep.score - PENALTY_OPTIMAE_REJECTED)
        rep.optimae_rejected += 1
        rep.last_activity = time.time()

    def record_evaluation_completed(self, peer_id: str, agreed_with_quorum: bool) -> None:
        rep = self.get(peer_id)
        self._apply_decay(rep)
        rep.evaluations_completed += 1

        if agreed_with_quorum:
            rep.score += REWARD_EVALUATION_COMPLETED + REWARD_EVALUATION_AGREED_WITH_QUORUM
        else:
            rep.score = max(0.0, rep.score - PENALTY_EVALUATION_DIVERGENT)
            rep.evaluations_divergent += 1

        rep.last_activity = time.time()

    def record_double_sign(self, peer_id: str) -> None:
        """Slash reputation for signing blocks on multiple forks."""
        rep = self.get(peer_id)
        rep.score = max(0.0, rep.score - PENALTY_DOUBLE_SIGN)
        rep.last_activity = time.time()

    def meets_threshold(self, peer_id: str) -> bool:
        """Check if peer has enough reputation for consensus participation."""
        return self.get_score(peer_id) >= MIN_REPUTATION_FOR_CONSENSUS

    def _apply_decay(self, rep: ReputationScore) -> float:
        """Apply EMA decay based on time since last activity.

        Returns the decayed score.
        """
        now = time.time()
        elapsed = now - rep.last_activity
        if elapsed > 0 and self._half_life > 0:
            decay_factor = math.pow(0.5, elapsed / self._half_life)
            rep.score *= decay_factor
            rep.last_activity = now
        return rep.score

    def rebuild_from_chain(self, transactions: list[dict[str, Any]]) -> None:
        """Rebuild all reputation scores from blockchain transaction history.

        This allows any node to independently compute reputation from
        the chain — no trust required.
        """
        self._scores.clear()
        for tx in transactions:
            tx_type = tx.get("tx_type", "")
            peer_id = tx.get("peer_id", "")
            if not peer_id:
                continue

            if tx_type == "optimae_accepted":
                self.record_optimae_accepted(peer_id)
            elif tx_type == "optimae_rejected":
                self.record_optimae_rejected(peer_id)
            elif tx_type == "task_completed":
                agreed = tx.get("payload", {}).get("agreed_with_quorum", True)
                self.record_evaluation_completed(peer_id, agreed)

    @property
    def all_scores(self) -> dict[str, float]:
        """Current decayed scores for all tracked peers."""
        return {pid: self.get_score(pid) for pid in self._scores}

    def top_peers(self, n: int = 10) -> list[tuple[str, float]]:
        """Top N peers by reputation."""
        scores = [(pid, self.get_score(pid)) for pid in self._scores]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:n]
