"""Tests for fork choice rule."""

from doin_core.consensus.fork_choice import ChainScore, ForkChoiceRule


class TestChainScore:
    def test_higher_increment_wins(self):
        a = ChainScore(tip_hash="a", height=10, cumulative_increment=5.0)
        b = ChainScore(tip_hash="b", height=10, cumulative_increment=3.0)
        assert b < a  # a is better

    def test_checkpoint_consistent_wins(self):
        a = ChainScore(tip_hash="a", height=10, cumulative_increment=5.0, is_checkpoint_consistent=True)
        b = ChainScore(tip_hash="b", height=10, cumulative_increment=10.0, is_checkpoint_consistent=False)
        assert b < a  # a wins despite lower increment (b is inconsistent)

    def test_more_optimae_breaks_tie(self):
        a = ChainScore(tip_hash="a", height=10, cumulative_increment=5.0, optimae_accepted_count=10)
        b = ChainScore(tip_hash="b", height=10, cumulative_increment=5.0, optimae_accepted_count=5)
        assert b < a

    def test_lower_hash_breaks_final_tie(self):
        a = ChainScore(tip_hash="aaa", height=10, cumulative_increment=5.0, optimae_accepted_count=5)
        b = ChainScore(tip_hash="zzz", height=10, cumulative_increment=5.0, optimae_accepted_count=5)
        # Lower hash wins → "aaa" < "zzz" → a wins, so b < a
        assert b < a


class TestForkChoiceRule:
    def test_select_best_single(self):
        fcr = ForkChoiceRule()
        fcr.score_chain("tip-a", 10, [
            {"height": 1, "hash": "h1", "transactions": [
                {"tx_type": "optimae_accepted", "payload": {"effective_increment": 1.0}}
            ]},
        ])
        best = fcr.select_best()
        assert best is not None
        assert best.tip_hash == "tip-a"

    def test_select_best_multiple_forks(self):
        fcr = ForkChoiceRule()
        fcr.score_chain("weak", 10, [
            {"height": 1, "hash": "h1", "transactions": [
                {"tx_type": "optimae_accepted", "payload": {"effective_increment": 1.0}},
            ]},
        ])
        fcr.score_chain("strong", 10, [
            {"height": 1, "hash": "h1", "transactions": [
                {"tx_type": "optimae_accepted", "payload": {"effective_increment": 5.0}},
                {"tx_type": "optimae_accepted", "payload": {"effective_increment": 3.0}},
            ]},
        ])
        best = fcr.select_best()
        assert best.tip_hash == "strong"

    def test_checkpoint_inconsistent_fork_loses(self):
        fcr = ForkChoiceRule()
        fcr.score_chain("inconsistent", 10, [
            {"height": 5, "hash": "wrong_hash", "transactions": [
                {"tx_type": "optimae_accepted", "payload": {"effective_increment": 100.0}},
            ]},
        ], finalized_height=5, finalized_hash="correct_hash")

        fcr.score_chain("consistent", 10, [
            {"height": 5, "hash": "correct_hash", "transactions": [
                {"tx_type": "optimae_accepted", "payload": {"effective_increment": 1.0}},
            ]},
        ], finalized_height=5, finalized_hash="correct_hash")

        best = fcr.select_best()
        assert best.tip_hash == "consistent"

    def test_empty_returns_none(self):
        fcr = ForkChoiceRule()
        assert fcr.select_best() is None

    def test_clear(self):
        fcr = ForkChoiceRule()
        fcr.score_chain("a", 1, [])
        assert fcr.candidate_count == 1
        fcr.clear()
        assert fcr.candidate_count == 0
