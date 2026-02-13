"""Tests for Verified Utility Weighting (VUW)."""

from doin_core.consensus.weights import VerifiedUtilityWeights, WeightConfig


class TestVerifiedUtilityWeights:
    def test_domain_without_synthetic_gets_zero(self):
        """Domains without synthetic data plugin get zero weight."""
        vuw = VerifiedUtilityWeights()
        vuw.register_domain("no-synth", base_weight=1.0, has_synthetic_data=False)
        vuw.register_domain("has-synth", base_weight=1.0, has_synthetic_data=True)

        weights = vuw.compute_weights()
        assert weights["no-synth"] == 0.0
        assert weights["has-synth"] > 0.0

    def test_demand_increases_weight(self):
        vuw = VerifiedUtilityWeights()
        vuw.register_domain("popular", base_weight=1.0, has_synthetic_data=True)
        vuw.register_domain("unpopular", base_weight=1.0, has_synthetic_data=True)

        # Simulate popular domain getting more inference tasks
        for _ in range(10):
            vuw.update_from_block([{
                "tx_type": "task_completed",
                "domain_id": "popular",
                "payload": {"task_type": "inference_request"},
            }])
        vuw.update_from_block([{
            "tx_type": "task_completed",
            "domain_id": "unpopular",
            "payload": {"task_type": "inference_request"},
        }])

        weights = vuw.compute_weights()
        assert weights["popular"] > weights["unpopular"]

    def test_progress_increases_weight(self):
        vuw = VerifiedUtilityWeights()
        vuw.register_domain("improving", base_weight=1.0, has_synthetic_data=True)
        vuw.register_domain("stagnant", base_weight=1.0, has_synthetic_data=True)

        vuw.update_from_block([{
            "tx_type": "optimae_accepted",
            "domain_id": "improving",
            "payload": {"increment": 0.5},
        }])

        weights = vuw.compute_weights()
        assert weights["improving"] > weights["stagnant"]

    def test_effective_increment_zero_for_no_synthetic(self):
        vuw = VerifiedUtilityWeights()
        vuw.register_domain("no-synth", base_weight=1.0, has_synthetic_data=False)

        eff = vuw.get_effective_increment("no-synth", 1.0, 5.0)
        assert eff == 0.0

    def test_effective_increment_scales_with_reputation(self):
        vuw = VerifiedUtilityWeights()
        vuw.register_domain("test", base_weight=1.0, has_synthetic_data=True)

        eff_low = vuw.get_effective_increment("test", 1.0, 0.5)
        eff_high = vuw.get_effective_increment("test", 1.0, 10.0)
        assert eff_high > eff_low

    def test_effective_increment_zero_reputation_zero_increment(self):
        vuw = VerifiedUtilityWeights()
        vuw.register_domain("test", base_weight=1.0, has_synthetic_data=True)

        eff = vuw.get_effective_increment("test", 1.0, 0.0)
        assert eff == 0.0

    def test_reset_stats(self):
        vuw = VerifiedUtilityWeights()
        vuw.register_domain("test", base_weight=1.0, has_synthetic_data=True)
        vuw.update_from_block([{
            "tx_type": "task_completed",
            "domain_id": "test",
            "payload": {"task_type": "inference_request"},
        }])

        stats = vuw.get_stats("test")
        assert stats.inference_tasks_completed == 1

        vuw.reset_stats()
        stats = vuw.get_stats("test")
        assert stats.inference_tasks_completed == 0

    def test_equal_weight_when_no_demand(self):
        """With no demand data, domains get equal demand factor."""
        vuw = VerifiedUtilityWeights()
        vuw.register_domain("a", base_weight=1.0, has_synthetic_data=True)
        vuw.register_domain("b", base_weight=1.0, has_synthetic_data=True)

        weights = vuw.compute_weights()
        assert abs(weights["a"] - weights["b"]) < 0.001

    def test_base_weight_scales(self):
        vuw = VerifiedUtilityWeights()
        vuw.register_domain("heavy", base_weight=2.0, has_synthetic_data=True)
        vuw.register_domain("light", base_weight=1.0, has_synthetic_data=True)

        weights = vuw.compute_weights()
        assert weights["heavy"] > weights["light"]
