"""DOIN Coin — native token for the Decentralized Optimization and Inference Network.

Each block mints new coins (block reward) distributed among participants
proportional to their contribution weights. This creates real economic
incentives for honest optimization and evaluation work.

Distribution follows the game-theoretic VUW weights:
  - Optimizers: rewarded for accepted optimae (proportional to effective increment × reward_fraction)
  - Evaluators: rewarded for honest verification work (agreed with quorum)
  - Block generator: small fee for assembling the block

The block reward halves periodically (like Bitcoin) to create scarcity.
Total supply is bounded.

Coin transfers are standard UTXO-like transactions included in blocks.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


# ── Constants ────────────────────────────────────────────────────────

INITIAL_BLOCK_REWARD = 50.0          # Coins minted per block initially
HALVING_INTERVAL = 210_000           # Blocks between halvings (like Bitcoin)
MAX_SUPPLY = 21_000_000.0            # Maximum total supply
GENERATOR_FEE_FRACTION = 0.05        # 5% of block reward goes to block generator
OPTIMIZER_POOL_FRACTION = 0.65       # 65% goes to optimizers (proportional to work)
EVALUATOR_POOL_FRACTION = 0.30       # 30% goes to evaluators (proportional to work)
MIN_REWARD = 1e-8                    # Minimum distributable amount (like satoshi)


# ── Coin Models ──────────────────────────────────────────────────────

class CoinbaseOutput(BaseModel):
    """A single output from a coinbase (block reward) transaction.

    Each output credits coins to a specific peer for their work
    in this block.
    """

    recipient: str = Field(description="Peer ID of the recipient")
    amount: float = Field(description="Amount of DOIN coins credited")
    reason: str = Field(
        default="",
        description="Why this reward was given (optimizer, evaluator, generator)",
    )
    domain_id: str = Field(default="", description="Domain this reward relates to")


class CoinbaseTransaction(BaseModel):
    """Block reward transaction — mints new coins and distributes them.

    Every block has exactly one coinbase transaction as its first
    transaction. This is the ONLY way new coins are created.

    Like Bitcoin's coinbase, it has no inputs — coins come from nothing.
    Unlike Bitcoin, the reward is split among multiple participants
    based on their game-theoretic contribution weights.
    """

    block_index: int = Field(description="Block this coinbase belongs to")
    block_reward: float = Field(description="Total coins minted in this block")
    outputs: list[CoinbaseOutput] = Field(
        default_factory=list,
        description="Distribution of the block reward",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def total_distributed(self) -> float:
        return sum(o.amount for o in self.outputs)

    @property
    def id(self) -> str:
        payload = json.dumps({
            "block_index": self.block_index,
            "block_reward": self.block_reward,
            "outputs": [
                {"recipient": o.recipient, "amount": o.amount}
                for o in self.outputs
            ],
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()


class TransferTransaction(BaseModel):
    """Peer-to-peer coin transfer.

    Simple account-based transfer (not UTXO for simplicity).
    Included in blocks like any other transaction.
    """

    sender: str = Field(description="Peer ID of sender")
    recipient: str = Field(description="Peer ID of recipient")
    amount: float = Field(description="Amount to transfer")
    fee: float = Field(default=0.0, description="Transaction fee (goes to block generator)")
    nonce: int = Field(default=0, description="Sender's transaction count (replay protection)")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def id(self) -> str:
        payload = json.dumps({
            "sender": self.sender,
            "recipient": self.recipient,
            "amount": self.amount,
            "fee": self.fee,
            "nonce": self.nonce,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()


# ── Reward Calculator ────────────────────────────────────────────────

def compute_block_reward(block_index: int) -> float:
    """Compute the block reward for a given block height.

    Halves every HALVING_INTERVAL blocks. Returns 0 when max supply
    would be exceeded.

    Bitcoin-style halving schedule:
      blocks 0-209999:     50 DOIN
      blocks 210000-419999: 25 DOIN
      blocks 420000-629999: 12.5 DOIN
      ...and so on until reward rounds to zero.
    """
    halvings = block_index // HALVING_INTERVAL
    if halvings >= 64:  # After 64 halvings, reward is effectively 0
        return 0.0

    reward = INITIAL_BLOCK_REWARD / (2 ** halvings)
    if reward < MIN_REWARD:
        return 0.0

    return reward


def compute_total_supply_at(block_index: int) -> float:
    """Compute total coins minted up to a given block height."""
    total = 0.0
    remaining = block_index + 1  # Include block 0

    epoch = 0
    while remaining > 0 and epoch < 64:
        reward = INITIAL_BLOCK_REWARD / (2 ** epoch)
        if reward < MIN_REWARD:
            break
        blocks_in_epoch = min(remaining, HALVING_INTERVAL)
        total += blocks_in_epoch * reward
        remaining -= blocks_in_epoch
        epoch += 1

    return min(total, MAX_SUPPLY)


@dataclass
class ContributorWork:
    """Tracks a peer's contribution within a single block."""

    peer_id: str
    role: str  # "optimizer" | "evaluator" | "generator"
    domain_id: str = ""
    weight: float = 0.0  # Contribution weight (from VUW/incentive model)

    # Optimizer-specific
    effective_increment: float = 0.0
    reward_fraction: float = 0.0

    # Evaluator-specific
    agreed_with_quorum: bool = True
    evaluations_completed: int = 0


