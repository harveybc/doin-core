"""Deterministic body and manifest bytes for an existing block.

Encoding is UTF-8 JSON: object keys sorted, separators ``(",", ":")``,
non-finite numbers refused. The body digest is SHA-256 of those exact
bytes. The manifest binds section digests, sizes and ordered inventory and
is hashed the same way. Neither document contains its own digest. The
header hash is the block's existing header hash, not either archive digest.

No validation, reward, difficulty or merkle rule is applied. A round with
no block is archived as UNANCHORED records, never as a substitute empty block.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from doin_core.models.block import Block
from doin_core.models.transaction import Transaction

BODY_SCHEMA = "doin.block_body.v1"
UNANCHORED_SCHEMA = "doin.unanchored_records.v1"
MANIFEST_SCHEMA = "doin.archive_manifest.v1"

_RECORD_FIELDS = (
    "record_id",
    "candidate_id",
    "attempt",
    "won",
    "domain_id",
    "peer_id",
    "performance",
)


class ArchiveRefusal(ValueError):
    """The bytes are not a valid archive document or failed read-back."""


@dataclass(frozen=True)
class Section:
    """One manifest section. ``content`` is not embedded in the manifest."""

    name: str
    digest: str
    size: int
    content: bytes


@dataclass(frozen=True)
class ArchiveEnvelope:
    """Body and manifest bytes plus the digests computed from them."""

    body: bytes
    body_digest: str
    manifest: bytes
    manifest_digest: str
    header_hash: str | None
    anchor: str
    sections: tuple[Section, ...]
    inventory: tuple[dict[str, Any], ...]


def canonical_bytes(value: Any) -> bytes:
    """Canonical JSON bytes. Raises ArchiveRefusal on non-finite numbers."""
    _reject_non_finite(value)
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ArchiveRefusal(f"NOT_CANONICAL: {exc}") from exc
    return text.encode("utf-8")


def digest_bytes(data: bytes) -> str:
    """SHA-256 hex digest of exact bytes."""
    if not isinstance(data, bytes):
        raise ArchiveRefusal("DIGEST_REQUIRES_BYTES")
    return hashlib.sha256(data).hexdigest()


def build_archive(
    *,
    block: Block | None,
    candidates: Sequence[Mapping[str, Any]],
    retries: Sequence[Mapping[str, Any]] | None = None,
) -> ArchiveEnvelope:
    """Serialize one round. ``block`` None archives candidate records as UNANCHORED."""
    retry_rows = list(retries or [])
    candidate_rows = [_normalize_record(raw, kind="candidate") for raw in candidates]
    normalized_retries = [_normalize_record(raw, kind="retry") for raw in retry_rows]
    _reject_duplicate_records(candidate_rows, normalized_retries)

    if block is None:
        if not candidate_rows and not normalized_retries:
            raise ArchiveRefusal("EMPTY_ROUND")
        return _unanchored(candidate_rows, normalized_retries)
    if not isinstance(block, Block):
        raise ArchiveRefusal("BLOCK_REQUIRED")
    return _anchored(block, candidate_rows, normalized_retries)


def _anchored(
    block: Block,
    candidates: list[dict[str, Any]],
    retries: list[dict[str, Any]],
) -> ArchiveEnvelope:
    header = _header_dict(block)
    transactions = [_transaction_dict(tx) for tx in block.transactions]
    header_hash = block.hash or block.header.compute_hash()
    if not isinstance(header_hash, str) or len(header_hash) != 64:
        raise ArchiveRefusal("HEADER_HASH_REQUIRED")
    body_obj = {
        "schema": BODY_SCHEMA,
        "header": header,
        "transactions": transactions,
        "header_hash": header_hash,
    }
    _reject_non_finite(body_obj)
    body = canonical_bytes(body_obj)
    sections = (
        _section("header", header),
        _section("transactions", transactions),
        _section("header_hash", header_hash),
        _section("candidates", candidates),
        _section("retries", retries),
    )
    inventory = _inventory(transactions, candidates, retries)
    return _envelope(
        body=body,
        header_hash=header_hash,
        anchor="ANCHORED",
        sections=sections,
        inventory=inventory,
        transaction_count=len(transactions),
    )


def _unanchored(
    candidates: list[dict[str, Any]],
    retries: list[dict[str, Any]],
) -> ArchiveEnvelope:
    body_obj = {
        "schema": UNANCHORED_SCHEMA,
        "anchor": "UNANCHORED",
        "candidates": candidates,
        "retries": retries,
    }
    body = canonical_bytes(body_obj)
    sections = (
        _section("candidates", candidates),
        _section("retries", retries),
    )
    inventory = _inventory([], candidates, retries)
    return _envelope(
        body=body,
        header_hash=None,
        anchor="UNANCHORED",
        sections=sections,
        inventory=inventory,
        transaction_count=0,
    )


def _envelope(
    *,
    body: bytes,
    header_hash: str | None,
    anchor: str,
    sections: tuple[Section, ...],
    inventory: list[dict[str, Any]],
    transaction_count: int,
) -> ArchiveEnvelope:
    body_digest = digest_bytes(body)
    manifest_obj = {
        "schema": MANIFEST_SCHEMA,
        "anchor": anchor,
        "header_hash": header_hash,
        "body_digest": body_digest,
        "sections": [
            {"name": section.name, "digest": section.digest, "size": section.size}
            for section in sections
        ],
        "inventory": inventory,
        "counts": {
            "transactions": transaction_count,
            "candidates": sum(1 for item in inventory if item["kind"] == "candidate"),
            "retries": sum(1 for item in inventory if item["kind"] == "retry"),
        },
        "sizes": {
            "body": len(body),
            **{section.name: section.size for section in sections},
        },
    }
    if "manifest_digest" in manifest_obj:
        raise ArchiveRefusal("MANIFEST_DIGEST_IS_NOT_AN_INPUT")
    manifest = canonical_bytes(manifest_obj)
    manifest_digest = digest_bytes(manifest)
    if manifest_digest.encode() in manifest:
        raise ArchiveRefusal("MANIFEST_DIGEST_IS_NOT_AN_INPUT")
    return ArchiveEnvelope(
        body=body,
        body_digest=body_digest,
        manifest=manifest,
        manifest_digest=manifest_digest,
        header_hash=header_hash,
        anchor=anchor,
        sections=sections,
        inventory=tuple(inventory),
    )


def _section(name: str, value: Any) -> Section:
    content = canonical_bytes(value)
    return Section(
        name=name,
        digest=digest_bytes(content),
        size=len(content),
        content=content,
    )


def _header_dict(block: Block) -> dict[str, Any]:
    header = block.header
    return {
        "index": header.index,
        "previous_hash": header.previous_hash,
        "timestamp": header.timestamp.isoformat(),
        "merkle_root": header.merkle_root,
        "generator_id": header.generator_id,
        "weighted_performance_sum": header.weighted_performance_sum,
        "threshold": header.threshold,
    }


def _transaction_dict(tx: Transaction) -> dict[str, Any]:
    tx_type = tx.tx_type.value if hasattr(tx.tx_type, "value") else str(tx.tx_type)
    return {
        "id": tx.id,
        "tx_type": tx_type,
        "domain_id": tx.domain_id,
        "peer_id": tx.peer_id,
        "payload": tx.payload,
        "timestamp": tx.timestamp.isoformat(),
    }


def _inventory(
    transactions: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
    retries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for tx in transactions:
        items.append(
            {"kind": "transaction", "id": tx["id"], "won": None, "attempt": None}
        )
    for record in candidates:
        items.append(
            {
                "kind": "candidate",
                "id": record["record_id"],
                "won": record["won"],
                "attempt": record["attempt"],
            }
        )
    for record in retries:
        items.append(
            {
                "kind": "retry",
                "id": record["record_id"],
                "won": record["won"],
                "attempt": record["attempt"],
            }
        )
    for seq, item in enumerate(items):
        item["seq"] = seq
    return items


def _normalize_record(raw: Mapping[str, Any], *, kind: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ArchiveRefusal("RECORD_MUST_BE_A_MAPPING")
    missing = [field for field in _RECORD_FIELDS if field not in raw]
    if missing:
        raise ArchiveRefusal("RECORD_FIELDS_MISSING: " + ",".join(missing))
    record_id = raw["record_id"]
    candidate_id = raw["candidate_id"]
    domain_id = raw["domain_id"]
    peer_id = raw["peer_id"]
    strings = (record_id, candidate_id, domain_id, peer_id)
    if not all(isinstance(value, str) and value for value in strings):
        raise ArchiveRefusal("RECORD_STRING_REQUIRED")
    attempt = raw["attempt"]
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ArchiveRefusal("ATTEMPT_MUST_BE_AN_INTEGER")
    if kind == "retry" and attempt < 2:
        raise ArchiveRefusal("RETRY_ATTEMPT_MUST_BE_AT_LEAST_2")
    if not isinstance(raw["won"], bool):
        raise ArchiveRefusal("WON_MUST_BE_A_BOOLEAN")
    performance = raw["performance"]
    if isinstance(performance, bool) or not isinstance(performance, (int, float)):
        raise ArchiveRefusal("PERFORMANCE_MUST_BE_A_NUMBER")
    parameters = raw.get("parameters") or {}
    metrics = raw.get("metrics") or {}
    if not isinstance(parameters, dict) or not isinstance(metrics, dict):
        raise ArchiveRefusal("RECORD_MAPPING_EXPECTED")
    record = {
        "record_id": record_id,
        "candidate_id": candidate_id,
        "attempt": attempt,
        "won": raw["won"],
        "domain_id": domain_id,
        "peer_id": peer_id,
        "performance": performance,
        "parameters": parameters,
        "metrics": metrics,
        "kind": kind,
    }
    _reject_non_finite(record)
    return record


def _reject_duplicate_records(
    candidates: Sequence[Mapping[str, Any]],
    retries: Sequence[Mapping[str, Any]],
) -> None:
    seen: set[str] = set()
    for record in (*candidates, *retries):
        record_id = str(record["record_id"])
        if record_id in seen:
            raise ArchiveRefusal(f"DUPLICATE_RECORD: {record_id}")
        seen.add(record_id)


def _reject_non_finite(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, str):
        return
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ArchiveRefusal(f"NON_FINITE: {path}")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ArchiveRefusal(f"NON_STRING_KEY: {path}")
            _reject_non_finite(item, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _reject_non_finite(item, f"{path}[{index}]")
        return
    raise ArchiveRefusal(f"UNSUPPORTED_TYPE: {path} {type(value).__name__}")
