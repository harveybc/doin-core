"""Difficulty adjustment — controls block time via threshold adaptation.

Implements a hybrid Bitcoin/Ethereum approach adapted for Proof of Optimization:

1. **Epoch-based adjustment (Bitcoin-style):** Every EPOCH_LENGTH blocks,
   compare actual epoch time vs target. Adjust threshold proportionally
   with a dampening factor and bounds to prevent extreme swings.

2. **Per-block EMA smoothing (Ethereum-style):** Between epochs, apply
   a small per-block correction using exponential moving average of
   recent block times. This provides faster response to sudden changes
   in network optimization throughput.

3. **Bounds:** Threshold cannot change by more than 4× in either direction
   per epoch (like Bitcoin's 4× cap). This prevents attackers from
   manipulating difficulty by controlling a burst of fast/slow blocks.

Key difference from Bitcoin: our "difficulty" is the optimization
threshold T that the weighted performance sum must exceed. Higher T
means more optimization work needed per block (harder). Lower T means
less work needed (easier).

    T_new = T_old × (target_time / actual_time)

Clamped to [T_old/4, T_old×4] per epoch.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field


# ── Constants ────────────────────────────────────────────────────────

DEFAULT_TARGET_BLOCK_TIME = 600.0   # 10 minutes (like Bitcoin)
EPOCH_LENGTH = 100                  # Blocks per adjustment epoch
                                    # (Bitcoin uses 2016, we use 100 for faster response)
MAX_ADJUSTMENT_FACTOR = 4.0         # Max 4× change per epoch (like Bitcoin)
EMA_ALPHA = 0.1                     # EMA smoothing factor for per-block adjustment
MIN_THRESHOLD = 1e-6                # Floor to prevent threshold from reaching zero
MAX_THRESHOLD = 1e9                 # Ceiling to prevent runaway difficulty
PER_BLOCK_CORRECTION_LIMIT = 0.02   # Max 2% per-block EMA correction


@dataclass
class BlockTimeRecord:
    """Record of a block's timestamp for difficulty calculation."""

    block_index: int
    timestamp: float  # Unix timestamp


@dataclass
class DifficultyState:
    """Persistent state for the difficulty controller."""

    current_threshold: float = 1.0
    target_block_time: float = DEFAULT_TARGET_BLOCK_TIME
    epoch_start_index: int = 0
    epoch_start_time: float = field(default_factory=time.time)
    ema_block_time: float = DEFAULT_TARGET_BLOCK_TIME  # EMA of recent block times
    last_block_time: float = field(default_factory=time.time)
    blocks_in_epoch: int = 0
    total_adjustments: int = 0

    def to_dict(self) -> dict:
        return {
            "current_threshold": self.current_threshold,
            "target_block_time": self.target_block_time,
            "epoch_start_index": self.epoch_start_index,
            "epoch_start_time": self.epoch_start_time,
            "ema_block_time": self.ema_block_time,
            "last_block_time": self.last_block_time,
            "blocks_in_epoch": self.blocks_in_epoch,
            "total_adjustments": self.total_adjustments,
        }

    @staticmethod
    def from_dict(data: dict) -> DifficultyState:
        return DifficultyState(**data)


