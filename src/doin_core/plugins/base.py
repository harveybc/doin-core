"""Abstract base classes for DON plugins.

All plugins are discovered via setuptools entry points:
    [project.entry-points."doin.optimization"]
    my_optimizer = "my_package:MyOptimizer"

    [project.entry-points."doin.inference"]
    my_inferencer = "my_package:MyInferencer"

    [project.entry-points."doin.synthetic_data"]
    my_generator = "my_package:MyGenerator"
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any

import numpy as np


class OptimizationPlugin(ABC):
    """Interface for optimization plugins.

    An optimization plugin performs the actual optimization work (e.g.,
    genetic algorithm for hyperparameter search, gradient-based optimization,
    etc.) and reports optimized parameters when they surpass the current best.
    """

    @abstractmethod
    def configure(self, config: dict[str, Any]) -> None:
        """Initialize the plugin with domain-specific configuration.

        Args:
            config: Plugin configuration from the domain's DomainConfig.
        """

    @abstractmethod
    def optimize(
        self,
        current_best_params: dict[str, Any] | None,
        current_best_performance: float | None,
    ) -> tuple[dict[str, Any], float]:
        """Run one optimization step.

        Args:
            current_best_params: Current best parameters in the network (None if first).
            current_best_performance: Current best performance metric (None if first).

        Returns:
            Tuple of (optimized_parameters, reported_performance).
            Only return if performance exceeds current_best_performance.

        Raises:
            NoImprovementError: If no improvement was found in this step.
        """

    @abstractmethod
    def get_domain_metadata(self) -> dict[str, Any]:
        """Return metadata about this optimization domain.

        Returns:
            Dict with at minimum 'performance_metric' and 'higher_is_better'.
        """


class InferencePlugin(ABC):
    """Interface for inference plugins.

    Used by evaluators to verify reported performance of optimae.
    The inference plugin loads the model with given parameters and
    evaluates on provided data to produce a performance metric.
    """

    @abstractmethod
    def configure(self, config: dict[str, Any]) -> None:
        """Initialize the plugin with domain-specific configuration."""

    @abstractmethod
    def evaluate(
        self,
        parameters: dict[str, Any],
        data: dict[str, Any] | None = None,
    ) -> float:
        """Evaluate model performance with given parameters.

        Args:
            parameters: The optimized parameters to evaluate.
            data: Optional evaluation data. If None, uses the plugin's
                  default validation dataset.

        Returns:
            The computed performance metric.
        """


class SyntheticDataPlugin(ABC):
    """Interface for synthetic data generation plugins.

    MANDATORY for verification trust — domains without a synthetic
    data plugin get ZERO consensus weight.

    CRITICAL: The generate() method MUST be deterministic given the same
    seed. All evaluators in a quorum use the same seed, so they must
    produce identical synthetic data. This is verified via hash consensus.
    """

    @abstractmethod
    def configure(self, config: dict[str, Any]) -> None:
        """Initialize the plugin with domain-specific configuration."""

    @abstractmethod
    def generate(self, seed: int | None = None) -> dict[str, Any]:
        """Generate synthetic evaluation data.

        MUST be deterministic: same seed → same output, always.

        Args:
            seed: Random seed for deterministic generation.
                  When used for quorum verification, this seed is derived
                  from the commitment hash — all evaluators get the same seed.

        Returns:
            Synthetic data dict compatible with the domain's inference plugin.
        """

    def generate_with_hash(self, seed: int | None = None) -> tuple[dict[str, Any], str]:
        """Generate synthetic data and compute its hash.

        This is the method evaluators should call. The hash is included
        in the verification vote so the quorum can verify all evaluators
        used identical synthetic data.

        Returns:
            (synthetic_data, sha256_hash)
        """
        data = self.generate(seed)
        data_hash = hash_synthetic_data(data)
        return data, data_hash


def hash_synthetic_data(data: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 hash of synthetic data.

    Handles numpy arrays, lists, scalars, and nested dicts.
    The hash is order-independent for dict keys (sorted) and
    uses a canonical representation for floating point values.

    All evaluators computing this hash on identical data will get
    the same result, enabling consensus verification.
    """
    hasher = hashlib.sha256()

    def _feed(obj: Any) -> None:
        if isinstance(obj, dict):
            for key in sorted(obj.keys()):
                hasher.update(key.encode())
                _feed(obj[key])
        elif isinstance(obj, np.ndarray):
            # Use tobytes for exact binary representation
            hasher.update(obj.tobytes())
            # Also include shape and dtype for safety
            hasher.update(str(obj.shape).encode())
            hasher.update(str(obj.dtype).encode())
        elif isinstance(obj, (list, tuple)):
            arr = np.array(obj)
            hasher.update(arr.tobytes())
            hasher.update(str(arr.shape).encode())
        elif isinstance(obj, (int, float)):
            hasher.update(repr(obj).encode())
        elif isinstance(obj, str):
            hasher.update(obj.encode())
        elif isinstance(obj, bool):
            hasher.update(b"T" if obj else b"F")
        elif obj is None:
            hasher.update(b"None")
        else:
            hasher.update(str(obj).encode())

    _feed(data)
    return hasher.hexdigest()
