"""Resource limits — bounds validation for hyperparameters and evaluation.

Prevents adversarial parameters that crash evaluators (OOM, infinite loops)
by enforcing strict bounds on all submitted hyperparameters and evaluation
resource usage.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ResourceLimits(BaseModel):
    """Resource limits for evaluation tasks."""

    max_training_seconds: float = Field(default=3600.0, description="Max training time per eval")
    max_memory_mb: float = Field(default=8192.0, description="Max memory usage in MB")
    max_epochs: int = Field(default=5000, description="Max training epochs")
    max_batch_size: int = Field(default=512, description="Max batch size")


class BoundsValidator:
    """Validates hyperparameters against configured bounds.

    Rejects any parameter that falls outside its declared bounds.
    This is checked BEFORE evaluation to prevent resource exhaustion.
    """

    def __init__(self, bounds: dict[str, tuple[float, float]] | None = None) -> None:
        self._bounds = bounds or {}

    def set_bounds(self, bounds: dict[str, tuple[float, float]]) -> None:
        self._bounds = bounds

    def validate(self, parameters: dict[str, Any]) -> tuple[bool, str]:
        """Validate parameters against bounds.

        Returns:
            (is_valid, reason) — reason is empty string if valid.
        """
        for key, value in parameters.items():
            if key not in self._bounds:
                continue  # Unknown params are allowed (plugin-specific)

            low, high = self._bounds[key]
            try:
                num_value = float(value) if not isinstance(value, (list, dict, bool)) else None
            except (TypeError, ValueError):
                num_value = None

            if num_value is None:
                continue  # Non-numeric params skip bounds check

            if num_value < low or num_value > high:
                return False, f"Parameter '{key}' = {num_value} outside bounds [{low}, {high}]"

        return True, ""

    def validate_resource_limits(
        self, parameters: dict[str, Any], limits: ResourceLimits
    ) -> tuple[bool, str]:
        """Validate that parameters don't exceed resource limits."""
        epochs = parameters.get("epochs", 0)
        if isinstance(epochs, (int, float)) and epochs > limits.max_epochs:
            return False, f"epochs={epochs} exceeds max {limits.max_epochs}"

        batch_size = parameters.get("batch_size", 0)
        if isinstance(batch_size, (int, float)) and batch_size > limits.max_batch_size:
            return False, f"batch_size={batch_size} exceeds max {limits.max_batch_size}"

        return True, ""
