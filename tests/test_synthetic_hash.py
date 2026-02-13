"""Tests for synthetic data hashing and quorum hash consensus."""

import numpy as np

from doin_core.plugins.base import hash_synthetic_data
from doin_core.models.quorum import QuorumConfig, QuorumManager


class TestSyntheticDataHash:
    def test_deterministic_hash(self):
        """Same data → same hash."""
        data = {
            "x_train": np.array([[1.0, 2.0], [3.0, 4.0]]),
            "y_train": np.array([[5.0], [6.0]]),
        }
        h1 = hash_synthetic_data(data)
        h2 = hash_synthetic_data(data)
        assert h1 == h2

    def test_different_data_different_hash(self):
        data1 = {"x": np.array([1.0, 2.0])}
        data2 = {"x": np.array([1.0, 2.1])}
        assert hash_synthetic_data(data1) != hash_synthetic_data(data2)

    def test_handles_nested_dicts(self):
        data = {"a": {"b": np.array([1.0])}}
        h = hash_synthetic_data(data)
        assert isinstance(h, str) and len(h) == 64

    def test_handles_none(self):
        data = {"baseline_val": None, "x": np.array([1.0])}
        h = hash_synthetic_data(data)
        assert isinstance(h, str)

    def test_handles_strings_and_bools(self):
        data = {"synthetic": True, "method": "bootstrap", "x": np.array([1.0])}
        h = hash_synthetic_data(data)
        assert isinstance(h, str)

    def test_key_order_independent(self):
        """Dict ordering shouldn't matter (keys are sorted)."""
        data1 = {"a": np.array([1.0]), "b": np.array([2.0])}
        data2 = {"b": np.array([2.0]), "a": np.array([1.0])}
        assert hash_synthetic_data(data1) == hash_synthetic_data(data2)

    def test_list_hashes_consistently(self):
        """Lists hash consistently with themselves."""
        data = {"x": [1.0, 2.0, 3.0]}
        assert hash_synthetic_data(data) == hash_synthetic_data(data)


class TestQuorumWithPerEvaluatorSyntheticData:
    """Now that each evaluator uses DIFFERENT synthetic data (per-evaluator seed),
    the quorum checks performance consensus, not hash consensus.
    Different hashes are expected and fine.
    """

    def _make_mgr(self, min_eval: int = 3) -> QuorumManager:
        return QuorumManager(QuorumConfig(
            min_evaluators=min_eval,
            quorum_fraction=0.67,
            tolerance=0.05,
        ))

    def test_different_hashes_accepted_if_perf_agrees(self):
        """Each evaluator has different synthetic data → different hashes.
        As long as performance agrees, quorum passes."""
        mgr = self._make_mgr(3)
        selected = mgr.select_evaluators(
            "opt-1", "test", "optimizer", -0.50,
            ["eval-1", "eval-2", "eval-3", "eval-4"], "tip",
        )

        # Different hashes (per-evaluator seed), similar performance
        mgr.add_vote("opt-1", selected[0], -0.50, synthetic_data_hash="hash_A")
        mgr.add_vote("opt-1", selected[1], -0.51, synthetic_data_hash="hash_B")
        mgr.add_vote("opt-1", selected[2], -0.50, synthetic_data_hash="hash_C")

        result = mgr.evaluate_quorum("opt-1")
        assert result.accepted

    def test_performance_divergence_rejected(self):
        """Even with different synthetic data, if one evaluator gets wildly
        different performance, they're flagged."""
        mgr = self._make_mgr(3)
        selected = mgr.select_evaluators(
            "opt-1", "test", "optimizer", -0.50,
            ["eval-1", "eval-2", "eval-3", "eval-4"], "tip",
        )

        mgr.add_vote("opt-1", selected[0], -0.50, synthetic_data_hash="hash_A")
        mgr.add_vote("opt-1", selected[1], -0.51, synthetic_data_hash="hash_B")
        mgr.add_vote("opt-1", selected[2], -10.0, synthetic_data_hash="hash_C")  # Outlier

        result = mgr.evaluate_quorum("opt-1")
        assert result.agreements[selected[2]] is False

    def test_hashes_stored_for_audit(self):
        """Hashes are recorded in votes for reproducibility auditing."""
        mgr = self._make_mgr(2)
        selected = mgr.select_evaluators(
            "opt-1", "test", "optimizer", -0.50,
            ["eval-1", "eval-2", "eval-3"], "tip",
        )

        mgr.add_vote("opt-1", selected[0], -0.50, synthetic_data_hash="hash_A")
        mgr.add_vote("opt-1", selected[1], -0.50, synthetic_data_hash="hash_B")

        state = mgr.get_state("opt-1")
        assert state.votes[0].synthetic_data_hash == "hash_A"
        assert state.votes[1].synthetic_data_hash == "hash_B"

    def test_no_hash_still_works(self):
        """Backward compat: votes without hashes still work."""
        mgr = self._make_mgr(3)
        selected = mgr.select_evaluators(
            "opt-1", "test", "optimizer", -0.50,
            ["eval-1", "eval-2", "eval-3", "eval-4"], "tip",
        )

        for ev in selected:
            mgr.add_vote("opt-1", ev, -0.50)

        result = mgr.evaluate_quorum("opt-1")
        assert result.accepted