def distribute_block_reward(
    block_index: int,
    generator_id: str,
    contributors: list[ContributorWork],
    tx_fees: float = 0.0,
) -> CoinbaseTransaction:
    """Distribute the block reward among contributors.

    Distribution formula:
      1. Generator gets GENERATOR_FEE_FRACTION of block reward + all tx fees
      2. Optimizer pool (OPTIMIZER_POOL_FRACTION) split by effective_increment weights
      3. Evaluator pool (EVALUATOR_POOL_FRACTION) split by evaluation work weights

    If no optimizers contributed, their share goes to evaluators (and vice versa).
    If nobody contributed (empty block), generator gets everything.

    Args:
        block_index: Current block height (determines reward via halving).
        generator_id: Peer ID of the block generator.
        contributors: List of work contributions in this block.
        tx_fees: Total transaction fees in this block.

    Returns:
        CoinbaseTransaction with the reward distribution.
    """
    block_reward = compute_block_reward(block_index)
    total_reward = block_reward + tx_fees

    if total_reward <= 0:
        return CoinbaseTransaction(
            block_index=block_index,
            block_reward=0.0,
            outputs=[],
        )

    outputs: list[CoinbaseOutput] = []

    # 1. Generator fee
    generator_reward = total_reward * GENERATOR_FEE_FRACTION + tx_fees
    if generator_reward >= MIN_REWARD:
        outputs.append(CoinbaseOutput(
            recipient=generator_id,
            amount=generator_reward,
            reason="block_generator",
        ))

    distributable = total_reward - (total_reward * GENERATOR_FEE_FRACTION)

    # Separate optimizers and evaluators
    optimizers = [c for c in contributors if c.role == "optimizer"]
    evaluators = [c for c in contributors if c.role == "evaluator"]

    # 2. Optimizer pool
    optimizer_pool = distributable * OPTIMIZER_POOL_FRACTION
    total_opt_weight = sum(
        c.effective_increment * c.reward_fraction for c in optimizers
    )

    if total_opt_weight > 0 and optimizer_pool >= MIN_REWARD:
        for c in optimizers:
            weight = c.effective_increment * c.reward_fraction
            if weight <= 0:
                continue
            share = optimizer_pool * (weight / total_opt_weight)
            if share >= MIN_REWARD:
                outputs.append(CoinbaseOutput(
                    recipient=c.peer_id,
                    amount=share,
                    reason="optimizer",
                    domain_id=c.domain_id,
                ))
    elif optimizer_pool >= MIN_REWARD:
        # No optimizers — redistribute to evaluators
        evaluator_bonus = optimizer_pool
    else:
        evaluator_bonus = 0.0

    # Check if evaluator_bonus was set
    if 'evaluator_bonus' not in dir():
        evaluator_bonus = 0.0

    # 3. Evaluator pool
    evaluator_pool = distributable * EVALUATOR_POOL_FRACTION + evaluator_bonus
    total_eval_weight = sum(
        c.evaluations_completed * (1.0 if c.agreed_with_quorum else 0.0)
        for c in evaluators
    )

    if total_eval_weight > 0 and evaluator_pool >= MIN_REWARD:
        for c in evaluators:
            if not c.agreed_with_quorum:
                continue  # Dishonest evaluators get nothing
            weight = c.evaluations_completed
            if weight <= 0:
                continue
            share = evaluator_pool * (weight / total_eval_weight)
            if share >= MIN_REWARD:
                outputs.append(CoinbaseOutput(
                    recipient=c.peer_id,
                    amount=share,
                    reason="evaluator",
                    domain_id=c.domain_id,
                ))
    elif evaluator_pool >= MIN_REWARD:
        # No evaluators — give remainder to generator
        outputs[0].amount += evaluator_pool if outputs else 0

    # Handle any undistributed remainder (goes to generator)
    distributed = sum(o.amount for o in outputs)
    remainder = total_reward - distributed
    if remainder >= MIN_REWARD and outputs:
        outputs[0].amount += remainder

    return CoinbaseTransaction(
        block_index=block_index,
        block_reward=block_reward,
        outputs=outputs,
    )


