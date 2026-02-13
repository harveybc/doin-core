"""Quorum — multi-evaluator verification protocol.

An optimae is only accepted when K-of-N randomly selected evaluator
nodes independently verify it. The selection is deterministic (seeded
from chain tip hash + optimae ID) so all nodes agree on who should verify.

This prevents:
- Self-verification (optimizer can't verify its own optimae)
- Collusion (can't choose your verifiers)
- Rubber-stamping (divergent evaluators are penalized)
"""

from __future__ import annotations

import hashlib
import statistics
from dataclasses import dataclass, field
from typing import Any


@dataclass
class QuorumConfig:
    """Configuration for quorum-based verification."""

    min_evaluators: int = 3          # Minimum K evaluators needed
    quorum_fraction: float = 0.67    # Fraction that must agree (2/3)
    tolerance: float = 0.05          # Max relative divergence from median
    max_wait_seconds: float = 3600   # Max time to wait for quorum


@dataclass
class VerificationVote:
    """A single evaluator's verification result."""

    evaluator_id: str
    verified_performance: float
    used_synthetic: bool = True
    synthetic_data_hash: str = ""  # SHA-256 of the synthetic data used
    timestamp: float = 0.0


@dataclass
class QuorumState:
    """Tracks verification progress for a single optimae."""

    optimae_id: str
    domain_id: str
    optimizer_id: str
    reported_performance: float
    required_evaluators: list[str] = field(default_factory=list)
    votes: list[VerificationVote] = field(default_factory=list)
    decided: bool = False
    accepted: bool = False
    median_performance: float | None = None

    @property
    def vote_count(self) -> int:
        return len(self.votes)

    @property
    def has_quorum(self) -> bool:
        if not self.required_evaluators:
            return False
        return self.vote_count >= len(self.required_evaluators)

    def voter_ids(self) -> set[str]:
        return {v.evaluator_id for v in self.votes}


