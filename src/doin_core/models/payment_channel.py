"""L2 Payment Channels — off-chain micropayments for inference requests.

On-chain settlement is expensive for frequent small payments (e.g., per-inference
fees). Payment channels allow two parties to transact off-chain with only two
on-chain transactions: open and close.

Flow:
  1. Client opens a channel with a node by locking DOIN on-chain (deposit)
  2. Client sends signed payment updates off-chain for each inference
  3. Either party can close the channel on-chain with the latest state
  4. Dispute period allows the other party to submit a newer state

This is similar to Bitcoin's Lightning Network or Ethereum's state channels,
adapted for DOIN's inference payment use case.

Channel states:
  OPENING → OPEN → CLOSING → CLOSED
                 → DISPUTED → CLOSED
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChannelState(str, Enum):
    OPENING = "opening"
    OPEN = "open"
    CLOSING = "closing"
    DISPUTED = "disputed"
    CLOSED = "closed"


@dataclass
class PaymentUpdate:
    """A signed off-chain payment update.

    Each update increments the nonce and adjusts balances.
    Only the latest (highest nonce) update matters for settlement.
    """

    channel_id: str
    nonce: int
    sender_balance: float
    receiver_balance: float
    timestamp: float = field(default_factory=time.time)
    sender_signature: str = ""
    receiver_signature: str = ""

    @property
    def state_hash(self) -> str:
        """Hash of the payment state (for signing)."""
        data = json.dumps({
            "channel_id": self.channel_id,
            "nonce": self.nonce,
            "sender_balance": self.sender_balance,
            "receiver_balance": self.receiver_balance,
        }, sort_keys=True)
        return hashlib.sha256(data.encode()).hexdigest()

    @property
    def total(self) -> float:
        return self.sender_balance + self.receiver_balance


@dataclass
class PaymentChannel:
    """A bidirectional payment channel between two parties."""

    channel_id: str
    sender_id: str      # Client (pays for inference)
    receiver_id: str     # Node (provides inference)
    deposit: float       # Total locked DOIN
    state: ChannelState = ChannelState.OPENING
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0  # 0 = no expiry
    dispute_period: float = 3600.0  # 1 hour default

    # Current balances (updated off-chain)
    sender_balance: float = 0.0
    receiver_balance: float = 0.0
    nonce: int = 0

    # Latest signed state
    latest_update: PaymentUpdate | None = None

    # Dispute tracking
    dispute_deadline: float = 0.0
    disputed_by: str = ""

    def __post_init__(self) -> None:
        if self.sender_balance == 0 and self.receiver_balance == 0:
            self.sender_balance = self.deposit
            self.receiver_balance = 0.0

    @property
    def is_active(self) -> bool:
        return self.state == ChannelState.OPEN

    @property
    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at

    @property
    def remaining_sender(self) -> float:
        return self.sender_balance

    @property
    def total_paid(self) -> float:
        return self.deposit - self.sender_balance


@dataclass
class ChannelConfig:
    """Configuration for the payment channel manager."""

    min_deposit: float = 1.0
    max_deposit: float = 10000.0
    default_expiry: float = 86400.0  # 24 hours
    dispute_period: float = 3600.0   # 1 hour
    max_channels_per_peer: int = 10
    settlement_fee_fraction: float = 0.001  # 0.1% fee on settlement


class PaymentChannelManager:
    """Manages payment channels for off-chain inference micropayments.

    Handles channel lifecycle: open, pay, close, dispute.
    On-chain settlement only happens at open and close.
    """

    def __init__(self, config: ChannelConfig | None = None) -> None:
        self.config = config or ChannelConfig()
        self._channels: dict[str, PaymentChannel] = {}
        self._peer_channels: dict[str, list[str]] = {}  # peer_id → [channel_ids]
        self._total_locked: float = 0.0
        self._total_settled: float = 0.0
        self._total_fees: float = 0.0

    @property
    def active_channels(self) -> int:
        return sum(1 for c in self._channels.values() if c.is_active)

    @property
    def total_locked(self) -> float:
        return self._total_locked

    # ── Channel lifecycle ────────────────────────────────────────

    def open_channel(
        self,
        channel_id: str,
        sender_id: str,
        receiver_id: str,
        deposit: float,
        expiry: float | None = None,
    ) -> tuple[PaymentChannel | None, str]:
        """Open a new payment channel.

        Returns (channel, error_message). Channel is None on failure.
        """
        # Validate
        if deposit < self.config.min_deposit:
            return None, f"Deposit {deposit} below minimum {self.config.min_deposit}"
        if deposit > self.config.max_deposit:
            return None, f"Deposit {deposit} above maximum {self.config.max_deposit}"
        if channel_id in self._channels:
            return None, f"Channel {channel_id} already exists"
        if sender_id == receiver_id:
            return None, "Cannot open channel with yourself"

        # Check per-peer limit
        sender_channels = self._peer_channels.get(sender_id, [])
        if len(sender_channels) >= self.config.max_channels_per_peer:
            return None, f"Peer {sender_id[:12]} has too many channels"

        channel = PaymentChannel(
            channel_id=channel_id,
            sender_id=sender_id,
            receiver_id=receiver_id,
            deposit=deposit,
            state=ChannelState.OPEN,
            expires_at=time.time() + (expiry or self.config.default_expiry),
            dispute_period=self.config.dispute_period,
        )

        self._channels[channel_id] = channel
        self._peer_channels.setdefault(sender_id, []).append(channel_id)
        self._peer_channels.setdefault(receiver_id, []).append(channel_id)
        self._total_locked += deposit

        return channel, ""

    def pay(
        self,
        channel_id: str,
        amount: float,
        sender_id: str,
    ) -> tuple[PaymentUpdate | None, str]:
        """Create an off-chain payment in a channel.

        Returns (update, error_message). Update is None on failure.
        """
        channel = self._channels.get(channel_id)
        if channel is None:
            return None, f"Channel {channel_id} not found"
        if not channel.is_active:
            return None, f"Channel not active (state={channel.state.value})"
        if channel.is_expired:
            return None, "Channel expired"
        if sender_id != channel.sender_id:
            return None, "Only the sender can make payments"
        if amount <= 0:
            return None, "Payment amount must be positive"
        if amount > channel.sender_balance:
            return None, (
                f"Insufficient balance: {amount} > {channel.sender_balance}"
            )

        # Update balances
        channel.sender_balance -= amount
        channel.receiver_balance += amount
        channel.nonce += 1

        update = PaymentUpdate(
            channel_id=channel_id,
            nonce=channel.nonce,
            sender_balance=channel.sender_balance,
            receiver_balance=channel.receiver_balance,
        )
        channel.latest_update = update

        return update, ""

    def close_channel(
        self,
        channel_id: str,
        closer_id: str,
    ) -> tuple[dict[str, float] | None, str]:
        """Initiate cooperative channel close.

        Returns (settlement, error_message).
        Settlement is {sender_id: refund, receiver_id: payment, fee: fee}.
        """
        channel = self._channels.get(channel_id)
        if channel is None:
            return None, f"Channel {channel_id} not found"
        if channel.state == ChannelState.CLOSED:
            return None, "Channel already closed"
        if closer_id not in (channel.sender_id, channel.receiver_id):
            return None, "Only channel participants can close"

        return self._settle(channel)

    def dispute(
        self,
        channel_id: str,
        disputer_id: str,
        update: PaymentUpdate,
    ) -> tuple[bool, str]:
        """Submit a dispute with a newer state.

        If the submitted state has a higher nonce than the current one,
        the channel enters dispute period. After the period, settlement
        uses the disputed state.
        """
        channel = self._channels.get(channel_id)
        if channel is None:
            return False, f"Channel {channel_id} not found"
        if disputer_id not in (channel.sender_id, channel.receiver_id):
            return False, "Only participants can dispute"
        if channel.state == ChannelState.CLOSED:
            return False, "Channel already closed"

        # Must have higher nonce
        if update.nonce <= channel.nonce:
            return False, (
                f"Dispute nonce {update.nonce} not newer than {channel.nonce}"
            )

        # Validate totals match deposit
        if abs(update.total - channel.deposit) > 1e-10:
            return False, "Balance totals don't match deposit"

        # Accept dispute
        channel.state = ChannelState.DISPUTED
        channel.sender_balance = update.sender_balance
        channel.receiver_balance = update.receiver_balance
        channel.nonce = update.nonce
        channel.latest_update = update
        channel.dispute_deadline = time.time() + channel.dispute_period
        channel.disputed_by = disputer_id

        return True, ""

    def resolve_disputes(self) -> list[dict[str, Any]]:
        """Resolve expired disputes and settle channels.

        Call periodically to finalize disputed channels.
        """
        settled = []
        now = time.time()
        for channel in list(self._channels.values()):
            if (
                channel.state == ChannelState.DISPUTED
                and channel.dispute_deadline > 0
                and now >= channel.dispute_deadline
            ):
                result, _ = self._settle(channel)
                if result:
                    settled.append(result)
        return settled

    def _settle(self, channel: PaymentChannel) -> tuple[dict[str, float] | None, str]:
        """Settle a channel and distribute funds."""
        fee = channel.receiver_balance * self.config.settlement_fee_fraction
        receiver_payout = channel.receiver_balance - fee
        sender_refund = channel.sender_balance

        settlement = {
            "channel_id": channel.channel_id,
            "sender_id": channel.sender_id,
            "receiver_id": channel.receiver_id,
            "sender_refund": sender_refund,
            "receiver_payout": receiver_payout,
            "fee": fee,
            "nonce": channel.nonce,
            "total_paid": channel.total_paid,
        }

        channel.state = ChannelState.CLOSED
        self._total_locked -= channel.deposit
        self._total_settled += channel.total_paid
        self._total_fees += fee

        return settlement, ""

    # ── Queries ──────────────────────────────────────────────────

    def get_channel(self, channel_id: str) -> PaymentChannel | None:
        return self._channels.get(channel_id)

    def get_peer_channels(
        self, peer_id: str, active_only: bool = True,
    ) -> list[PaymentChannel]:
        channel_ids = self._peer_channels.get(peer_id, [])
        channels = [self._channels[cid] for cid in channel_ids if cid in self._channels]
        if active_only:
            channels = [c for c in channels if c.is_active]
        return channels

    def get_channel_between(
        self, sender_id: str, receiver_id: str,
    ) -> PaymentChannel | None:
        """Find an active channel between two peers."""
        for c in self.get_peer_channels(sender_id):
            if c.receiver_id == receiver_id and c.is_active:
                return c
        return None

    def cleanup_expired(self) -> int:
        """Close expired channels."""
        closed = 0
        for channel in list(self._channels.values()):
            if channel.is_active and channel.is_expired:
                self._settle(channel)
                closed += 1
        return closed

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_channels": len(self._channels),
            "active_channels": self.active_channels,
            "total_locked": self._total_locked,
            "total_settled": self._total_settled,
            "total_fees": self._total_fees,
        }
