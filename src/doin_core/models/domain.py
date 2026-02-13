"""Domain — a model being optimized in the DON network."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DomainConfig(BaseModel):
    """Configuration for a domain's plugin ecosystem.

    Each domain requires at minimum an optimization plugin and an inference
    plugin. Optionally, a synthetic data generation plugin can be specified
    to allow evaluators to validate on generated data (preventing overfitting).
    """

    optimization_plugin: str = Field(
        description="Entry point or module path for the optimization plugin",
    )
    inference_plugin: str = Field(
        description="Entry point or module path for the inference plugin",
    )
    synthetic_data_plugin: str | None = Field(
        default=None,
        description="Optional entry point for synthetic data generation plugin",
    )
    plugin_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional configuration passed to plugins",
    )


class Domain(BaseModel):
    """A domain represents a model being optimized across the network.

    Each domain has its own performance metric, plugin configuration,
    and contributes a weighted amount to the proof-of-optimization
    threshold for block generation.
    """

    id: str = Field(
        description="Unique domain identifier",
    )
    name: str = Field(
        description="Human-readable domain name",
    )
    description: str = Field(
        default="",
        description="Description of what this domain optimizes",
    )
    performance_metric: str = Field(
        description="Name of the performance metric (e.g., 'mse', 'accuracy', 'f1')",
    )
    higher_is_better: bool = Field(
        default=True,
        description="Whether higher metric values indicate better performance",
    )
    weight: float = Field(
        default=1.0,
        description="Weight of this domain in the proof-of-optimization threshold",
    )
    config: DomainConfig = Field(
        description="Plugin configuration for this domain",
    )
    current_best_performance: float | None = Field(
        default=None,
        description="Current best-known performance in the network",
    )