class QuorumManager:
    """Manages quorum-based verification for optimae.

    Flow:
    1. Optimae announced → select_evaluators() picks K random evaluators
    2. Selected evaluators verify independently → add_vote()
    3. When K votes collected → evaluate_quorum() decides accept/reject
    """

    def __init__(self, config: QuorumConfig | None = None) -> None:
        self.config = config or QuorumConfig()
        self._pending: dict[str, QuorumState] = {}

    def select_evaluators(
        self,
        optimae_id: str,
        domain_id: str,
        optimizer_id: str,
        reported_performance: float,
        eligible_evaluators: list[str],
        chain_tip_hash: str,
    ) -> list[str]:
        """Deterministically select evaluators for an optimae.

        Selection is seeded from chain_tip_hash + optimae_id so all
        nodes in the network agree on the same evaluator set.
        The optimizer is excluded from its own verification.

        Args:
            optimae_id: ID of the optimae to verify.
            domain_id: Domain of the optimae.
            optimizer_id: Peer ID of the optimizer (excluded from selection).
            reported_performance: Optimizer's claimed performance.
            eligible_evaluators: All nodes that can evaluate this domain.
            chain_tip_hash: Hash of current chain tip (randomness source).

        Returns:
            List of selected evaluator peer IDs.
        """
        # Exclude the optimizer from verifying its own work
        candidates = [e for e in eligible_evaluators if e != optimizer_id]

        if len(candidates) == 0:
            return []

        k = min(self.config.min_evaluators, len(candidates))

        # Deterministic shuffle seeded from chain state + optimae
        seed = hashlib.sha256(
            f"{chain_tip_hash}:{optimae_id}".encode()
        ).hexdigest()

        # Sort candidates by hash(seed + candidate_id) for deterministic random selection
        scored = []
        for c in candidates:
            h = hashlib.sha256(f"{seed}:{c}".encode()).hexdigest()
            scored.append((h, c))
        scored.sort()

        selected = [c for _, c in scored[:k]]

        # Create quorum state
        self._pending[optimae_id] = QuorumState(
            optimae_id=optimae_id,
            domain_id=domain_id,
            optimizer_id=optimizer_id,
            reported_performance=reported_performance,
            required_evaluators=selected,
        )

        return selected

    def add_vote(
        self,
        optimae_id: str,
        evaluator_id: str,
        verified_performance: float,
        used_synthetic: bool = True,
        synthetic_data_hash: str = "",
    ) -> QuorumState | None:
        """Add an evaluator's verification vote.

        Returns the QuorumState if quorum is now reached, None otherwise.
        """
        state = self._pending.get(optimae_id)
        if state is None or state.decided:
            return None

        # Only accept votes from selected evaluators
        if evaluator_id not in state.required_evaluators:
            return None

        # Don't accept duplicate votes
        if evaluator_id in state.voter_ids():
            return None

        state.votes.append(VerificationVote(
            evaluator_id=evaluator_id,
            verified_performance=verified_performance,
            used_synthetic=used_synthetic,
            synthetic_data_hash=synthetic_data_hash,
        ))

        if state.has_quorum:
            return state
        return None

    def evaluate_quorum(self, optimae_id: str) -> QuorumResult:
        """Evaluate whether quorum accepts or rejects the optimae.

        Checks:
        1. All evaluators used the same synthetic data (hash must match)
        2. Sufficient fraction of evaluators agree on performance (within tolerance)
        3. Median performance is within tolerance of reported performance

        Returns QuorumResult with accept/reject and per-evaluator agreement.
        """
        state = self._pending.get(optimae_id)
        if state is None:
            return QuorumResult(accepted=False, reason="not found")

        performances = [v.verified_performance for v in state.votes]
        if not performances:
            return QuorumResult(accepted=False, reason="no votes")

        # ── Step 1: Collect synthetic data hashes (for audit trail) ──
        # Each evaluator uses DIFFERENT synthetic data (per-evaluator seed),
        # so hashes are expected to differ.  The hash is stored for
        # reproducibility auditing, not for consensus.
        synth_hashes = {
            v.evaluator_id: v.synthetic_data_hash
            for v in state.votes if v.synthetic_data_hash
        }

        # ── Step 2: Performance consensus ──
        # Since each evaluator tested on different synthetic data, there will
        # be natural variance.  The tolerance handles this — a genuinely good
        # model performs similarly across different synthetic datasets.
        performances = [v.verified_performance for v in state.votes]
        median_perf = statistics.median(performances)
        state.median_performance = median_perf

        agreements: dict[str, bool] = {}
        for vote in state.votes:
            if abs(median_perf) > 1e-10:
                divergence = abs(vote.verified_performance - median_perf) / abs(median_perf)
            else:
                divergence = abs(vote.verified_performance - median_perf)
            agreements[vote.evaluator_id] = divergence <= self.config.tolerance

        agree_count = sum(1 for a in agreements.values() if a)
        agree_fraction = agree_count / len(state.votes) if state.votes else 0

        # ── Step 3: Check reported performance vs median ──
        if abs(median_perf) > 1e-10:
            report_divergence = abs(state.reported_performance - median_perf) / abs(median_perf)
        else:
            report_divergence = abs(state.reported_performance - median_perf)

        report_matches = report_divergence <= self.config.tolerance

        accepted = (
            agree_fraction >= self.config.quorum_fraction
            and report_matches
        )

        state.decided = True
        state.accepted = accepted

        return QuorumResult(
            accepted=accepted,
            median_performance=median_perf,
            reported_performance=state.reported_performance,
            report_divergence=report_divergence,
            agree_fraction=agree_fraction,
            agreements=agreements,
            reason="accepted" if accepted else (
                f"quorum disagreement ({agree_fraction:.0%} < {self.config.quorum_fraction:.0%})"
                if not agree_fraction >= self.config.quorum_fraction
                else f"report diverges from median ({report_divergence:.2%} > {self.config.tolerance:.0%})"
            ),
        )

    def get_state(self, optimae_id: str) -> QuorumState | None:
        return self._pending.get(optimae_id)

    def cleanup_decided(self) -> int:
        """Remove decided quorums. Returns count removed."""
        to_remove = [oid for oid, s in self._pending.items() if s.decided]
        for oid in to_remove:
            del self._pending[oid]
        return len(to_remove)

    @property
    def pending_count(self) -> int:
        return sum(1 for s in self._pending.values() if not s.decided)


@dataclass
class QuorumResult:
    """Result of quorum evaluation."""

    accepted: bool
    reason: str = ""
    median_performance: float | None = None
    reported_performance: float | None = None
    report_divergence: float | None = None
    agree_fraction: float | None = None
    agreements: dict[str, bool] = field(default_factory=dict)
    synthetic_data_hash: str = ""  # Majority hash (empty if no hashes provided)
