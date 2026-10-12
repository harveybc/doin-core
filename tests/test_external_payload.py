"""External-payload archive mode: body first, reference second, three distinct hashes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from doin_core.archive import ArchiveRefusal
from doin_core.archive.external import (
    EXTERNAL_BODY_SCHEMA,
    EXTERNAL_MANIFEST_SCHEMA,
    REFERENCE_SCHEMA,
    build_external_body,
    check_reference_payload,
    check_reference_transaction,
    is_reference_transaction,
    make_locator,
    parse_locator,
    reference_payload,
    resolve_full_payload,
    verify_external_bytes,
)
from doin_core.crypto.hashing import compute_merkle_root
from doin_core.models.block import Block, BlockHeader
from doin_core.models.transaction import Transaction, TransactionType

PAYLOAD = {
    "experiment": "i6n-test",
    "candidates": [{"id": "a", "fitness": 0.5, "won": False}, {"id": "b", "fitness": None}],
    "rows": [{"n": 3, "sum_abs_error": 0.25}],
}


def _body():
    return build_external_body(
        domain_id="dom",
        producer_peer_id="peer-1",
        payload_schema="i6n.archive.round.v1",
        payload=PAYLOAD,
    )


def _tx(reference, ts=datetime(2026, 10, 11, tzinfo=timezone.utc)):
    return Transaction(
        tx_type=TransactionType.CANDIDATE_EVALUATED,
        domain_id="dom",
        peer_id="peer-1",
        payload=reference,
        timestamp=ts,
    )


def test_body_manifest_and_block_hash_are_distinct_and_not_circular():
    body = _body()
    assert body.body_digest == hashlib.sha256(body.body).hexdigest()
    assert body.manifest_digest == hashlib.sha256(body.manifest).hexdigest()
    assert body.body_digest != body.manifest_digest
    parsed_body = json.loads(body.body)
    parsed_manifest = json.loads(body.manifest)
    assert parsed_body["schema"] == EXTERNAL_BODY_SCHEMA
    assert parsed_manifest["schema"] == EXTERNAL_MANIFEST_SCHEMA
    # The body does not contain its own digest, the manifest digest or any block hash.
    assert body.body_digest.encode() not in body.body
    assert body.manifest_digest.encode() not in body.body
    assert body.manifest_digest.encode() not in body.manifest
    assert parsed_manifest["body_digest"] == body.body_digest
    ref = reference_payload(body, mode="external_payload", store_id="cas")
    tx = _tx(ref)
    header = BlockHeader(
        index=1,
        previous_hash=Block.genesis().hash,
        merkle_root=compute_merkle_root([tx.id]),
        generator_id="peer-1",
        weighted_performance_sum=1.0,
        threshold=0.5,
    )
    block = Block(header=header, transactions=[tx])
    assert block.hash not in (body.body_digest, body.manifest_digest)
    assert block.hash.encode() not in body.body


def test_body_is_canonical_and_deterministic():
    assert _body().body == _body().body
    with pytest.raises(ArchiveRefusal):
        build_external_body(domain_id="d", producer_peer_id="p", payload_schema="s",
                            payload={"x": float("nan")})


def test_locator_round_trip_and_refusals():
    digest = "a" * 64
    loc = make_locator("cas_store", digest)
    assert loc == "doin-cas://cas_store/sha256/" + digest
    assert parse_locator(loc) == ("cas_store", digest)
    for bad in ("http://x/sha256/" + digest, "doin-cas://cas/sha1/" + digest,
                "doin-cas://cas/sha256/xyz", "doin-cas:///sha256/" + digest):
        with pytest.raises(ArchiveRefusal):
            parse_locator(bad)


def test_external_reference_carries_no_body_and_full_carries_it():
    body = _body()
    ext = reference_payload(body, mode="external_payload", store_id="cas")
    assert ext["reference_schema"] == REFERENCE_SCHEMA
    assert ext["archive_mode"] == "external_payload"
    assert "body" not in ext
    assert parse_locator(ext["locator"]) == ("cas", body.body_digest)
    full = reference_payload(body, mode="full_payload")
    assert full["archive_mode"] == "full_payload"
    assert full["locator"] is None
    assert full["body"] == json.loads(body.body)
    assert check_reference_payload(ext) == ext
    assert check_reference_payload(full) == full
    with pytest.raises(ArchiveRefusal):
        reference_payload(body, mode="external_payload")  # store id required


def test_full_payload_resolves_to_the_same_bytes_as_external():
    body = _body()
    full = reference_payload(body, mode="full_payload")
    resolved = resolve_full_payload(json.loads(json.dumps(full)))
    assert resolved.body == body.body
    assert resolved.manifest == body.manifest
    assert resolved.payload == PAYLOAD
    ext = reference_payload(body, mode="external_payload", store_id="cas")
    verified = verify_external_bytes(ext, body=body.body, manifest=body.manifest)
    assert verified.body == resolved.body
    assert verified.payload == resolved.payload


def test_wrong_bytes_digest_and_locator_are_refused():
    body = _body()
    ext = reference_payload(body, mode="external_payload", store_id="cas")
    with pytest.raises(ArchiveRefusal, match="DIGEST_MISMATCH"):
        verify_external_bytes(ext, body=body.body + b" ", manifest=body.manifest)
    with pytest.raises(ArchiveRefusal, match="DIGEST_MISMATCH"):
        verify_external_bytes(ext, body=body.body, manifest=body.manifest + b" ")
    wrong_digest = dict(ext, body_digest="b" * 64)
    with pytest.raises(ArchiveRefusal):
        verify_external_bytes(wrong_digest, body=body.body, manifest=body.manifest)
    wrong_locator = dict(ext, locator=make_locator("cas", "c" * 64))
    with pytest.raises(ArchiveRefusal, match="LOCATOR"):
        check_reference_payload(wrong_locator)
    other = build_external_body(domain_id="dom", producer_peer_id="peer-1",
                                payload_schema="i6n.archive.round.v1", payload={"x": 1})
    with pytest.raises(ArchiveRefusal):
        verify_external_bytes(ext, body=other.body, manifest=other.manifest)
    tampered_full = reference_payload(body, mode="full_payload")
    tampered_full["body"] = dict(tampered_full["body"], producer_peer_id="peer-2")
    with pytest.raises(ArchiveRefusal, match="DIGEST_MISMATCH"):
        resolve_full_payload(tampered_full)


def test_reference_transaction_binds_payload_to_tx_id():
    body = _body()
    ext = reference_payload(body, mode="external_payload", store_id="cas")
    tx = _tx(ext)
    assert is_reference_transaction(tx)
    assert check_reference_transaction(tx)["body_digest"] == body.body_digest
    forged = tx.model_copy(update={"payload": dict(ext, body_digest="d" * 64)})
    with pytest.raises(ArchiveRefusal, match="TX_ID"):
        check_reference_transaction(forged)
    plain = Transaction(tx_type=TransactionType.CANDIDATE_EVALUATED, domain_id="d",
                        peer_id="p", payload={"fitness": 1.0})
    assert not is_reference_transaction(plain)
    wrong_type = Transaction(tx_type=TransactionType.TASK_CREATED, domain_id="dom",
                             peer_id="p", payload=ext)
    with pytest.raises(ArchiveRefusal, match="TX_TYPE"):
        check_reference_transaction(wrong_type)


def test_reference_payload_shape_is_strict():
    body = _body()
    ext = reference_payload(body, mode="external_payload", store_id="cas")
    for key in ("body_digest", "manifest_digest", "body_size", "payload_schema", "locator"):
        broken = dict(ext)
        broken.pop(key)
        with pytest.raises(ArchiveRefusal):
            check_reference_payload(broken)
    with pytest.raises(ArchiveRefusal):
        check_reference_payload(dict(ext, extra=1))
    with pytest.raises(ArchiveRefusal):
        check_reference_payload(dict(ext, archive_mode="other"))
    with pytest.raises(ArchiveRefusal):
        check_reference_payload(dict(ext, body={"x": 1}))
    with pytest.raises(ArchiveRefusal):
        check_reference_payload(dict(ext, manifest_digest=ext["body_digest"]))
