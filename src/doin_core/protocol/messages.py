"""Network message definitions for DON P2P protocol.

All messages are serialized as JSON for transport.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

#: Versioned protocol constant (findings 202-203). Version 2 introduces
#: explicit chain identity (``chain_id`` + ``genesis_hash``) in
#: ``ChainStatus``. Peers exchanging chain data MUST attest the same
#: protocol version and chain identity before any block exchange; a
#: mismatch — or an *absent* attestation — is a typed refusal, never
#: field-default acceptance.
PROTOCOL_VERSION = 2


class PeerChainMismatchError(Exception):
    """Typed refusal: a peer's chain attestation is incompatible with ours.

    Raised before any block exchange. Carries the offending field with the
    expected/received values (short identifiers only — never payloads).
    """

    def __init__(self, field: str, expected: object, received: object) -> None:
        super().__init__(
            f"peer chain mismatch on {field}: "
            f"expected {expected!r}, received {received!r}"
        )
        self.field = field
        self.expected = expected
        self.received = received


class ProtocolVersionMismatchError(PeerChainMismatchError):
    """The peer speaks a different (or unattested) protocol version."""


class ChainIdentityMismatchError(PeerChainMismatchError):
    """The peer's chain_id / genesis_hash differs from (or omits) ours."""


class MessageType(str, Enum):
    """Types of messages in the DON P2P protocol.

    ALL messages are flooded to the network and logged on-chain.
    This provides decentralized timestamping and an auditable record
    of every event in the network.
    """

    # Optimae lifecycle (commit-reveal)
    OPTIMAE_COMMIT = "optimae_commit"
    OPTIMAE_REVEAL = "optimae_reveal"
    OPTIMAE_ANNOUNCEMENT = "optimae_announcement"  # Legacy / direct mode

    # Task lifecycle
    TASK_CREATED = "task_created"
    TASK_CLAIMED = "task_claimed"
    TASK_COMPLETED = "task_completed"

    # Chain
    BLOCK_ANNOUNCEMENT = "block_announcement"

    # Block sync
    CHAIN_STATUS = "chain_status"
    BLOCK_REQUEST = "block_request"
    BLOCK_RESPONSE = "block_response"

    # Network
    PEER_DISCOVERY = "peer_discovery"

    # Champion sync (island model — request best on startup)
    CHAMPION_REQUEST = "champion_request"
    CHAMPION_RESPONSE = "champion_response"

    # Stage synchronisation (island model — all nodes advance stages together)
    STAGE_COMPLETE = "stage_complete"

    # Per-candidate evaluation broadcast (research mode — accepted without verification)
    CANDIDATE_EVALUATION = "candidate_evaluation"

    # Legacy
    EVALUATION_REQUEST = "evaluation_request"
    EVALUATION_RESPONSE = "evaluation_response"


class Message(BaseModel):
    """Base message wrapper for all DON protocol messages."""

    msg_type: MessageType = Field(description="Type of message")
    sender_id: str = Field(description="Peer ID of the sender")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    ttl: int = Field(
        default=7,
        description="Time-to-live for controlled flooding (hop count)",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific payload",
    )


class OptimaeCommit(BaseModel):
    """Phase 1 of commit-reveal: optimizer commits hash of optimae."""

    commitment_hash: str
    domain_id: str


class OptimaeReveal(BaseModel):
    """Phase 2 of commit-reveal: optimizer reveals full parameters."""

    commitment_hash: str
    domain_id: str
    optimae_id: str
    parameters: dict[str, Any]
    reported_performance: float
    nonce: str
    champion_metrics: dict[str, Any] | None = None  # MAE breakdowns from originator


class OptimaeAnnouncement(BaseModel):
    """Optimizer announces new optimae to the network.

    Legacy / direct mode (without commit-reveal). Used for testing
    and networks where front-running is not a concern.
    """

    domain_id: str
    optimae_id: str
    parameters: dict[str, Any]
    reported_performance: float
    previous_best_performance: float | None = None


class EvaluationRequest(BaseModel):
    """Client requests inference from an evaluator."""

    domain_id: str
    input_data: dict[str, Any]
    request_id: str


class EvaluationResponse(BaseModel):
    """Evaluator responds with inference result."""

    request_id: str
    domain_id: str
    result: dict[str, Any]
    optimae_id: str = Field(
        description="Which optimae was used for this inference",
    )


