"""Network message definitions for DON P2P protocol.

All messages are serialized as JSON for transport.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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
    """Exchange chain status with a peer for sync."""

    chain_height: int
    tip_hash: str
    tip_index: int
    finalized_height: int = 0


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
