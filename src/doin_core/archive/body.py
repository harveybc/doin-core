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
DIGEST_IDENTITY = (
    "body_digest is the identity of the body bytes. "
    "manifest_digest is the identity of the manifest bytes. "
    "header_hash is the block header hash. "
    "The three are not substitutes, and a manifest digest is not a body digest."
)

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


@dataclass(frozen=True)
class VerifiedArchive:
    """Bytes re-read and checked. ``chain_verified`` is never set from a manifest claim."""

    body: bytes
    body_digest: str
    manifest: bytes
    manifest_digest: str
    header_hash: str | None
    anchor: str
    sections: tuple[Section, ...]
    inventory: tuple[dict[str, Any], ...]
    records: tuple[dict[str, Any], ...]
    chain_verified: bool = False


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
    if "parameters" not in raw or "metrics" not in raw:
        raise ArchiveRefusal("RECORD_FIELDS_MISSING: parameters,metrics")
    parameters = raw["parameters"]
    metrics = raw["metrics"]
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
    if "provenance" in raw:
        if not isinstance(raw["provenance"], dict):
            raise ArchiveRefusal("PROVENANCE")
        record["provenance"] = raw["provenance"]
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


_ANCHORED_SECTIONS = ("header", "transactions", "header_hash", "candidates", "retries")
_UNANCHORED_SECTIONS = ("candidates", "retries")
_MANIFEST_KEYS = {
    "schema",
    "anchor",
    "header_hash",
    "body_digest",
    "sections",
    "inventory",
    "counts",
    "sizes",
}
_INVENTORY_KEYS = {"kind", "id", "won", "attempt", "seq"}


def verify_archive_bytes(
    *,
    body: bytes,
    manifest: bytes,
    sections: Mapping[str, bytes],
) -> VerifiedArchive:
    """Rebuild an archive from bytes and refuse any broken hash, size, type or link.

    ``sections`` maps a section digest to the exact section bytes. The caller's
    in-memory section objects are not trusted.
    """
    if not isinstance(body, bytes) or not isinstance(manifest, bytes):
        raise ArchiveRefusal("DIGEST_REQUIRES_BYTES")
    if not isinstance(sections, Mapping):
        raise ArchiveRefusal("SECTION")
    body_digest = digest_bytes(body)
    manifest_digest = digest_bytes(manifest)
    body_obj = _canonical_object(body)
    manifest_obj = _canonical_object(manifest)
    if set(manifest_obj) != _MANIFEST_KEYS:
        raise ArchiveRefusal("MANIFEST_SCHEMA")
    if manifest_obj.get("schema") != MANIFEST_SCHEMA:
        raise ArchiveRefusal("MANIFEST_SCHEMA")
    if manifest_obj.get("body_digest") != body_digest:
        raise ArchiveRefusal("DIGEST_MISMATCH")
    anchor = manifest_obj.get("anchor")
    if anchor == "ANCHORED":
        expected_names = _ANCHORED_SECTIONS
        if set(body_obj) != {"schema", "header", "transactions", "header_hash"}:
            raise ArchiveRefusal("BODY_SCHEMA")
        if body_obj.get("schema") != BODY_SCHEMA:
            raise ArchiveRefusal("BODY_SCHEMA")
    elif anchor == "UNANCHORED":
        expected_names = _UNANCHORED_SECTIONS
        if set(body_obj) != {"schema", "anchor", "candidates", "retries"}:
            raise ArchiveRefusal("BODY_SCHEMA")
        if body_obj.get("schema") != UNANCHORED_SCHEMA or body_obj.get("anchor") != "UNANCHORED":
            raise ArchiveRefusal("BODY_SCHEMA")
    else:
        raise ArchiveRefusal("ANCHOR")
    header_hash = _linked_header(anchor, body_obj, manifest_obj)
    declared = manifest_obj.get("sections")
    if not isinstance(declared, list):
        raise ArchiveRefusal("SECTION")
    names = tuple(item.get("name") if isinstance(item, dict) else None for item in declared)
    if names != expected_names:
        raise ArchiveRefusal("SECTION_ORDER")
    rebuilt: list[Section] = []
    parsed: dict[str, Any] = {}
    for item in declared:
        content = _checked_section(item, sections)
        parsed[item["name"]] = _canonical_object(content)
        rebuilt.append(
            Section(
                name=item["name"],
                digest=item["digest"],
                size=item["size"],
                content=content,
            )
        )
    _link_body(anchor, body_obj, parsed)
    candidates = _checked_records(parsed["candidates"], kind="candidate")
    retries = _checked_records(parsed["retries"], kind="retry")
    _reject_duplicate_records(candidates, retries)
    transaction_ids: list[str] = []
    if anchor == "ANCHORED":
        txs = body_obj.get("transactions")
        if not isinstance(txs, list):
            raise ArchiveRefusal("BODY_SCHEMA")
        for tx in txs:
            if not isinstance(tx, dict) or not isinstance(tx.get("id"), str) or not tx["id"]:
                raise ArchiveRefusal("BODY_SCHEMA")
            transaction_ids.append(tx["id"])
    inventory = _checked_inventory(
        manifest_obj,
        transaction_ids=transaction_ids,
        candidates=candidates,
        retries=retries,
    )
    sizes = manifest_obj.get("sizes")
    if not isinstance(sizes, dict) or sizes.get("body") != len(body):
        raise ArchiveRefusal("SIZE_MISMATCH")
    for item in declared:
        if sizes.get(item["name"]) != item["size"]:
            raise ArchiveRefusal("SIZE_MISMATCH")
    return VerifiedArchive(
        body=body,
        body_digest=body_digest,
        manifest=manifest,
        manifest_digest=manifest_digest,
        header_hash=header_hash,
        anchor=anchor,
        sections=tuple(rebuilt),
        inventory=tuple(inventory),
        records=tuple(candidates + retries),
        chain_verified=False,
    )


