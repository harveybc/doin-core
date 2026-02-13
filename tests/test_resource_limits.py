"""Tests for BoundsValidator and ResourceLimits."""

from doin_core.models.resource_limits import BoundsValidator, ResourceLimits


class TestBoundsValidator:
    def test_valid_params(self):
        v = BoundsValidator({"lr": (1e-5, 1e-2), "layers": (1, 5)})
        ok, reason = v.validate({"lr": 0.001, "layers": 3})
        assert ok
        assert reason == ""

    def test_out_of_bounds_rejected(self):
        v = BoundsValidator({"lr": (1e-5, 1e-2)})
        ok, reason = v.validate({"lr": 1.0})  # Way too high
        assert not ok
        assert "lr" in reason

    def test_below_lower_bound_rejected(self):
        v = BoundsValidator({"layers": (1, 5)})
        ok, reason = v.validate({"layers": 0})
        assert not ok

    def test_unknown_params_allowed(self):
        v = BoundsValidator({"lr": (1e-5, 1e-2)})
        ok, _ = v.validate({"lr": 0.001, "unknown_param": "whatever"})
        assert ok

    def test_non_numeric_params_skipped(self):
        v = BoundsValidator({"activation": (0, 7)})
        ok, _ = v.validate({"activation": [1, 2, 3]})  # List, not numeric
        assert ok

    def test_resource_limits_epochs(self):
        v = BoundsValidator()
        limits = ResourceLimits(max_epochs=1000)
        ok, reason = v.validate_resource_limits({"epochs": 5000}, limits)
        assert not ok
        assert "epochs" in reason

    def test_resource_limits_batch_size(self):
        v = BoundsValidator()
        limits = ResourceLimits(max_batch_size=256)
        ok, reason = v.validate_resource_limits({"batch_size": 512}, limits)
        assert not ok

    def test_resource_limits_within_bounds(self):
        v = BoundsValidator()
        limits = ResourceLimits()
        ok, _ = v.validate_resource_limits({"epochs": 100, "batch_size": 32}, limits)
        assert ok
