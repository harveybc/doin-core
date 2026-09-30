"""Deterministic shadow serialization of an existing block body.

The body is the block the caller already holds. It is not replaced with an
empty block, and header validation, rewards, difficulty and merkle rules are
not applied here. Body digest, manifest digest and header hash are three
different values. Neither document contains its own digest.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone

import pytest

from doin_core.archive.body import (
    DIGEST_IDENTITY,
    MANIFEST_SCHEMA,
    UNANCHORED_SCHEMA,
    ArchiveRefusal,
    build_archive,
    canonical_bytes,
    digest_bytes,
    verify_archive_bytes,
    verify_envelope,
)
from doin_core.crypto.hashing import compute_merkle_root
from doin_core.models import Block, BlockHeader, Transaction, TransactionType

TS = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def _tx(tx_type: TransactionType, payload: dict, *, tx_id: str = "") -> Transaction:
    kwargs: dict = {
        "tx_type": tx_type,
        "domain_id": "fixture-domain",
        "peer_id": "peer-fixture",
        "payload": payload,
        "timestamp": TS,
    }
    if tx_id:
        kwargs["id"] = tx_id
    return Transaction(**kwargs)


def _block(transactions: list[Transaction] | None = None) -> Block:
    txs = transactions if transactions is not None else [
        _tx(
            TransactionType.OPTIMAE_ACCEPTED,
            {
                "optimae_id": "opt-win",
                "parameters": {"w": 1},
                "verified_performance": 0.9,
            },
        )
    ]
    header = BlockHeader(
        index=3,
        previous_hash="ab" * 32,
        timestamp=TS,
        merkle_root=compute_merkle_root([tx.id for tx in txs]),
        generator_id="node-fixture",
        weighted_performance_sum=1.5,
        threshold=0.5,
    )
    return Block(header=header, transactions=txs)


def _candidate(record_id: str, *, won: bool, attempt: int, performance: float) -> dict:
    return {
        "record_id": record_id,
        "candidate_id": "cand-lose" if not won else "cand-win",
        "attempt": attempt,
        "won": won,
        "domain_id": "fixture-domain",
        "peer_id": "peer-fixture",
        "performance": performance,
        "parameters": {"w": performance},
        "metrics": {"split": "val"},
    }


def _archive(block: Block | None = None):
    block = _block() if block is None else block
    return build_archive(
        block=block,
        candidates=[
            _candidate("rec-lose-1", won=False, attempt=1, performance=0.2),
            _candidate("rec-win-1", won=True, attempt=1, performance=0.9),
        ],
        retries=[
            _candidate("rec-lose-2", won=False, attempt=2, performance=0.25),
        ],
    )


class TestBlockBody:
    def test_serializes_existing_block_not_an_empty_substitute(self) -> None:
        block = _block()
        env = _archive(block)
        parsed = json.loads(env.body)
        assert parsed["schema"] == "doin.block_body.v1"
        assert set(parsed) == {"schema", "header", "transactions", "header_hash"}
        assert [tx["id"] for tx in parsed["transactions"]] == [
            tx.id for tx in block.transactions
        ]
        assert parsed["transactions"]
        assert parsed["header"]["index"] == block.header.index
        assert parsed["header"]["merkle_root"] == block.header.merkle_root
        assert "hash" not in parsed["header"]

    def test_preserves_caller_transaction_id(self) -> None:
        custom = "cd" * 32
        tx = _tx(
            TransactionType.OPTIMAE_ACCEPTED,
            {"optimae_id": "opt-win"},
            tx_id=custom,
        )
        assert tx.compute_id() != custom
        env = build_archive(block=_block([tx]), candidates=[], retries=[])
        parsed = json.loads(env.body)
        assert parsed["transactions"][0]["id"] == custom

    def test_does_not_recompute_a_mismatched_merkle_root(self) -> None:
        block = _block()
        block.header.merkle_root = "ef" * 32
        env = build_archive(block=block, candidates=[], retries=[])
        assert json.loads(env.body)["header"]["merkle_root"] == "ef" * 32

    def test_deterministic_bytes_and_exact_digest(self) -> None:
        first = _archive()
        second = _archive()
        assert first.body == second.body
        assert first.manifest == second.manifest
        assert first.body_digest == digest_bytes(first.body)
        assert first.body_digest == hashlib.sha256(first.body).hexdigest()
        assert first.manifest_digest == digest_bytes(first.manifest)

    def test_three_digests_differ_and_are_not_self_inputs(self) -> None:
        block = _block()
        env = _archive(block)
        body = json.loads(env.body)
        manifest = json.loads(env.manifest)
        assert body["header_hash"] == block.hash == block.header.compute_hash()
        assert env.header_hash == block.hash
        assert env.body_digest != block.hash
        assert env.manifest_digest != env.body_digest
        assert env.manifest_digest != block.hash
        assert "body_digest" not in body
        assert "manifest_digest" not in body
        assert "manifest_digest" not in manifest
        assert manifest["body_digest"] == env.body_digest
        assert manifest["header_hash"] == block.hash
        assert env.body_digest.encode() not in env.body
        assert env.manifest_digest.encode() not in env.manifest

    def test_transaction_order_is_significant(self) -> None:
        first = _tx(
            TransactionType.CANDIDATE_EVALUATED,
            {"candidate_id": "a", "fitness": 0.1},
        )
        second = _tx(TransactionType.OPTIMAE_ACCEPTED, {"optimae_id": "b"})
        forward = build_archive(
            block=_block([first, second]),
            candidates=[],
            retries=[],
        )
        backward = build_archive(
            block=_block([second, first]),
            candidates=[],
            retries=[],
        )
        assert json.loads(forward.body)["transactions"][0]["id"] == first.id
        assert forward.body_digest != backward.body_digest

    def test_rejects_non_finite_numbers(self) -> None:
        block = _block()
        block.transactions[0].payload["verified_performance"] = math.nan
        with pytest.raises(ArchiveRefusal, match="NON_FINITE"):
            build_archive(block=block, candidates=[], retries=[])
        block = _block()
        block.header.threshold = math.inf
        with pytest.raises(ArchiveRefusal, match="NON_FINITE"):
            build_archive(block=block, candidates=[], retries=[])
        bad = _candidate("rec-nan", won=False, attempt=1, performance=math.nan)
        with pytest.raises(ArchiveRefusal, match="NON_FINITE"):
            build_archive(block=_block(), candidates=[bad], retries=[])


class TestManifest:
    def test_binds_sections_sizes_and_ordered_inventory(self) -> None:
        block = _block()
        env = _archive(block)
        manifest = json.loads(env.manifest)
        assert manifest["schema"] == MANIFEST_SCHEMA
        assert manifest["anchor"] == "ANCHORED"
        names = [section["name"] for section in manifest["sections"]]
        assert names == [
            "header",
            "transactions",
            "header_hash",
            "candidates",
            "retries",
        ]
        by_name = {section.name: section for section in env.sections}
        for declared in manifest["sections"]:
            section = by_name[declared["name"]]
            assert declared["digest"] == digest_bytes(section.content)
            assert declared["size"] == len(section.content)
            assert canonical_bytes(json.loads(section.content)) == section.content
        assert manifest["sizes"]["body"] == len(env.body)
        assert manifest["counts"] == {"transactions": 1, "candidates": 2, "retries": 1}
        inventory = manifest["inventory"]
        assert [item["seq"] for item in inventory] == list(range(len(inventory)))
        assert [item["id"] for item in inventory] == [
            block.transactions[0].id,
            "rec-lose-1",
            "rec-win-1",
            "rec-lose-2",
        ]
        assert [item["kind"] for item in inventory] == [
            "transaction",
            "candidate",
            "candidate",
            "retry",
        ]
        tx_rows = [item for item in inventory if item["kind"] == "transaction"]
        assert all(item["won"] is None for item in tx_rows)
        assert any(item["won"] is False for item in inventory)
        assert any(
            item["attempt"] == 2 and item["kind"] == "retry"
            for item in inventory
        )

    def test_unanchored_round_is_not_an_empty_block(self) -> None:
        lose = _candidate("rec-lose-1", won=False, attempt=1, performance=0.2)
        env = build_archive(block=None, candidates=[lose], retries=[])
        parsed = json.loads(env.body)
        manifest = json.loads(env.manifest)
        assert env.anchor == "UNANCHORED"
        assert env.header_hash is None
        assert parsed["schema"] == UNANCHORED_SCHEMA
        assert parsed["anchor"] == "UNANCHORED"
        assert "transactions" not in parsed
        assert "header" not in parsed
        assert "header_hash" not in parsed
        assert manifest["anchor"] == "UNANCHORED"
        assert manifest["header_hash"] is None
        assert manifest["counts"]["transactions"] == 0
        assert manifest["inventory"][0]["id"] == "rec-lose-1"
        assert manifest["inventory"][0]["won"] is False
        assert env.body_digest != env.manifest_digest

    def test_refuses_a_round_with_nothing_to_archive(self) -> None:
        with pytest.raises(ArchiveRefusal, match="EMPTY_ROUND"):
            build_archive(block=None, candidates=[], retries=[])

    def test_refuses_duplicate_record_identity(self) -> None:
        one = _candidate("same", won=False, attempt=1, performance=0.1)
        again = _candidate("same", won=False, attempt=2, performance=0.2)
        with pytest.raises(ArchiveRefusal, match="DUPLICATE_RECORD"):
            build_archive(block=_block(), candidates=[one], retries=[again])


class TestSharedVerification:
    """O03/AT02. Reconstruction reads stored bytes, not a caller's section objects."""

    def test_digest_identity_is_declared(self) -> None:
        assert "body_digest" in DIGEST_IDENTITY
        assert "manifest_digest" in DIGEST_IDENTITY
        assert "header_hash" in DIGEST_IDENTITY
        assert "not substitutes" in DIGEST_IDENTITY

    def test_reconstructs_from_bytes_without_the_envelope_object(self) -> None:
        env = _archive()
        sections = {section.digest: section.content for section in env.sections}
        verified = verify_archive_bytes(
            body=env.body,
            manifest=env.manifest,
            sections=sections,
        )
        assert verified.chain_verified is False
        assert verified.body_digest == env.body_digest
        assert verified.manifest_digest == env.manifest_digest
        assert verified.header_hash == env.header_hash
        assert verified.body_digest != verified.manifest_digest
        assert verified.body_digest != verified.header_hash
        assert verified.manifest_digest != verified.header_hash
        assert [item["record_id"] for item in verified.records] == [
            "rec-lose-1",
            "rec-win-1",
            "rec-lose-2",
        ]
        assert verify_envelope(env).manifest_digest == env.manifest_digest

    def test_forged_section_bytes_are_refused(self) -> None:
        env = _archive()
        sections = {section.digest: section.content for section in env.sections}
        original = next(section for section in env.sections if section.name == "candidates")
        forged = canonical_bytes(
            [{**json.loads(original.content)[0], "performance": 999.0}]
        )
        sections[original.digest] = forged
        with pytest.raises(ArchiveRefusal, match="DIGEST_MISMATCH"):
            verify_archive_bytes(body=env.body, manifest=env.manifest, sections=sections)

    def test_reordered_inventory_link_is_refused(self) -> None:
        env = _archive()
        manifest = json.loads(env.manifest)
        manifest["inventory"][1], manifest["inventory"][2] = (
            manifest["inventory"][2],
            manifest["inventory"][1],
        )
        for seq, item in enumerate(manifest["inventory"]):
            item["seq"] = seq
        sections = {section.digest: section.content for section in env.sections}
        with pytest.raises(ArchiveRefusal, match="INVENTORY_LINK"):
            verify_archive_bytes(
                body=env.body,
                manifest=canonical_bytes(manifest),
                sections=sections,
            )

    def test_same_block_candidates_share_body_digest_only(self) -> None:
        block = _block()
        first = build_archive(
            block=block,
            candidates=[_candidate("rec-a", won=False, attempt=1, performance=0.1)],
            retries=[],
        )
        second = build_archive(
            block=block,
            candidates=[_candidate("rec-a", won=False, attempt=1, performance=0.2)],
            retries=[],
        )
        assert first.body_digest == second.body_digest
        assert first.manifest_digest != second.manifest_digest
        assert first.header_hash == second.header_hash
        assert first.body_digest != first.header_hash
