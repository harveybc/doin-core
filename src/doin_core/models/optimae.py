"""Optimae — optimized model parameters submitted by optimizers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class Optimae(BaseModel):
    """Represents a set of optimized parameters for a specific domain.

    An optimae is produced by an optimizer when it surpasses the current
    best-known performance for a domain. It contains the optimized parameters
    as JSON-serializable data, the reported performance metric, and metadata
    for network validation.
    """

    id: str = Field(
        default="",
        description="Unique identifier (hash of domain_id + params + optimizer_id + timestamp)",
    )
    domain_id: str = Field(
        description="ID of the domain (model) this optimae belongs to",
    )
    optimizer_id: str = Field(
        description="Peer ID of the optimizer that produced this optimae",
    )
    parameters: dict[str, Any] = Field(
        description="Optimized parameters as JSON-serializable dict",
    )
    reported_performance: float = Field(
        description="Performance metric reported by the optimizer",
    )
    verified_performance: float | None = Field(
        default=None,
        description="Performance verified by evaluators (None until verified)",
    )
    performance_increment: float = Field(
        default=0.0,
        description="Improvement over previous best optimae",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this optimae was produced",
    )
    accepted: bool = Field(
        default=False,
        description="Whether the network has accepted this optimae",
    )

    def model_post_init(self, __context: Any) -> None:
        """Generate ID if not set."""
        if not self.id:
            self.id = self.compute_id()

    def compute_id(self) -> str:
        """Compute deterministic ID from content."""
        payload = json.dumps(
            {
                "domain_id": self.domain_id,
                "parameters": self.parameters,
                "optimizer_id": self.optimizer_id,
                "timestamp": self.timestamp.isoformat(),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()
