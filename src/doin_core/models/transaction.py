"""Transactions — events logged on the DON blockchain.

Canonical content binding (finding 201): every transaction ID is the SHA-256
hash of the transaction's canonical byte serialization. A transaction may be
constructed without an ID (the ID is derived), but a *supplied* ID must equal
the recomputed content hash exactly — construction fails closed otherwise.

The canonical byte format is frozen: a JSON object with exactly the keys
``tx_type``, ``domain_id``, ``peer_id``, ``payload`` and ``timestamp``
(ISO-8601), serialized with ``sort_keys=True`` and default separators. This
preserves byte/hash identity with every transaction created by earlier
releases, which used the same serialization. Any change to this format is a
versioned protocol migration, never a silent edit.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

#: A valid transaction ID is exactly 64 lowercase hexadecimal characters
#: (a SHA-256 digest in lowercase hex).
TX_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class TransactionIntegrityError(Exception):
    """A transaction ID does not match its canonical content hash.

    Raised when a supplied/stored/network transaction ID fails validation
    against the recomputed content hash, or is not 64 lowercase hex chars.
    Carries block/transaction coordinates when known. Never includes the
    transaction payload.

    Deliberately NOT a ``ValueError``: Pydantic v2 wraps ``ValueError`` from
    ``model_post_init`` into a ``ValidationError`` whose message embeds the
    raw input (a payload dump). Subclassing ``Exception`` keeps the error
    typed and payload-free through Pydantic construction.
    """

    def __init__(
        self,
        message: str,
        *,
        block_index: int | None = None,
        tx_index: int | None = None,
        tx_id: str | None = None,
    ) -> None:
        coords = []
        if block_index is not None:
            coords.append(f"block={block_index}")
        if tx_index is not None:
            coords.append(f"tx_index={tx_index}")
        if tx_id is not None:
            coords.append(f"tx_id={tx_id[:16]}…")
        if coords:
            message = f"{message} ({', '.join(coords)})"
        super().__init__(message)
        self.block_index = block_index
        self.tx_index = tx_index
        self.tx_id = tx_id


def canonical_transaction_bytes(
    *,
    tx_type: str,
    domain_id: str,
    peer_id: str,
    payload: dict[str, Any],
    timestamp: str,
) -> bytes:
    """The one canonical byte serialization of a transaction's content.

    Field set and ordering are frozen (see module docstring). ``timestamp``
    is the ISO-8601 string exactly as produced by ``datetime.isoformat()``.
    Key order inside ``payload`` is irrelevant: ``sort_keys=True`` makes
    semantically identical payloads serialize identically.
    """
    return json.dumps(
        {
            "tx_type": tx_type,
            "domain_id": domain_id,
            "peer_id": peer_id,
            "payload": payload,
            "timestamp": timestamp,
        },
        sort_keys=True,
    ).encode()


def compute_transaction_id(
    *,
    tx_type: str,
    domain_id: str,
    peer_id: str,
    payload: dict[str, Any],
    timestamp: str,
) -> str:
    """Compute the canonical content hash (transaction ID) from raw fields.

    This is usable directly on stored rows / wire fields so that validators
    never need to trust Pydantic construction as their only defense.
    """
    return hashlib.sha256(
        canonical_transaction_bytes(
            tx_type=tx_type,
            domain_id=domain_id,
            peer_id=peer_id,
            payload=payload,
            timestamp=timestamp,
        )
    ).hexdigest()


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

    # Per-candidate evaluation results (all candidates, not just champions)
    CANDIDATE_EVALUATED = "candidate_evaluated"


class Transaction(BaseModel):
    """A single event logged on the DON blockchain.

    Transactions record optimae acceptances, evaluation requests served,
    and domain lifecycle events. The ordering consensus of these transactions
    provides the decentralized timestamping service.

    The ``id`` is bound to content: empty at construction → derived from the
    canonical content hash; supplied → must equal the recomputed content hash
    (64 lowercase hex) or construction raises ``TransactionIntegrityError``.
    """

    id: str = Field(
        default="",
        description="Transaction hash (SHA-256 of canonical content bytes)",
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
        """Derive an empty ID; fail closed on a supplied ID that does not
        match the recomputed canonical content hash."""
        if not self.id:
            self.id = self.compute_id()
            return
        if not TX_ID_PATTERN.fullmatch(self.id):
            raise TransactionIntegrityError(
                "transaction ID is not 64 lowercase hexadecimal characters",
                tx_id=self.id,
            )
        expected = self.compute_id()
        if self.id != expected:
            raise TransactionIntegrityError(
                "transaction ID does not match canonical content hash "
                f"(expected {expected[:16]}…)",
                tx_id=self.id,
            )

    def canonical_bytes(self) -> bytes:
        """Canonical byte serialization of this transaction's content."""
        return canonical_transaction_bytes(
            tx_type=self.tx_type.value,
            domain_id=self.domain_id,
            peer_id=self.peer_id,
            payload=self.payload,
            timestamp=self.timestamp.isoformat(),
        )

    def compute_id(self) -> str:
        """Compute the deterministic transaction hash from canonical bytes."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def verify_integrity(self) -> None:
        """Re-verify that the current ID matches the current content.

        Guards against post-construction mutation. Raises
        ``TransactionIntegrityError`` on mismatch.
        """
        expected = self.compute_id()
        if self.id != expected or not TX_ID_PATTERN.fullmatch(self.id):
            raise TransactionIntegrityError(
                "transaction ID does not match canonical content hash "
                f"(expected {expected[:16]}…)",
                tx_id=self.id,
            )
