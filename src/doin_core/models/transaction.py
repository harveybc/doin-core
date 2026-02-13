"""Transactions — events logged on the DON blockchain."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TransactionType(str, Enum):
    """Types of events that get logged on-chain.

    Every network event is recorded as a transaction.
    The blockchain provides ordering consensus (decentralized timestamping).
    """

    # Optimae lifecycle
    OPTIMAE_ANNOUNCED = "optimae_announced"
    OPTIMAE_ACCEPTED = "optimae_accepted"
    OPTIMAE_REJECTED = "optimae_rejected"

    # Task lifecycle (work queue)
    TASK_CREATED = "task_created"
    TASK_CLAIMED = "task_claimed"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"

    # Inference served to clients
    EVALUATION_SERVED = "evaluation_served"

    # Domain lifecycle
    DOMAIN_REGISTERED = "domain_registered"
    DOMAIN_UPDATED = "domain_updated"


class Transaction(BaseModel):
    """A single event logged on the DON blockchain.

    Transactions record optimae acceptances, evaluation requests served,
    and domain lifecycle events. The ordering consensus of these transactions
    provides the decentralized timestamping service.
    """

    id: str = Field(
        default="",
        description="Transaction hash",
    )
    tx_type: TransactionType = Field(
        description="Type of transaction",
    )
    domain_id: str = Field(
        description="Domain this transaction relates to",
    )
    peer_id: str = Field(
        description="Peer that originated this transaction",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Transaction-specific data",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this transaction was created",
    )

    def model_post_init(self, __context: Any) -> None:
        """Generate ID if not set."""
        if not self.id:
            self.id = self.compute_id()

    def compute_id(self) -> str:
        """Compute deterministic transaction hash."""
        payload = json.dumps(
            {
                "tx_type": self.tx_type.value,
                "domain_id": self.domain_id,
                "peer_id": self.peer_id,
                "payload": self.payload,
                "timestamp": self.timestamp.isoformat(),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()
