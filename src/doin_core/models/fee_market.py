"""Fee Market — transaction pricing and spam protection.

Implements a fee market similar to EIP-1559 (Ethereum) adapted for DOIN:
  1. Base fee: minimum fee that adjusts based on block fullness
  2. Priority fee (tip): optional extra fee for faster inclusion
  3. Rate limiting: per-peer submission rate caps
  4. Mempool management: priority queue by fee, eviction of low-fee txs

The base fee is burned (removed from circulation), while tips go to
the block generator. This creates deflationary pressure as the network
grows, similar to Ethereum post-EIP-1559.

For optimization submissions (optimae), the "fee" is staked from the
optimizer's balance and refunded if the optimae is accepted. If rejected,
a fraction is burned as a penalty. This prevents spam optimae.
"""

from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field
from typing import Any


# ── Constants ────────────────────────────────────────────────────────

MIN_BASE_FEE = 0.001          # Minimum base fee (never zero)
MAX_BASE_FEE = 100.0          # Cap to prevent runaway
TARGET_BLOCK_FULLNESS = 0.5   # Target 50% full blocks
ELASTICITY = 2.0              # Block can be 2× target size
BASE_FEE_CHANGE_DENOM = 8     # Max 12.5% change per block (like EIP-1559)
MEMPOOL_SIZE_LIMIT = 10_000   # Max pending transactions
OPTIMAE_STAKE_MULTIPLIER = 5  # Optimae stake = 5× base fee
OPTIMAE_BURN_FRACTION = 0.2   # 20% of stake burned on rejection
RATE_LIMIT_WINDOW = 60.0      # Rate limit window in seconds
RATE_LIMIT_MAX_TX = 20        # Max transactions per peer per window
RATE_LIMIT_MAX_OPTIMAE = 5    # Max optimae submissions per peer per window


@dataclass
class FeeConfig:
    """Configurable fee market parameters."""

    min_base_fee: float = MIN_BASE_FEE
    max_base_fee: float = MAX_BASE_FEE
    target_block_fullness: float = TARGET_BLOCK_FULLNESS
    base_fee_change_denom: int = BASE_FEE_CHANGE_DENOM
    target_block_size: int = 100  # Target transactions per block
    max_block_size: int = 200     # Max transactions per block (= target × elasticity)
    optimae_stake_multiplier: float = OPTIMAE_STAKE_MULTIPLIER
    optimae_burn_fraction: float = OPTIMAE_BURN_FRACTION


