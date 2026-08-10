"""Typed chain-verification contract (findings 202-203).

``doin-core`` owns the *contract*: the report types every verifier must
return and the outcome semantics every consumer must honor. The one
authoritative verifier implementation lives in ``doin-node``
(``doin_node.blockchain.verify``), which executes ten ordered checks
against a SQLite chain database and returns a ``ChainVerificationReport``.

Outcome semantics (correction order §5, WP2):

- ``fully_verified`` — every check passed and every transaction body
  required for Merkle recomputation was present and verified.
- ``verified_suffix_from_checkpoint`` — the chain is pruned; the header
  chain, checkpoint commitment and the retained suffix all verified. A
  pruned chain is NEVER reported ``fully_verified``.
- ``failed`` — a check failed. ``first_failure`` carries the exact first
  failing block/transaction coordinate. No payload is ever included.
- ``refused`` — required provenance (e.g. pruning/checkpoint metadata,
  or an expected chain identity that the database cannot attest) is
  absent or contradictory. Absence of required provenance is refusal,
  never success.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class ChainVerificationOutcome(str, Enum):
    """Overall result of a chain verification run."""

    FULLY_VERIFIED = "fully_verified"
    VERIFIED_SUFFIX_FROM_CHECKPOINT = "verified_suffix_from_checkpoint"
    FAILED = "failed"
    REFUSED = "refused"


class CheckStatus(str, Enum):
    """Status of one ordered verifier check."""

    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"       # not executed because an earlier check failed
    UNAVAILABLE = "unavailable"  # required provenance absent — treated as refusal


class VerificationCheck(BaseModel):
    """One of the ten ordered verifier checks."""

    number: int = Field(description="Ordered check number (1-10)")
    name: str = Field(description="Stable check identifier")
    status: CheckStatus
    detail: str = Field(default="", description="Human-readable, payload-free detail")
    first_failing_block: int | None = Field(
        default=None, description="Block index of the first failure, if any"
    )
    first_failing_tx: int | None = Field(
        default=None, description="tx_index of the first failure, if any"
    )


class FailureCoordinate(BaseModel):
    """Exact first failing coordinate — never includes payload data."""

    check_number: int
    check_name: str
    block_index: int | None = None
    tx_index: int | None = None
    reason: str = ""


class VerifiedSuffixFromCheckpoint(BaseModel):
    """Typed result for a pruned chain whose retained suffix verified.

    Returned only when the checkpoint commitment verified AND every block
    at or above ``suffix_start_index`` fully verified (bodies, content
    hashes and Merkle roots).
    """

    checkpoint_block_index: int = Field(
        description="Index of the checkpoint block the suffix chains from"
    )
    checkpoint_block_hash: str = Field(
        description="Committed hash of the checkpoint block"
    )
    suffix_start_index: int = Field(
        description="First block whose transaction bodies are fully retained"
    )
    suffix_end_index: int = Field(description="Verified tip index")
    suffix_tip_hash: str = Field(description="Verified tip hash")
    pruned_body_blocks: int = Field(
        default=0,
        description="Number of blocks whose transaction bodies were pruned",
    )


class ChainVerificationReport(BaseModel):
    """Typed report of one full chain verification run."""

    outcome: ChainVerificationOutcome
    db_path: str = ""
    protocol_version: int = 0

    # Identity as attested by the database (metadata) and as expected.
    chain_id: str = ""
    genesis_hash: str = ""
    expected_chain_id: str | None = None
    expected_genesis_hash: str | None = None

    # Chain shape derived from verified rows.
    height: int = 0
    tip_index: int = -1
    tip_hash: str = ""

    checks: list[VerificationCheck] = Field(default_factory=list)
    first_failure: FailureCoordinate | None = None
    verified_suffix: VerifiedSuffixFromCheckpoint | None = None

    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    finished_at: datetime | None = None

    @property
    def ok(self) -> bool:
        """True only for the two verified outcomes."""
        return self.outcome in (
            ChainVerificationOutcome.FULLY_VERIFIED,
            ChainVerificationOutcome.VERIFIED_SUFFIX_FROM_CHECKPOINT,
        )
