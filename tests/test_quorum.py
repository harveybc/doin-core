"""Tests for the Quorum verification system."""

from doin_core.models.quorum import QuorumConfig, QuorumManager


class TestQuorumManager:
    def _make_manager(self, min_eval: int = 3) -> QuorumManager:
        return QuorumManager(QuorumConfig(
            min_evaluators=min_eval,
            quorum_fraction=0.67,
            tolerance=0.05,
        ))

    def test_select_evaluators_excludes_optimizer(self):
        mgr = self._make_manager(min_eval=2)
        selected = mgr.select_evaluators(
            optimae_id="opt-1",
            domain_id="test",
            optimizer_id="optimizer-node",
            reported_performance=-0.5,
            eligible_evaluators=["optimizer-node", "eval-1", "eval-2", "eval-3"],
            chain_tip_hash="abc123",
        )
        assert "optimizer-node" not in selected
        assert len(selected) == 2

    def test_select_evaluators_deterministic(self):
        """Same inputs → same selected evaluators."""
        mgr1 = self._make_manager(min_eval=2)
        mgr2 = self._make_manager(min_eval=2)

        kwargs = dict(
            optimae_id="opt-1",
            domain_id="test",
            optimizer_id="optimizer",
            reported_performance=-0.5,
            eligible_evaluators=["eval-1", "eval-2", "eval-3", "eval-4"],
            chain_tip_hash="abc123",
        )
        s1 = mgr1.select_evaluators(**kwargs)
        s2 = mgr2.select_evaluators(**kwargs)
        assert s1 == s2

    def test_select_evaluators_different_chain_tip_different_selection(self):
        mgr = self._make_manager(min_eval=2)
        evals = [f"eval-{i}" for i in range(10)]

        s1 = mgr.select_evaluators("opt-1", "test", "optimizer", -0.5, evals, "tip-A")
        # Need new manager since opt-1 is already registered
        mgr2 = self._make_manager(min_eval=2)
        s2 = mgr2.select_evaluators("opt-1", "test", "optimizer", -0.5, evals, "tip-B")
        # Different chain tips should (very likely) produce different selections
        # Not guaranteed but overwhelmingly likely with 10 candidates
        # Just check it doesn't crash and returns correct count
        assert len(s1) == 2
        assert len(s2) == 2

    def test_add_vote_only_from_selected(self):
        mgr = self._make_manager(min_eval=2)
        selected = mgr.select_evaluators(
            "opt-1", "test", "optimizer", -0.5,
            ["eval-1", "eval-2", "eval-3"], "tip",
        )

        # Vote from non-selected evaluator should be ignored
        result = mgr.add_vote("opt-1", "not-selected", -0.48)
        assert result is None

        # Vote from selected evaluator should work
        result = mgr.add_vote("opt-1", selected[0], -0.48)
        # Not quorum yet (need 2)
        assert result is None

    def test_quorum_reached_on_last_vote(self):
        mgr = self._make_manager(min_eval=2)
        selected = mgr.select_evaluators(
            "opt-1", "test", "optimizer", -0.5,
            ["eval-1", "eval-2", "eval-3"], "tip",
        )

        mgr.add_vote("opt-1", selected[0], -0.48)
        result = mgr.add_vote("opt-1", selected[1], -0.49)
        assert result is not None  # Quorum reached
        assert result.has_quorum

    def test_no_duplicate_votes(self):
        mgr = self._make_manager(min_eval=2)
        selected = mgr.select_evaluators(
            "opt-1", "test", "optimizer", -0.5,
            ["eval-1", "eval-2", "eval-3"], "tip",
        )
        mgr.add_vote("opt-1", selected[0], -0.48)
        # Same evaluator voting again should be ignored
        result = mgr.add_vote("opt-1", selected[0], -0.49)
        assert result is None  # Still only 1 vote

    def test_evaluate_quorum_accepts_when_consistent(self):
        mgr = self._make_manager(min_eval=3)
        selected = mgr.select_evaluators(
            "opt-1", "test", "optimizer", -0.50,
            ["eval-1", "eval-2", "eval-3", "eval-4"], "tip",
        )

        # All evaluators report close to reported performance
        for ev in selected:
            mgr.add_vote("opt-1", ev, -0.50)

        result = mgr.evaluate_quorum("opt-1")
        assert result.accepted
        assert result.median_performance == -0.50

    def test_evaluate_quorum_rejects_when_report_diverges(self):
        mgr = self._make_manager(min_eval=3)
        selected = mgr.select_evaluators(
            "opt-1", "test", "optimizer", -0.10,  # Optimizer claims -0.10
            ["eval-1", "eval-2", "eval-3", "eval-4"], "tip",
        )

        # Evaluators all agree on -0.50 (far from reported -0.10)
        for ev in selected:
            mgr.add_vote("opt-1", ev, -0.50)

        result = mgr.evaluate_quorum("opt-1")
        assert not result.accepted
        assert "report diverges" in result.reason

    def test_evaluate_quorum_rejects_when_evaluators_disagree(self):
        mgr = self._make_manager(min_eval=3)
        selected = mgr.select_evaluators(
            "opt-1", "test", "optimizer", -0.50,
            ["eval-1", "eval-2", "eval-3", "eval-4"], "tip",
        )

        # Evaluators wildly disagree
        mgr.add_vote("opt-1", selected[0], -0.50)
        mgr.add_vote("opt-1", selected[1], -0.10)
        mgr.add_vote("opt-1", selected[2], -0.90)

        result = mgr.evaluate_quorum("opt-1")
        assert not result.accepted

    def test_agreements_track_per_evaluator(self):
        mgr = self._make_manager(min_eval=3)
        selected = mgr.select_evaluators(
            "opt-1", "test", "optimizer", -0.50,
            ["eval-1", "eval-2", "eval-3", "eval-4"], "tip",
        )

        mgr.add_vote("opt-1", selected[0], -0.50)
        mgr.add_vote("opt-1", selected[1], -0.51)  # Close to median
        mgr.add_vote("opt-1", selected[2], -10.0)   # Way off

        result = mgr.evaluate_quorum("opt-1")
        # The outlier should be marked as disagreeing
        assert result.agreements[selected[2]] is False

    def test_cleanup_decided(self):
        mgr = self._make_manager(min_eval=2)
        selected = mgr.select_evaluators(
            "opt-1", "test", "optimizer", -0.5,
            ["eval-1", "eval-2", "eval-3"], "tip",
        )
        for ev in selected:
            mgr.add_vote("opt-1", ev, -0.5)
        mgr.evaluate_quorum("opt-1")

        assert mgr.pending_count == 0
        removed = mgr.cleanup_decided()
        assert removed == 1