class FeeMarket:
    """Manages the dynamic fee market and transaction mempool.

    Base fee adjusts every block based on how full the previous block was:
      - Block > 50% full → base fee increases (up to 12.5%)
      - Block < 50% full → base fee decreases (up to 12.5%)
      - Block = 50% full → base fee stays the same

    This creates an equilibrium where blocks tend toward 50% full.
    """

    def __init__(self, config: FeeConfig | None = None) -> None:
        self.config = config or FeeConfig()
        self._base_fee = self.config.min_base_fee
        self._mempool: list[tuple[float, float, str, dict]] = []  # (-priority, timestamp, tx_id, tx_data)
        self._rate_tracker: dict[str, list[float]] = {}  # peer_id → [timestamps]
        self._optimae_tracker: dict[str, list[float]] = {}
        self._staked: dict[str, float] = {}  # optimae_id → staked amount
        self._total_burned: float = 0.0

    @property
    def base_fee(self) -> float:
        return self._base_fee

    @property
    def mempool_size(self) -> int:
        return len(self._mempool)

    @property
    def total_burned(self) -> float:
        return self._total_burned

    # ── Fee calculation ──────────────────────────────────────────

    def get_suggested_fee(self, priority: str = "normal") -> dict[str, float]:
        """Get suggested fees for the current market conditions.

        Returns base_fee + suggested tip for different priority levels.
        """
        base = self._base_fee
        tips = {
            "low": base * 0.1,
            "normal": base * 0.5,
            "high": base * 1.0,
            "urgent": base * 2.0,
        }
        tip = tips.get(priority, tips["normal"])
        return {
            "base_fee": base,
            "tip": tip,
            "total": base + tip,
            "optimae_stake": base * self.config.optimae_stake_multiplier,
        }

    def validate_fee(self, fee: float, is_optimae: bool = False) -> tuple[bool, str]:
        """Check if a transaction fee meets minimum requirements."""
        if is_optimae:
            min_fee = self._base_fee * self.config.optimae_stake_multiplier
            if fee < min_fee:
                return False, f"Optimae stake {fee:.6f} below minimum {min_fee:.6f}"
        else:
            if fee < self._base_fee:
                return False, f"Fee {fee:.6f} below base fee {self._base_fee:.6f}"
        return True, ""

    # ── Base fee adjustment ──────────────────────────────────────

    def adjust_base_fee(self, block_tx_count: int) -> float:
        """Adjust base fee after a block is generated.

        EIP-1559 style: base fee moves toward equilibrium where
        blocks are half full.

        Args:
            block_tx_count: Number of transactions in the block.

        Returns:
            New base fee.
        """
        target = self.config.target_block_size

        if block_tx_count == target:
            # Perfect — no change
            return self._base_fee

        if block_tx_count > target:
            # Block overfull → increase base fee
            delta = block_tx_count - target
            change = self._base_fee * delta / (target * self.config.base_fee_change_denom)
            change = max(change, 1e-8)  # Ensure at least tiny increase
            self._base_fee = min(
                self.config.max_base_fee,
                self._base_fee + change,
            )
        else:
            # Block underfull → decrease base fee
            delta = target - block_tx_count
            change = self._base_fee * delta / (target * self.config.base_fee_change_denom)
            self._base_fee = max(
                self.config.min_base_fee,
                self._base_fee - change,
            )

        return self._base_fee

    # ── Rate limiting ────────────────────────────────────────────

    def check_rate_limit(
        self, peer_id: str, is_optimae: bool = False,
    ) -> tuple[bool, str]:
        """Check if a peer is within their rate limit."""
        now = time.time()
        cutoff = now - RATE_LIMIT_WINDOW

        if is_optimae:
            tracker = self._optimae_tracker
            limit = RATE_LIMIT_MAX_OPTIMAE
            label = "optimae"
        else:
            tracker = self._rate_tracker
            limit = RATE_LIMIT_MAX_TX
            label = "transaction"

        if peer_id not in tracker:
            tracker[peer_id] = []

        # Remove old entries
        tracker[peer_id] = [t for t in tracker[peer_id] if t > cutoff]

        if len(tracker[peer_id]) >= limit:
            return False, (
                f"Rate limit exceeded: {len(tracker[peer_id])} {label}s "
                f"in {RATE_LIMIT_WINDOW}s (limit: {limit})"
            )

        tracker[peer_id].append(now)
        return True, ""

    # ── Mempool management ───────────────────────────────────────

    def add_to_mempool(
        self,
        tx_id: str,
        fee: float,
        tx_data: dict[str, Any],
        peer_id: str = "",
    ) -> tuple[bool, str]:
        """Add a transaction to the mempool.

        Returns (success, reason).
        """
        # Validate fee
        is_optimae = tx_data.get("tx_type") in ("optimae_commit", "optimae_reveal")
        ok, reason = self.validate_fee(fee, is_optimae)
        if not ok:
            return False, reason

        # Check rate limit
        if peer_id:
            ok, reason = self.check_rate_limit(peer_id, is_optimae)
            if not ok:
                return False, reason

        # Check mempool capacity
        if len(self._mempool) >= MEMPOOL_SIZE_LIMIT:
            # Evict lowest-fee transaction
            if self._mempool:
                # Peek at lowest priority (highest negative = lowest fee)
                worst_priority = max(item[0] for item in self._mempool)
                if -fee <= worst_priority:
                    return False, "Mempool full and fee too low"
                # Remove worst
                self._mempool.sort()
                self._mempool.pop()

        # Add with negative fee for min-heap (highest fee = highest priority)
        heapq.heappush(
            self._mempool,
            (-fee, time.time(), tx_id, tx_data),
        )

        return True, ""

    def get_block_transactions(self, max_count: int | None = None) -> list[dict[str, Any]]:
        """Get the highest-fee transactions for a new block.

        Returns up to max_block_size transactions, sorted by fee (highest first).
        """
        limit = max_count or self.config.max_block_size
        result = []
        temp = []

        while self._mempool and len(result) < limit:
            item = heapq.heappop(self._mempool)
            neg_fee, ts, tx_id, tx_data = item
            tx_data["fee"] = -neg_fee
            tx_data["tx_id"] = tx_id
            result.append(tx_data)

        return result

    def return_to_mempool(self, transactions: list[dict[str, Any]]) -> None:
        """Return transactions to the mempool (e.g., after a reorg)."""
        for tx_data in transactions:
            fee = tx_data.get("fee", 0)
            tx_id = tx_data.get("tx_id", "")
            heapq.heappush(
                self._mempool,
                (-fee, time.time(), tx_id, tx_data),
            )

    # ── Optimae staking ──────────────────────────────────────────

    def stake_for_optimae(self, optimae_id: str, stake: float) -> None:
        """Record a stake for an optimae submission."""
        self._staked[optimae_id] = stake

    def resolve_optimae(self, optimae_id: str, accepted: bool) -> float:
        """Resolve an optimae stake.

        Accepted: full refund
        Rejected: burn fraction, refund remainder

        Returns the amount to refund.
        """
        stake = self._staked.pop(optimae_id, 0.0)
        if stake <= 0:
            return 0.0

        if accepted:
            return stake  # Full refund
        else:
            burn = stake * self.config.optimae_burn_fraction
            self._total_burned += burn
            return stake - burn  # Partial refund

    # ── Statistics ───────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        return {
            "base_fee": self._base_fee,
            "mempool_size": len(self._mempool),
            "mempool_limit": MEMPOOL_SIZE_LIMIT,
            "total_burned": self._total_burned,
            "staked_optimae": len(self._staked),
            "total_staked": sum(self._staked.values()),
            "suggested_fees": self.get_suggested_fee(),
        }
