"""Tests for difficulty adjustment controller."""

from __future__ import annotations

import pytest

from doin_core.consensus.difficulty import (
    DEFAULT_TARGET_BLOCK_TIME,
    EPOCH_LENGTH,
    MAX_ADJUSTMENT_FACTOR,
    MAX_THRESHOLD,
    MIN_THRESHOLD,
    DifficultyController,
    DifficultyState,
)


class TestDifficultyBasic:

    def test_initial_state(self):
        dc = DifficultyController(target_block_time=600.0, initial_threshold=1.0)
        assert dc.threshold == 1.0
        assert dc.target_block_time == 600.0
        assert dc.ema_block_time == 600.0

    def test_single_block_on_target(self):
        """A single block at exactly target time → minimal change."""
        dc = DifficultyController(target_block_time=10.0, initial_threshold=1.0)
        t0 = 1000.0
        dc.state.last_block_time = t0
        dc.state.epoch_start_time = t0

        new_t = dc.on_new_block(1, t0 + 10.0)  # Exactly on target
        # Should be close to 1.0 (minor EMA adjustment)
        assert 0.9 < new_t < 1.1

    def test_stats(self):
        dc = DifficultyController()
        stats = dc.get_stats()
        assert "threshold" in stats
        assert "ema_block_time" in stats
        assert "deviation" in stats


class TestPerBlockCorrection:

    def test_fast_blocks_increase_threshold(self):
        """Blocks faster than target → threshold should increase."""
        dc = DifficultyController(target_block_time=100.0, initial_threshold=1.0)
        t = 1000.0
        dc.state.last_block_time = t
        dc.state.epoch_start_time = t

        # Generate blocks much faster than target (every 10s vs 100s target)
        for i in range(1, 20):
            t += 10.0  # 10x faster than target
            dc.on_new_block(i, t)

        # Threshold should have increased (making blocks harder)
        assert dc.threshold > 1.0

    def test_slow_blocks_decrease_threshold(self):
        """Blocks slower than target → threshold should decrease."""
        dc = DifficultyController(target_block_time=10.0, initial_threshold=1.0)
        t = 1000.0
        dc.state.last_block_time = t
        dc.state.epoch_start_time = t

        # Generate blocks much slower than target (every 100s vs 10s target)
        for i in range(1, 20):
            t += 100.0  # 10x slower than target
            dc.on_new_block(i, t)

        assert dc.threshold < 1.0


class TestEpochAdjustment:

    def test_full_epoch_on_target(self):
        """A full epoch at target time → threshold stays similar."""
        dc = DifficultyController(
            target_block_time=10.0,
            initial_threshold=1.0,
            epoch_length=10,
        )
        t = 1000.0
        dc.state.last_block_time = t
        dc.state.epoch_start_time = t
        initial = dc.threshold

        for i in range(1, 11):
            t += 10.0
            dc.on_new_block(i, t)

        # Should be close to initial (perfect timing)
        assert 0.8 < dc.threshold / initial < 1.2

    def test_fast_epoch_increases_threshold(self):
        """Epoch completed 2× faster → threshold roughly doubles."""
        dc = DifficultyController(
            target_block_time=10.0,
            initial_threshold=1.0,
            epoch_length=10,
        )
        t = 1000.0
        dc.state.last_block_time = t
        dc.state.epoch_start_time = t
        initial = dc.threshold

        # 10 blocks in 50s (target was 100s) — 2× faster
        for i in range(1, 11):
            t += 5.0
            dc.on_new_block(i, t)

        # Threshold should have increased significantly
        # (epoch adjustment × per-block corrections)
        assert dc.threshold > initial * 1.3

    def test_slow_epoch_decreases_threshold(self):
        """Epoch completed 2× slower → threshold roughly halves."""
        dc = DifficultyController(
            target_block_time=10.0,
            initial_threshold=1.0,
            epoch_length=10,
        )
        t = 1000.0
        dc.state.last_block_time = t
        dc.state.epoch_start_time = t
        initial = dc.threshold

        # 10 blocks in 200s (target was 100s) — 2× slower
        for i in range(1, 11):
            t += 20.0
            dc.on_new_block(i, t)

        assert dc.threshold < initial * 0.7

    def test_adjustment_capped_at_4x(self):
        """Even extreme deviation capped at 4× per epoch."""
        dc = DifficultyController(
            target_block_time=10.0,
            initial_threshold=1.0,
            epoch_length=10,
        )
        t = 1000.0
        dc.state.last_block_time = t
        dc.state.epoch_start_time = t

        # Absurdly fast: all 10 blocks in 1 second total
        for i in range(1, 11):
            t += 0.1
            dc.on_new_block(i, t)

        # Should not exceed initial × 4 (capped)
        assert dc.threshold <= 1.0 * MAX_ADJUSTMENT_FACTOR * 2  # Some margin for per-block EMA

    def test_multiple_epochs_converge(self):
        """After several epochs, threshold converges to stable value."""
        dc = DifficultyController(
            target_block_time=10.0,
            initial_threshold=1.0,
            epoch_length=5,
        )
        t = 1000.0
        dc.state.last_block_time = t
        dc.state.epoch_start_time = t

        # First: fast blocks (5s instead of 10s)
        for i in range(1, 21):
            t += 5.0
            dc.on_new_block(i, t)

        # Then: blocks at target (10s) for many epochs
        thresholds = []
        for i in range(21, 71):
            t += 10.0
            dc.on_new_block(i, t)
            thresholds.append(dc.threshold)

        # Last 10 thresholds should be relatively stable
        last_10 = thresholds[-10:]
        variation = max(last_10) / min(last_10)
        assert variation < 1.3  # Less than 30% variation


class TestBounds:

    def test_threshold_never_below_minimum(self):
        dc = DifficultyController(
            target_block_time=10.0,
            initial_threshold=MIN_THRESHOLD * 2,
            epoch_length=5,
        )
        t = 1000.0
        dc.state.last_block_time = t
        dc.state.epoch_start_time = t

        # Very slow blocks to push threshold down
        for i in range(1, 50):
            t += 10000.0
            dc.on_new_block(i, t)
            assert dc.threshold >= MIN_THRESHOLD

    def test_threshold_never_above_maximum(self):
        dc = DifficultyController(
            target_block_time=10.0,
            initial_threshold=MAX_THRESHOLD / 2,
            epoch_length=5,
        )
        t = 1000.0
        dc.state.last_block_time = t
        dc.state.epoch_start_time = t

        # Very fast blocks to push threshold up
        for i in range(1, 50):
            t += 0.001
            dc.on_new_block(i, t)
            assert dc.threshold <= MAX_THRESHOLD


class TestStateSerialize:

    def test_round_trip(self):
        dc = DifficultyController(target_block_time=60.0, initial_threshold=2.5)
        dc.state.blocks_in_epoch = 42
        dc.state.total_adjustments = 7

        data = dc.state.to_dict()
        restored = DifficultyState.from_dict(data)

        assert restored.current_threshold == 2.5
        assert restored.target_block_time == 60.0
        assert restored.blocks_in_epoch == 42
        assert restored.total_adjustments == 7