class BlockAnnouncement(BaseModel):
    """Node announces a newly generated block."""

    block_index: int
    block_hash: str
    previous_hash: str
    generator_id: str
    transaction_count: int
    weighted_performance_sum: float
    threshold: float


class TaskCreated(BaseModel):
    """Flooded when a new task is added to the work queue.

    Created by nodes when an optimizer submits an optimae (verification task)
    or when a client requests inference.
    """

    task_id: str
    task_type: str  # "optimae_verification" or "inference_request"
    domain_id: str
    requester_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    optimae_id: str | None = None
    reported_performance: float | None = None
    metric_evidence: dict[str, Any] = Field(default_factory=dict)
    priority: int = 10


class TaskClaimed(BaseModel):
    """Flooded when an evaluator claims a pending task."""

    task_id: str
    evaluator_id: str
    domain_id: str


class TaskCompleted(BaseModel):
    """Flooded when an evaluator completes a task.

    Contains the verified performance (for verification tasks)
    or inference result (for inference tasks).
    """

    task_id: str
    evaluator_id: str
    domain_id: str
    verified_performance: float | None = None
    result: dict[str, Any] | None = None
    optimae_id: str | None = None


class ChainStatus(BaseModel):
    """Exchange chain status with a peer for sync.

    ``protocol_version``, ``chain_id`` and ``genesis_hash`` are the peer's
    explicit chain attestation (protocol v2, findings 202-203). The zero /
    empty defaults exist only so that *legacy* (pre-v2) statuses can still
    be parsed for diagnostics — they mean "not attested". Acceptance is
    decided exclusively by :func:`validate_peer_chain_status`, which
    refuses unattested or mismatched identity with a typed error. The
    defaults are never grounds for acceptance.
    """

    chain_height: int
    tip_hash: str
    tip_index: int
    finalized_height: int = 0
    protocol_version: int = 0  # 0 = not attested (legacy peer)
    chain_id: str = ""         # "" = not attested (legacy peer)
    genesis_hash: str = ""     # "" = not attested (legacy peer)


def validate_peer_chain_status(
    status: ChainStatus,
    *,
    expected_chain_id: str,
    expected_genesis_hash: str,
    expected_protocol_version: int = PROTOCOL_VERSION,
) -> None:
    """Refuse a peer's chain status unless it exactly attests our chain.

    Must be called BEFORE any block exchange with the peer. Raises:

    - :class:`ProtocolVersionMismatchError` when the peer's protocol
      version differs from ours or is absent (0);
    - :class:`ChainIdentityMismatchError` when ``chain_id`` or
      ``genesis_hash`` differs from ours or is absent ("").

    Absent fields are refusals — a legacy peer that cannot attest its
    chain identity is not accepted by default.
    """
    if status.protocol_version != expected_protocol_version:
        raise ProtocolVersionMismatchError(
            "protocol_version",
            expected_protocol_version,
            status.protocol_version,
        )
    if status.chain_id != expected_chain_id:
        raise ChainIdentityMismatchError(
            "chain_id", expected_chain_id, status.chain_id
        )
    if status.genesis_hash != expected_genesis_hash:
        raise ChainIdentityMismatchError(
            "genesis_hash", expected_genesis_hash, status.genesis_hash
        )


class BlockRequest(BaseModel):
    """Request blocks from a peer by index range."""

    from_index: int
    to_index: int  # Inclusive
    request_id: str = ""


class BlockResponse(BaseModel):
    """Response containing requested blocks (serialized)."""

    request_id: str = ""
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    has_more: bool = False


class ChampionRequest(BaseModel):
    """Request current best champion for a domain from peers."""

    domain_id: str
    request_id: str = ""


class ChampionResponse(BaseModel):
    """Response with current best champion for a domain."""

    domain_id: str
    request_id: str = ""
    parameters: dict[str, Any] | None = None
    performance: float | None = None
    has_champion: bool = False


class PeerDiscovery(BaseModel):
    """Peer discovery / neighbor announcement."""

    peer_id: str
    addresses: list[str] = Field(default_factory=list)
    domains: list[str] = Field(
        default_factory=list,
        description="Domain IDs this peer participates in",
    )
    roles: list[str] = Field(
        default_factory=list,
        description="Roles this peer serves: optimizer, evaluator, node",
    )