def verify_envelope(envelope: ArchiveEnvelope) -> VerifiedArchive:
    """Validate an envelope's own bytes. A section whose content was replaced fails."""
    if not isinstance(envelope, ArchiveEnvelope):
        raise ArchiveRefusal("ENVELOPE_REQUIRED")
    if digest_bytes(envelope.body) != envelope.body_digest:
        raise ArchiveRefusal("DIGEST_MISMATCH")
    if digest_bytes(envelope.manifest) != envelope.manifest_digest:
        raise ArchiveRefusal("DIGEST_MISMATCH")
    sections: dict[str, bytes] = {}
    for section in envelope.sections:
        if digest_bytes(section.content) != section.digest or len(section.content) != section.size:
            raise ArchiveRefusal("DIGEST_MISMATCH")
        previous = sections.get(section.digest)
        if previous is not None and previous != section.content:
            raise ArchiveRefusal("DIGEST_MISMATCH")
        sections[section.digest] = section.content
    verified = verify_archive_bytes(
        body=envelope.body,
        manifest=envelope.manifest,
        sections=sections,
    )
    if (
        verified.body_digest != envelope.body_digest
        or verified.manifest_digest != envelope.manifest_digest
        or verified.chain_verified
    ):
        raise ArchiveRefusal("DIGEST_MISMATCH")
    return verified


def _canonical_object(data: bytes) -> Any:
    try:
        parsed = json.loads(data)
    except ValueError as exc:
        raise ArchiveRefusal("UNREADABLE") from exc
    if canonical_bytes(parsed) != data:
        raise ArchiveRefusal("NOT_CANONICAL")
    return parsed


def _linked_header(anchor: str, body_obj: Mapping[str, Any], manifest_obj: Mapping[str, Any]) -> str | None:
    header_hash = manifest_obj.get("header_hash")
    if anchor == "UNANCHORED":
        if header_hash is not None or "header_hash" in body_obj:
            raise ArchiveRefusal("HEADER_LINK")
        return None
    if not isinstance(header_hash, str) or len(header_hash) != 64:
        raise ArchiveRefusal("HEADER_HASH_REQUIRED")
    if any(char not in "0123456789abcdef" for char in header_hash):
        raise ArchiveRefusal("HEADER_HASH_REQUIRED")
    if body_obj.get("header_hash") != header_hash:
        raise ArchiveRefusal("HEADER_LINK")
    return header_hash


