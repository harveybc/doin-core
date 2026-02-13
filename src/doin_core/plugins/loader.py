"""Plugin discovery and loading via setuptools entry points."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import TypeVar

from doin_core.plugins.base import (
    InferencePlugin,
    OptimizationPlugin,
    SyntheticDataPlugin,
)

T = TypeVar("T")

# Entry point group names
OPTIMIZATION_GROUP = "doin.optimization"
INFERENCE_GROUP = "doin.inference"
SYNTHETIC_DATA_GROUP = "doin.synthetic_data"


class PluginNotFoundError(Exception):
    """Raised when a requested plugin is not installed."""


def _load_plugin(group: str, name: str, expected_type: type[T]) -> type[T]:
    """Load a plugin class by entry point group and name.

    Args:
        group: Entry point group (e.g., 'doin.optimization').
        name: Plugin name as registered in entry points.
        expected_type: Expected base class.

    Returns:
        The plugin class (not an instance).

    Raises:
        PluginNotFoundError: If plugin not found.
        TypeError: If loaded class doesn't match expected type.
    """
    eps = entry_points()
    group_eps = eps.select(group=group) if hasattr(eps, "select") else eps.get(group, [])

    for ep in group_eps:
        if ep.name == name:
            cls = ep.load()
            if not (isinstance(cls, type) and issubclass(cls, expected_type)):
                msg = f"Plugin '{name}' in '{group}' is not a subclass of {expected_type.__name__}"
                raise TypeError(msg)
            return cls  # type: ignore[return-value]

    msg = f"Plugin '{name}' not found in entry point group '{group}'"
    raise PluginNotFoundError(msg)


def load_optimization_plugin(name: str) -> type[OptimizationPlugin]:
    """Load an optimization plugin by name."""
    return _load_plugin(OPTIMIZATION_GROUP, name, OptimizationPlugin)


def load_inference_plugin(name: str) -> type[InferencePlugin]:
    """Load an inference plugin by name."""
    return _load_plugin(INFERENCE_GROUP, name, InferencePlugin)


def load_synthetic_data_plugin(name: str) -> type[SyntheticDataPlugin]:
    """Load a synthetic data generation plugin by name."""
    return _load_plugin(SYNTHETIC_DATA_GROUP, name, SyntheticDataPlugin)


def list_plugins(group: str) -> list[str]:
    """List all available plugin names in a group."""
    eps = entry_points()
    group_eps = eps.select(group=group) if hasattr(eps, "select") else eps.get(group, [])
    return [ep.name for ep in group_eps]
