"""Hashing utilities for DON blockchain."""

from __future__ import annotations

import hashlib


def sha256(data: str | bytes) -> str:
    """Compute SHA-256 hash of data."""
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def compute_merkle_root(hashes: list[str]) -> str:
    """Compute the Merkle root of a list of transaction hashes.

    Args:
        hashes: List of hex-encoded transaction hashes.

    Returns:
        Hex-encoded Merkle root. Returns '0' * 64 for empty list.
    """
    if not hashes:
        return "0" * 64

    if len(hashes) == 1:
        return hashes[0]

    # Duplicate last hash if odd number
    current_level = list(hashes)
    if len(current_level) % 2 == 1:
        current_level.append(current_level[-1])

    while len(current_level) > 1:
        next_level: list[str] = []
        for i in range(0, len(current_level), 2):
            combined = current_level[i] + current_level[i + 1]
            next_level.append(sha256(combined))
        current_level = next_level
        if len(current_level) > 1 and len(current_level) % 2 == 1:
            current_level.append(current_level[-1])

    return current_level[0]