def _checked_section(declared: Mapping[str, Any], sections: Mapping[str, bytes]) -> bytes:
    if set(declared) != {"name", "digest", "size"}:
        raise ArchiveRefusal("SECTION")
    digest = declared["digest"]
    size = declared["size"]
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ArchiveRefusal("NOT_A_SHA256")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ArchiveRefusal("SIZE_MISMATCH")
    if digest not in sections:
        raise ArchiveRefusal("MISSING")
    content = sections[digest]
    if not isinstance(content, bytes):
        raise ArchiveRefusal("DIGEST_REQUIRES_BYTES")
    if len(content) != size or digest_bytes(content) != digest:
        raise ArchiveRefusal("DIGEST_MISMATCH")
    return content


def _link_body(anchor: str, body_obj: Mapping[str, Any], parsed: Mapping[str, Any]) -> None:
    if anchor == "ANCHORED":
        if parsed["header"] != body_obj["header"]:
            raise ArchiveRefusal("HEADER_LINK")
        if parsed["transactions"] != body_obj["transactions"]:
            raise ArchiveRefusal("HEADER_LINK")
        if parsed["header_hash"] != body_obj["header_hash"]:
            raise ArchiveRefusal("HEADER_LINK")
        return
    if parsed["candidates"] != body_obj["candidates"] or parsed["retries"] != body_obj["retries"]:
        raise ArchiveRefusal("HEADER_LINK")


def _checked_records(raw_records: Any, *, kind: str) -> list[dict[str, Any]]:
    if not isinstance(raw_records, list):
        raise ArchiveRefusal("RECORD_LIST")
    checked: list[dict[str, Any]] = []
    for raw in raw_records:
        if not isinstance(raw, Mapping):
            raise ArchiveRefusal("RECORD_MUST_BE_A_MAPPING")
        if raw.get("kind") != kind:
            raise ArchiveRefusal("RECORD_KIND_MISMATCH")
        normalized = _normalize_record(raw, kind=kind)
        if normalized["parameters"] != raw["parameters"] or normalized["metrics"] != raw["metrics"]:
            raise ArchiveRefusal("RECORD_LINK")
        checked.append(dict(raw))
    return checked


def _checked_inventory(
    manifest_obj: Mapping[str, Any],
    *,
    transaction_ids: Sequence[str],
    candidates: Sequence[Mapping[str, Any]],
    retries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    inventory = manifest_obj.get("inventory")
    counts = manifest_obj.get("counts")
    if not isinstance(inventory, list) or not isinstance(counts, dict):
        raise ArchiveRefusal("INVENTORY")
    expected_counts = {
        "transactions": len(transaction_ids),
        "candidates": len(candidates),
        "retries": len(retries),
    }
    if counts != expected_counts:
        raise ArchiveRefusal("INVENTORY_COUNTS")
    expected: list[tuple[Any, ...]] = [
        ("transaction", tx_id, None, None) for tx_id in transaction_ids
    ]
    expected.extend(
        ("candidate", record["record_id"], record["won"], record["attempt"])
        for record in candidates
    )
    expected.extend(
        ("retry", record["record_id"], record["won"], record["attempt"])
        for record in retries
    )
    if len(inventory) != len(expected):
        raise ArchiveRefusal("INVENTORY_LINK")
    checked: list[dict[str, Any]] = []
    for seq, (item, wanted) in enumerate(zip(inventory, expected)):
        if not isinstance(item, dict) or set(item) != _INVENTORY_KEYS:
            raise ArchiveRefusal("INVENTORY_LINK")
        if item.get("seq") != seq:
            raise ArchiveRefusal("INVENTORY_ORDER")
        got = (item.get("kind"), item.get("id"), item.get("won"), item.get("attempt"))
        if got != wanted:
            raise ArchiveRefusal("INVENTORY_LINK")
        checked.append(dict(item))
    return checked
