"""Commit-Reveal scheme for optimae submission.

Prevents front-running: optimizer commits hash(optimae) first,
then reveals the full optimae after the commitment is on-chain.
Evaluators only see parameters after the timestamp is established.

Flow:
1. Optimizer produces optimae → computes commitment = hash(params + nonce)
2. Broadcasts OPTIMAE_COMMIT with commitment hash
3. Waits for commitment to appear in at least one block (or N confirmations)
4. Broadcasts OPTIMAE_REVEAL with full params + nonce
5. Network verifies hash(params + nonce) matches the commitment
6. Verification quorum begins
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from pydantic import BaseModel, Field


class Commitment(BaseModel):
    """A commitment to an optimae (hash only, no params revealed yet)."""

    commitment_hash: str = Field(description="SHA-256 of (params_json + nonce)")
    domain_id: str
    optimizer_id: str
    timestamp: float = Field(default_factory=time.time)
    revealed: bool = False
    expired: bool = False


class Reveal(BaseModel):
    """The reveal phase — full parameters + nonce."""

    commitment_hash: str
    domain_id: str
    optimizer_id: str
    parameters: dict[str, Any]
    nonce: str
    reported_performance: float


def compute_commitment(parameters: dict[str, Any], nonce: str) -> str:
    """Compute the commitment hash for given parameters and nonce."""
    payload = json.dumps(parameters, sort_keys=True) + ":" + nonce
    return hashlib.sha256(payload.encode()).hexdigest()


def verify_commitment(commitment_hash: str, parameters: dict[str, Any], nonce: str) -> bool:
    """Verify that a reveal matches a commitment."""
    return compute_commitment(parameters, nonce) == commitment_hash


class CommitRevealManager:
    """Manages the commit-reveal protocol for optimae.

    Commitments expire after max_commit_age_seconds if not revealed.
    """

    def __init__(self, max_commit_age: float = 600.0) -> None:
        self._commitments: dict[str, Commitment] = {}  # hash → Commitment
        self._max_age = max_commit_age

    def add_commitment(self, commitment: Commitment) -> bool:
        """Register a new commitment. Returns False if duplicate."""
        if commitment.commitment_hash in self._commitments:
            return False
        self._commitments[commitment.commitment_hash] = commitment
        return True

    def process_reveal(self, reveal: Reveal) -> bool:
        """Process a reveal and verify it matches a commitment.

        Returns True if valid (commitment exists, not expired, hash matches).
        """
        commitment = self._commitments.get(reveal.commitment_hash)
        if commitment is None:
            return False

        if commitment.revealed:
            return False  # Already revealed

        if commitment.expired:
            return False

        # Check age
        if time.time() - commitment.timestamp > self._max_age:
            commitment.expired = True
            return False

        # Verify the hash matches
        if not verify_commitment(
            reveal.commitment_hash, reveal.parameters, reveal.nonce
        ):
            return False

        # Verify same optimizer
        if reveal.optimizer_id != commitment.optimizer_id:
            return False

        # Verify same domain
        if reveal.domain_id != commitment.domain_id:
            return False

        commitment.revealed = True
        return True

    def cleanup_expired(self) -> int:
        """Remove expired and revealed commitments. Returns count removed."""
        now = time.time()
        to_remove = []
        for h, c in self._commitments.items():
            if c.revealed or c.expired or (now - c.timestamp > self._max_age):
                to_remove.append(h)
        for h in to_remove:
            del self._commitments[h]
        return len(to_remove)

    def has_valid_commitment(self, commitment_hash: str) -> bool:
        """Check if a valid (unrevealed, unexpired) commitment exists."""
        c = self._commitments.get(commitment_hash)
        if c is None:
            return False
        if c.revealed or c.expired:
            return False
        if time.time() - c.timestamp > self._max_age:
            c.expired = True
            return False
        return True

    @property
    def pending_count(self) -> int:
        return sum(
            1 for c in self._commitments.values()
            if not c.revealed and not c.expired
        )
