"""Tests for the Reputation system."""

import time
from unittest.mock import patch

from doin_core.models.reputation import (
    MIN_REPUTATION_FOR_CONSENSUS,
    PENALTY_OPTIMAE_REJECTED,
    REWARD_OPTIMAE_ACCEPTED,
    ReputationTracker,
)


class TestReputationTracker:
    def test_initial_score_is_zero(self):
        tracker = ReputationTracker()
        assert tracker.get_score("node-1") == 0.0

    def test_optimae_accepted_increases_score(self):
        tracker = ReputationTracker()
        tracker.record_optimae_accepted("node-1")
        assert tracker.get_score("node-1") > 0

    def test_optimae_rejected_decreases_score(self):
        tracker = ReputationTracker()
        # Build some reputation first
        for _ in range(5):
            tracker.record_optimae_accepted("node-1")
        score_before = tracker.get_score("node-1")
        tracker.record_optimae_rejected("node-1")
        assert tracker.get_score("node-1") < score_before

    def test_asymmetric_penalties(self):
        """Penalty constant is larger than reward constant."""
        assert PENALTY_OPTIMAE_REJECTED > REWARD_OPTIMAE_ACCEPTED

    def test_score_never_negative(self):
        tracker = ReputationTracker()
        for _ in range(10):
            tracker.record_optimae_rejected("node-1")
        assert tracker.get_score("node-1") >= 0.0

    def test_evaluation_completed_increases_score(self):
        tracker = ReputationTracker()
        tracker.record_evaluation_completed("node-1", agreed_with_quorum=True)
        assert tracker.get_score("node-1") > 0

    def test_evaluation_divergent_decreases_score(self):
        tracker = ReputationTracker()
        for _ in range(5):
            tracker.record_evaluation_completed("node-1", agreed_with_quorum=True)
        before = tracker.get_score("node-1")
        tracker.record_evaluation_completed("node-1", agreed_with_quorum=False)
        assert tracker.get_score("node-1") < before

    def test_meets_threshold(self):
        tracker = ReputationTracker()
        assert not tracker.meets_threshold("node-1")
        # Need enough accepted optimae to pass threshold
        for _ in range(int(MIN_REPUTATION_FOR_CONSENSUS / REWARD_OPTIMAE_ACCEPTED) + 1):
            tracker.record_optimae_accepted("node-1")
        assert tracker.meets_threshold("node-1")

    def test_decay_reduces_score_over_time(self):
        tracker = ReputationTracker(half_life=1.0)  # 1 second half-life for testing
        tracker.record_optimae_accepted("node-1")
        score_t0 = tracker.get_score("node-1")
        assert score_t0 > 0

        # Simulate time passing
        rep = tracker.get("node-1")
        rep.last_activity = time.time() - 2.0  # 2 seconds ago (2 half-lives)
        score_t2 = tracker.get_score("node-1")
        assert score_t2 < score_t0 * 0.5  # Should be ~25% of original

    def test_multiple_peers_independent(self):
        tracker = ReputationTracker()
        tracker.record_optimae_accepted("node-1")
        tracker.record_optimae_accepted("node-1")
        tracker.record_optimae_accepted("node-2")

        assert tracker.get_score("node-1") > tracker.get_score("node-2")

    def test_top_peers(self):
        tracker = ReputationTracker()
        for _ in range(5):
            tracker.record_optimae_accepted("node-1")
        for _ in range(3):
            tracker.record_optimae_accepted("node-2")
        tracker.record_optimae_accepted("node-3")

        top = tracker.top_peers(2)
        assert len(top) == 2
        assert top[0][0] == "node-1"
        assert top[1][0] == "node-2"

    def test_acceptance_rate(self):
        tracker = ReputationTracker()
        tracker.record_optimae_accepted("node-1")
        tracker.record_optimae_accepted("node-1")
        tracker.record_optimae_rejected("node-1")

        rep = tracker.get("node-1")
        assert rep.acceptance_rate == 2 / 3
