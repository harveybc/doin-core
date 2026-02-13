"""Plugin interfaces for DON — optimization, inference, and synthetic data."""

from doin_core.plugins.base import (
    InferencePlugin,
    OptimizationPlugin,
    SyntheticDataPlugin,
)

from doin_core.plugins.base import hash_synthetic_data

__all__ = [
    "InferencePlugin",
    "OptimizationPlugin",
    "SyntheticDataPlugin",
    "hash_synthetic_data",
]
