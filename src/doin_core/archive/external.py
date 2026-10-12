"""External-payload archive mode: canonical body bytes first, chain reference second.

Pure serialization and verification, no I/O. The order a publisher must follow
lives in doin-node: PUT the body and manifest bytes to a content-addressed
store, GET them back exactly, compare digests, and only then submit the
reference transaction. This module defines what those bytes and that
reference are, and how a reader refuses anything that does not match.

Three identities, never substitutes for each other, none an input of its own
computation:

* ``body_digest``     = SHA-256 of the canonical body bytes;
* ``manifest_digest`` = SHA-256 of the canonical manifest bytes (the manifest
  names ``body_digest``; the body names neither digest);
* the block hash      = the existing header hash. The reference transaction id
  is bound to the payload by ``Transaction.compute_id`` and the header binds
  transaction ids through its merkle root, so the header commits to the
  reference without the body ever containing a block hash.

``full_payload`` mode keeps the complete body inside the transaction. A reader
rebuilds the identical canonical bytes from it, so both modes resolve to the
same body bytes and the same digests. No consensus rule, signature or block
validation is removed or replaced by this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from doin_core.archive.body import ArchiveRefusal, canonical_bytes, digest_bytes
from doin_core.models.transaction import Transaction, TransactionType

EXTERNAL_BODY_SCHEMA = "doin.external_payload_body.v1"
EXTERNAL_MANIFEST_SCHEMA = "doin.external_payload_manifest.v1"
REFERENCE_SCHEMA = "doin.external_payload_ref.v1"
MODES = ("external_payload", "full_payload")
LOCATOR_SCHEME = "doin-cas://"
REFERENCE_TX_TYPE = TransactionType.CANDIDATE_EVALUATED

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_STORE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SCHEMA_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_BODY_KEYS = frozenset({"schema", "domain_id", "producer_peer_id", "payload_schema", "payload"})
_MANIFEST_KEYS = frozenset(
    {"schema", "body_digest", "body_size", "body_schema", "payload_schema", "domain_id"}
)
_REF_KEYS = frozenset(
    {
        "reference_schema",
        "archive_mode",
        "body_digest",
        "manifest_digest",
        "body_size",
        "payload_schema",
        "domain_id",
        "locator",
    }
)


@dataclass(frozen=True)
class ExternalBody:
    """Canonical body and manifest bytes with the digests computed from them."""

    body: bytes
    body_digest: str
    manifest: bytes
    manifest_digest: str
    domain_id: str
    payload_schema: str
    payload: Any


def build_external_body(
    *,
    domain_id: str,
    producer_peer_id: str,
    payload_schema: str,
    payload: Mapping[str, Any],
) -> ExternalBody:
    """Serialize one domain payload. Non-finite numbers are refused."""
    for name, value in (
        ("domain_id", domain_id),
        ("producer_peer_id", producer_peer_id),
        ("payload_schema", payload_schema),
    ):
        if not isinstance(value, str) or not value:
            raise ArchiveRefusal(f"FIELD_REQUIRED: {name}")
    if not _SCHEMA_ID.match(payload_schema):
        raise ArchiveRefusal("PAYLOAD_SCHEMA")
    if not isinstance(payload, Mapping):
        raise ArchiveRefusal("PAYLOAD_MUST_BE_A_MAPPING")
    body_obj = {
        "schema": EXTERNAL_BODY_SCHEMA,
        "domain_id": domain_id,
        "producer_peer_id": producer_peer_id,
        "payload_schema": payload_schema,
        "payload": dict(payload),
    }
    return _from_body_obj(body_obj)


def _from_body_obj(body_obj: Mapping[str, Any]) -> ExternalBody:
    body = canonical_bytes(body_obj)
    body_digest = digest_bytes(body)
    manifest_obj = _manifest_obj(body_obj, body, body_digest)
    manifest = canonical_bytes(manifest_obj)
    manifest_digest = digest_bytes(manifest)
    if body_digest == manifest_digest:  # pragma: no cover - SHA-256 collision
        raise ArchiveRefusal("DIGEST_IDENTITY")
    return ExternalBody(
        body=body,
        body_digest=body_digest,
        manifest=manifest,
        manifest_digest=manifest_digest,
        domain_id=body_obj["domain_id"],
        payload_schema=body_obj["payload_schema"],
        payload=body_obj["payload"],
    )


def _manifest_obj(body_obj: Mapping[str, Any], body: bytes, body_digest: str) -> dict[str, Any]:
    return {
        "schema": EXTERNAL_MANIFEST_SCHEMA,
        "body_digest": body_digest,
        "body_size": len(body),
        "body_schema": body_obj["schema"],
        "payload_schema": body_obj["payload_schema"],
        "domain_id": body_obj["domain_id"],
    }


def make_locator(store_id: str, digest: str) -> str:
    if not isinstance(store_id, str) or not _STORE_ID.match(store_id):
        raise ArchiveRefusal("LOCATOR_STORE_ID")
    if not isinstance(digest, str) or not _HEX64.match(digest):
        raise ArchiveRefusal("NOT_A_SHA256")
    return f"{LOCATOR_SCHEME}{store_id}/sha256/{digest}"


def parse_locator(locator: Any) -> tuple[str, str]:
    """Return ``(store_id, digest)``. Anything else is LOCATOR refused."""
    if not isinstance(locator, str) or not locator.startswith(LOCATOR_SCHEME):
        raise ArchiveRefusal("LOCATOR")
    rest = locator[len(LOCATOR_SCHEME):]
    parts = rest.split("/")
    if len(parts) != 3 or parts[1] != "sha256":
        raise ArchiveRefusal("LOCATOR")
    store_id, _, digest = parts
    if not _STORE_ID.match(store_id) or not _HEX64.match(digest):
        raise ArchiveRefusal("LOCATOR")
    return store_id, digest


def reference_payload(
    external: ExternalBody,
    *,
    mode: str,
    store_id: str | None = None,
) -> dict[str, Any]:
    """The transaction payload that commits to ``external``.

    ``external_payload`` carries digests and a locator. ``full_payload`` carries
    the same digests plus the complete body object, and no locator.
    """
    if mode not in MODES:
        raise ArchiveRefusal("ARCHIVE_MODE")
    ref: dict[str, Any] = {
        "reference_schema": REFERENCE_SCHEMA,
        "archive_mode": mode,
        "body_digest": external.body_digest,
        "manifest_digest": external.manifest_digest,
        "body_size": len(external.body),
        "payload_schema": external.payload_schema,
        "domain_id": external.domain_id,
        "locator": None,
    }
    if mode == "external_payload":
        if store_id is None:
            raise ArchiveRefusal("LOCATOR_STORE_ID")
        ref["locator"] = make_locator(store_id, external.body_digest)
    else:
        ref["body"] = _parse(external.body)
    return check_reference_payload(ref)


def check_reference_payload(payload: Any) -> dict[str, Any]:
    """Structural check of a reference payload. Returns it unchanged."""
    if not isinstance(payload, Mapping):
        raise ArchiveRefusal("REFERENCE")
    mode = payload.get("archive_mode")
    expected = set(_REF_KEYS) | ({"body"} if mode == "full_payload" else set())
    if set(payload) != expected:
        raise ArchiveRefusal("REFERENCE_KEYS")
    if payload["reference_schema"] != REFERENCE_SCHEMA:
        raise ArchiveRefusal("REFERENCE_SCHEMA")
    if mode not in MODES:
        raise ArchiveRefusal("ARCHIVE_MODE")
    for name in ("body_digest", "manifest_digest"):
        if not isinstance(payload[name], str) or not _HEX64.match(payload[name]):
            raise ArchiveRefusal("NOT_A_SHA256")
    if payload["body_digest"] == payload["manifest_digest"]:
        raise ArchiveRefusal("DIGEST_IDENTITY")
    size = payload["body_size"]
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ArchiveRefusal("SIZE_MISMATCH")
    for name in ("payload_schema", "domain_id"):
        if not isinstance(payload[name], str) or not payload[name]:
            raise ArchiveRefusal("REFERENCE")
    if mode == "external_payload":
        _store, digest = parse_locator(payload["locator"])
        if digest != payload["body_digest"]:
            raise ArchiveRefusal("LOCATOR_DIGEST_MISMATCH")
    elif payload["locator"] is not None:
        raise ArchiveRefusal("LOCATOR")
    return dict(payload)


@dataclass(frozen=True)
class ResolvedBody:
    """Bytes re-read and checked against a reference. Not a chain verdict."""

    body: bytes
    body_digest: str
    manifest: bytes
    manifest_digest: str
    domain_id: str
    producer_peer_id: str
    payload_schema: str
    payload: Any
    archive_mode: str


def verify_external_bytes(
    reference: Mapping[str, Any],
    *,
    body: bytes,
    manifest: bytes,
) -> ResolvedBody:
    """Check fetched bytes against a reference: digests, sizes, schemas and links."""
    ref = check_reference_payload(reference)
    if not isinstance(body, bytes) or not isinstance(manifest, bytes):
        raise ArchiveRefusal("DIGEST_REQUIRES_BYTES")
    if digest_bytes(body) != ref["body_digest"]:
        raise ArchiveRefusal("DIGEST_MISMATCH: body")
    if digest_bytes(manifest) != ref["manifest_digest"]:
        raise ArchiveRefusal("DIGEST_MISMATCH: manifest")
    if len(body) != ref["body_size"]:
        raise ArchiveRefusal("SIZE_MISMATCH")
    body_obj = _parse(body)
    manifest_obj = _parse(manifest)
    if not isinstance(body_obj, dict) or set(body_obj) != _BODY_KEYS:
        raise ArchiveRefusal("BODY_SCHEMA")
    if body_obj["schema"] != EXTERNAL_BODY_SCHEMA:
        raise ArchiveRefusal("BODY_SCHEMA")
    if not isinstance(manifest_obj, dict) or set(manifest_obj) != _MANIFEST_KEYS:
        raise ArchiveRefusal("MANIFEST_SCHEMA")
    if manifest_obj != _manifest_obj(body_obj, body, ref["body_digest"]):
        raise ArchiveRefusal("MANIFEST_LINK")
    if body_obj["payload_schema"] != ref["payload_schema"]:
        raise ArchiveRefusal("PAYLOAD_SCHEMA")
    if body_obj["domain_id"] != ref["domain_id"]:
        raise ArchiveRefusal("DOMAIN_MISMATCH")
    return ResolvedBody(
        body=body,
        body_digest=ref["body_digest"],
        manifest=manifest,
        manifest_digest=ref["manifest_digest"],
        domain_id=body_obj["domain_id"],
        producer_peer_id=body_obj["producer_peer_id"],
        payload_schema=body_obj["payload_schema"],
        payload=body_obj["payload"],
        archive_mode=ref["archive_mode"],
    )


def resolve_full_payload(reference: Mapping[str, Any]) -> ResolvedBody:
    """Rebuild canonical bytes from a full-payload reference and verify them."""
    ref = check_reference_payload(reference)
    if ref["archive_mode"] != "full_payload":
        raise ArchiveRefusal("ARCHIVE_MODE")
    body_obj = ref["body"]
    if not isinstance(body_obj, Mapping) or set(body_obj) != _BODY_KEYS:
        raise ArchiveRefusal("BODY_SCHEMA")
    rebuilt = _from_body_obj(dict(body_obj))
    if rebuilt.body_digest != ref["body_digest"]:
        raise ArchiveRefusal("DIGEST_MISMATCH: body")
    return verify_external_bytes(ref, body=rebuilt.body, manifest=rebuilt.manifest)


def is_reference_transaction(tx: Transaction) -> bool:
    payload = getattr(tx, "payload", None)
    return isinstance(payload, Mapping) and payload.get("reference_schema") == REFERENCE_SCHEMA


def check_reference_transaction(tx: Transaction) -> dict[str, Any]:
    """A reference transaction must have the candidate type, a bound id and a valid payload.

    This is an additional check. It does not replace chain, merkle or signature validation.
    """
    if not isinstance(tx, Transaction):
        raise ArchiveRefusal("TRANSACTION_REQUIRED")
    if tx.tx_type != REFERENCE_TX_TYPE:
        raise ArchiveRefusal("TX_TYPE")
    if tx.id != tx.compute_id():
        raise ArchiveRefusal("TX_ID_NOT_BOUND_TO_PAYLOAD")
    ref = check_reference_payload(tx.payload)
    if ref["domain_id"] != tx.domain_id:
        raise ArchiveRefusal("DOMAIN_MISMATCH")
    return ref


def _parse(data: bytes) -> Any:
    import json

    try:
        parsed = json.loads(data)
    except ValueError as exc:
        raise ArchiveRefusal("UNREADABLE") from exc
    if canonical_bytes(parsed) != data:
        raise ArchiveRefusal("NOT_CANONICAL")
    return parsed