# ── Account Balances (state derived from chain) ─────────────────────

class BalanceTracker:
    """Tracks coin balances for all peers.

    Balances are fully derivable from the chain — any node can rebuild
    them by replaying all coinbase and transfer transactions.
    """

    def __init__(self) -> None:
        self._balances: dict[str, float] = {}
        self._nonces: dict[str, int] = {}  # Last used nonce per peer
        self._total_minted: float = 0.0

    def get_balance(self, peer_id: str) -> float:
        return self._balances.get(peer_id, 0.0)

    def get_nonce(self, peer_id: str) -> int:
        return self._nonces.get(peer_id, 0)

    @property
    def total_supply(self) -> float:
        return self._total_minted

    @property
    def all_balances(self) -> dict[str, float]:
        return dict(self._balances)

    def apply_coinbase(self, coinbase: CoinbaseTransaction) -> None:
        """Apply a coinbase transaction (mint new coins)."""
        for output in coinbase.outputs:
            self._balances[output.recipient] = (
                self._balances.get(output.recipient, 0.0) + output.amount
            )
        self._total_minted += coinbase.block_reward

    def apply_transfer(self, transfer: TransferTransaction) -> tuple[bool, str]:
        """Apply a transfer transaction.

        Returns (success, reason).
        """
        sender_balance = self.get_balance(transfer.sender)
        total_debit = transfer.amount + transfer.fee

        if total_debit <= 0:
            return False, "Amount must be positive"

        if sender_balance < total_debit:
            return False, (
                f"Insufficient balance: {sender_balance:.8f} < "
                f"{total_debit:.8f} (amount + fee)"
            )

        # Check nonce (replay protection)
        expected_nonce = self.get_nonce(transfer.sender) + 1
        if transfer.nonce != expected_nonce:
            return False, (
                f"Invalid nonce: expected {expected_nonce}, got {transfer.nonce}"
            )

        # Apply
        self._balances[transfer.sender] = sender_balance - total_debit
        self._balances[transfer.recipient] = (
            self._balances.get(transfer.recipient, 0.0) + transfer.amount
        )
        self._nonces[transfer.sender] = transfer.nonce

        return True, ""

    def rebuild_from_chain(
        self,
        coinbases: list[CoinbaseTransaction],
        transfers: list[TransferTransaction],
    ) -> None:
        """Rebuild all balances from chain history."""
        self._balances.clear()
        self._nonces.clear()
        self._total_minted = 0.0

        for cb in coinbases:
            self.apply_coinbase(cb)
        for tx in transfers:
            self.apply_transfer(tx)

    def top_holders(self, n: int = 10) -> list[tuple[str, float]]:
        """Top N peers by balance."""
        holders = sorted(
            self._balances.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return holders[:n]