class DifficultyController:
    """Controls the Proof-of-Optimization threshold to maintain target block time.

    Two-level adjustment:
      1. Epoch adjustment (every EPOCH_LENGTH blocks): major correction
         based on actual vs target epoch duration.
      2. Per-block EMA: minor smoothing between epochs for faster response.

    Usage:
        controller = DifficultyController(target_block_time=600.0)

        # When a new block is generated:
        new_threshold = controller.on_new_block(block_index, block_timestamp)

        # Use new_threshold as the consensus threshold for the next block
    """

    def __init__(
        self,
        target_block_time: float = DEFAULT_TARGET_BLOCK_TIME,
        initial_threshold: float = 1.0,
        epoch_length: int = EPOCH_LENGTH,
    ) -> None:
        self.epoch_length = epoch_length
        self.state = DifficultyState(
            current_threshold=initial_threshold,
            target_block_time=target_block_time,
            ema_block_time=target_block_time,
        )

    @property
    def threshold(self) -> float:
        return self.state.current_threshold

    @property
    def ema_block_time(self) -> float:
        return self.state.ema_block_time

    @property
    def target_block_time(self) -> float:
        return self.state.target_block_time

    def on_new_block(
        self,
        block_index: int,
        block_timestamp: float | None = None,
    ) -> float:
        """Process a new block and return the updated threshold.

        Call this after every new block is appended to the chain.

        Args:
            block_index: Height of the new block.
            block_timestamp: Unix timestamp of the block.
                             Defaults to current time.

        Returns:
            The new threshold to use for the next block.
        """
        now = block_timestamp or time.time()

        # Compute time since last block
        elapsed = max(0.001, now - self.state.last_block_time)

        # Update EMA of block times (Ethereum-style smoothing)
        self.state.ema_block_time = (
            EMA_ALPHA * elapsed
            + (1 - EMA_ALPHA) * self.state.ema_block_time
        )

        # Per-block EMA correction (small adjustment between epochs)
        self._apply_per_block_correction()

        # Track epoch
        self.state.blocks_in_epoch += 1
        self.state.last_block_time = now

        # Epoch boundary — major adjustment
        if self.state.blocks_in_epoch >= self.epoch_length:
            self._epoch_adjustment(now)

        return self.state.current_threshold

    def _apply_per_block_correction(self) -> None:
        """Apply a small per-block correction based on EMA deviation.

        If blocks are coming faster than target, nudge threshold up.
        If blocks are coming slower, nudge threshold down.
        Correction is bounded to prevent instability.
        """
        if self.state.ema_block_time <= 0:
            return

        ratio = self.state.target_block_time / self.state.ema_block_time

        # How far off are we? (1.0 = perfect, >1 = too slow, <1 = too fast)
        # Correction: if ratio > 1 (too slow), decrease threshold
        #             if ratio < 1 (too fast), increase threshold
        correction = ratio - 1.0

        # Clamp correction
        correction = max(-PER_BLOCK_CORRECTION_LIMIT,
                        min(PER_BLOCK_CORRECTION_LIMIT, correction))

        # Apply: if too fast (correction < 0 since ratio < 1), we want HIGHER threshold
        # so multiply by (1 + |correction|). If too slow (correction > 0), LOWER threshold.
        # correction = target/ema - 1
        #   fast blocks: ema < target → ratio > 1 → correction > 0 → INCREASE threshold
        #   slow blocks: ema > target → ratio < 1 → correction < 0 → DECREASE threshold
        self.state.current_threshold *= (1.0 + correction)

        # Enforce bounds
        self.state.current_threshold = max(
            MIN_THRESHOLD,
            min(MAX_THRESHOLD, self.state.current_threshold),
        )

    def _epoch_adjustment(self, now: float) -> None:
        """Major threshold adjustment at epoch boundary.

        Bitcoin-style: compare actual epoch time to target epoch time.
        Adjust threshold proportionally, clamped to [1/4, 4×].

        If actual time > target → blocks too slow → decrease threshold
        If actual time < target → blocks too fast → increase threshold
        """
        actual_epoch_time = now - self.state.epoch_start_time
        target_epoch_time = self.epoch_length * self.state.target_block_time

        if actual_epoch_time <= 0 or target_epoch_time <= 0:
            self._reset_epoch(now)
            return

        # Ratio of target to actual (>1 means too slow, <1 means too fast)
        # We want: T_new = T_old × (actual / target)
        # If actual > target (slow): ratio > 1 → increase threshold? NO!
        # If blocks are slow, we need LESS work → DECREASE threshold
        # So: T_new = T_old × (target / actual)
        ratio = target_epoch_time / actual_epoch_time

        # Clamp to prevent extreme swings (Bitcoin's 4× rule)
        ratio = max(1.0 / MAX_ADJUSTMENT_FACTOR,
                    min(MAX_ADJUSTMENT_FACTOR, ratio))

        self.state.current_threshold *= ratio

        # Enforce absolute bounds
        self.state.current_threshold = max(
            MIN_THRESHOLD,
            min(MAX_THRESHOLD, self.state.current_threshold),
        )

        self.state.total_adjustments += 1

        self._reset_epoch(now)

    def _reset_epoch(self, now: float) -> None:
        """Reset epoch tracking for the next epoch."""
        self.state.epoch_start_time = now
        self.state.blocks_in_epoch = 0

    def get_stats(self) -> dict:
        """Get current difficulty stats for monitoring."""
        return {
            "threshold": self.state.current_threshold,
            "target_block_time": self.state.target_block_time,
            "ema_block_time": self.state.ema_block_time,
            "blocks_in_epoch": self.state.blocks_in_epoch,
            "epoch_length": self.epoch_length,
            "total_adjustments": self.state.total_adjustments,
            "deviation": (
                self.state.ema_block_time / self.state.target_block_time
                if self.state.target_block_time > 0 else 0
            ),
        }
