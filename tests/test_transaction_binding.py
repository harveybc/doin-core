"""Adversarial tests for transaction ID ↔ content binding (finding 201).

Order reference: MUSASHI_TO_GENERAL_SATOSHI_III_BLOCKCHAIN_AND_FOUR_FRONT
_CORRECTION_ORDER_2026_08_10.md §4 (WP1) — core-side mandatory cases:

- supplied arbitrary ID with valid body is rejected;
- type/domain/peer/timestamp mutations each invalidate the ID;
- key-order changes inside a semantically identical payload remain
  deterministic;
- valid historical fixtures remain byte/hash identical.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from doin_core.models.transaction import (
    TX_ID_PATTERN,
    Transaction,
    TransactionIntegrityError,
    TransactionType,
    canonical_transaction_bytes,
    compute_transaction_id,
)

TS = datetime(2026, 8, 10, tzinfo=timezone.utc)


def _make_tx(**overrides) -> Transaction:
    kwargs = dict(
        tx_type=TransactionType.OPTIMAE_ANNOUNCED,
        domain_id="eth-usd-4h",
        peer_id="peer-alpha",
        payload={"optimae_id": "abc123", "reported_performance": 0.87},
        timestamp=TS,
    )
    kwargs.update(overrides)
    return Transaction(**kwargs)


# ── Historical fixture stability ─────────────────────────────────────
# Constructed from the current implementation and frozen. Any change to
# these literals is a protocol migration, not a refactor.

FIXTURE_CANONICAL_BYTES = (
    b'{"domain_id": "eth-usd-4h", '
    b'"payload": {"optimae_id": "abc123", "reported_performance": 0.87}, '
    b'"peer_id": "peer-alpha", '
    b'"timestamp": "2026-08-10T00:00:00+00:00", '
    b'"tx_type": "optimae_announced"}'
)
FIXTURE_ID = "372639e6e99d22140702eb0a988a121be43bb04567ad157d2b372d5d57eae8dd"


class TestHistoricalFixtureStability:
    def test_canonical_bytes_are_byte_identical(self) -> None:
        tx = _make_tx()
        assert tx.canonical_bytes() == FIXTURE_CANONICAL_BYTES

    def test_fixture_hash_is_stable(self) -> None:
        tx = _make_tx()
        assert tx.id == FIXTURE_ID
        assert tx.compute_id() == FIXTURE_ID

    def test_raw_field_function_matches_fixture(self) -> None:
        assert compute_transaction_id(
            tx_type="optimae_announced",
            domain_id="eth-usd-4h",
            peer_id="peer-alpha",
            payload={"optimae_id": "abc123", "reported_performance": 0.87},
            timestamp="2026-08-10T00:00:00+00:00",
        ) == FIXTURE_ID

    def test_supplying_the_true_content_hash_is_accepted(self) -> None:
        tx = _make_tx(id=FIXTURE_ID)
        assert tx.id == FIXTURE_ID

    def test_json_roundtrip_preserves_id(self) -> None:
        tx = _make_tx()
        again = Transaction.model_validate_json(tx.model_dump_json())
        assert again.id == tx.id
        assert again.canonical_bytes() == tx.canonical_bytes()


class TestSuppliedIdRejection:
    def test_forged_id_with_valid_body_is_rejected(self) -> None:
        with pytest.raises(TransactionIntegrityError):
            _make_tx(id="f" * 64)

    def test_hash_of_wrong_content_is_rejected(self) -> None:
        other = _make_tx(domain_id="other-domain")
        with pytest.raises(TransactionIntegrityError):
            _make_tx(id=other.id)

    @pytest.mark.parametrize(
        "bad_id",
        [
            "F" * 64,          # uppercase hex
            "f" * 63,          # too short
            "f" * 65,          # too long
            "g" * 64,          # non-hex
            "0x" + "f" * 62,   # prefixed
            " " + "f" * 63,    # whitespace
        ],
    )
    def test_non_64_lowercase_hex_ids_are_rejected(self, bad_id: str) -> None:
        with pytest.raises(TransactionIntegrityError):
            _make_tx(id=bad_id)

    def test_error_contains_no_payload_dump(self) -> None:
        with pytest.raises(TransactionIntegrityError) as exc_info:
            _make_tx(id="f" * 64, payload={"secret": "DO-NOT-LEAK"})
        assert "DO-NOT-LEAK" not in str(exc_info.value)

    def test_derived_id_is_64_lowercase_hex(self) -> None:
        tx = _make_tx()
        assert TX_ID_PATTERN.fullmatch(tx.id)

    def test_post_construction_mutation_detected_by_verify(self) -> None:
        tx = _make_tx()
        tx.payload["reported_performance"] = 0.01
        with pytest.raises(TransactionIntegrityError):
            tx.verify_integrity()


class TestFieldMutationsInvalidateId:
    def test_tx_type_mutation_changes_id(self) -> None:
        a = _make_tx()
        b = _make_tx(tx_type=TransactionType.OPTIMAE_ACCEPTED)
        assert a.id != b.id

    def test_domain_mutation_changes_id(self) -> None:
        a = _make_tx()
        b = _make_tx(domain_id="btc-usd-1h")
        assert a.id != b.id

    def test_peer_mutation_changes_id(self) -> None:
        a = _make_tx()
        b = _make_tx(peer_id="peer-beta")
        assert a.id != b.id

    def test_timestamp_mutation_changes_id(self) -> None:
        a = _make_tx()
        b = _make_tx(timestamp=TS + timedelta(seconds=1))
        assert a.id != b.id

    def test_payload_mutation_changes_id(self) -> None:
        a = _make_tx()
        b = _make_tx(payload={"optimae_id": "abc123", "reported_performance": 0.88})
        assert a.id != b.id


class TestKeyOrderDeterminism:
    def test_payload_key_order_does_not_change_id(self) -> None:
        p1 = {"alpha": 1, "beta": 2, "gamma": {"x": 1, "y": 2}}
        p2 = {"gamma": {"y": 2, "x": 1}, "beta": 2, "alpha": 1}
        a = _make_tx(payload=p1)
        b = _make_tx(payload=p2)
        assert a.id == b.id
        assert a.canonical_bytes() == b.canonical_bytes()

    def test_raw_function_is_key_order_deterministic(self) -> None:
        common = dict(
            tx_type="optimae_announced",
            domain_id="d",
            peer_id="p",
            timestamp="2026-08-10T00:00:00+00:00",
        )
        h1 = compute_transaction_id(payload={"a": 1, "b": [1, 2]}, **common)
        h2 = compute_transaction_id(payload={"b": [1, 2], "a": 1}, **common)
        assert h1 == h2
