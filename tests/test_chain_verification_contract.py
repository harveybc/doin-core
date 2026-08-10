"""Contract tests: typed chain verification report + explicit chain identity.

Order reference: MUSASHI_TO_GENERAL_SATOSHI_III_BLOCKCHAIN_AND_FOUR_FRONT
_CORRECTION_ORDER_2026_08_10.md §5 (WP2), findings 202-203.

- ChainVerificationReport outcome semantics (pruned is never fully
  verified; refusal is a first-class outcome).
- ChainStatus carries protocol_version + chain_id + genesis_hash.
- validate_peer_chain_status refuses mismatched AND unattested identity
  with typed errors — legacy field defaults are never acceptance.
"""

from __future__ import annotations

import pytest

from doin_core.models.verification import (
    ChainVerificationOutcome,
    ChainVerificationReport,
    CheckStatus,
    FailureCoordinate,
    VerificationCheck,
    VerifiedSuffixFromCheckpoint,
)
from doin_core.protocol.messages import (
    PROTOCOL_VERSION,
    ChainIdentityMismatchError,
    ChainStatus,
    PeerChainMismatchError,
    ProtocolVersionMismatchError,
    validate_peer_chain_status,
)

CHAIN_ID = "doin-testnet-a"
GENESIS = "a" * 64


def _attested_status(**overrides) -> ChainStatus:
    fields = dict(
        chain_height=5,
        tip_hash="b" * 64,
        tip_index=4,
        finalized_height=2,
        protocol_version=PROTOCOL_VERSION,
        chain_id=CHAIN_ID,
        genesis_hash=GENESIS,
    )
    fields.update(overrides)
    return ChainStatus(**fields)


class TestChainStatusIdentity:
    def test_carries_identity_fields(self) -> None:
        status = _attested_status()
        assert status.protocol_version == PROTOCOL_VERSION
        assert status.chain_id == CHAIN_ID
        assert status.genesis_hash == GENESIS

    def test_serialization_roundtrip_preserves_identity(self) -> None:
        status = _attested_status()
        again = ChainStatus.model_validate(status.model_dump())
        assert again == status

    def test_matching_attestation_accepted(self) -> None:
        validate_peer_chain_status(
            _attested_status(),
            expected_chain_id=CHAIN_ID,
            expected_genesis_hash=GENESIS,
        )

    def test_protocol_version_mismatch_is_typed_refusal(self) -> None:
        with pytest.raises(ProtocolVersionMismatchError) as e:
            validate_peer_chain_status(
                _attested_status(protocol_version=PROTOCOL_VERSION + 1),
                expected_chain_id=CHAIN_ID,
                expected_genesis_hash=GENESIS,
            )
        assert e.value.field == "protocol_version"
        assert e.value.expected == PROTOCOL_VERSION
        assert e.value.received == PROTOCOL_VERSION + 1

    def test_legacy_unversioned_status_refused_not_default_accepted(self) -> None:
        # A pre-v2 peer parses fine (defaults 0/""), but is REFUSED:
        # field defaults are never acceptance.
        legacy = ChainStatus(chain_height=5, tip_hash="b" * 64, tip_index=4)
        assert legacy.protocol_version == 0 and legacy.chain_id == ""
        with pytest.raises(ProtocolVersionMismatchError):
            validate_peer_chain_status(
                legacy,
                expected_chain_id=CHAIN_ID,
                expected_genesis_hash=GENESIS,
            )

    def test_chain_id_mismatch_is_typed_refusal(self) -> None:
        with pytest.raises(ChainIdentityMismatchError) as e:
            validate_peer_chain_status(
                _attested_status(chain_id="doin-other-net"),
                expected_chain_id=CHAIN_ID,
                expected_genesis_hash=GENESIS,
            )
        assert e.value.field == "chain_id"

    def test_genesis_hash_mismatch_is_typed_refusal(self) -> None:
        with pytest.raises(ChainIdentityMismatchError) as e:
            validate_peer_chain_status(
                _attested_status(genesis_hash="c" * 64),
                expected_chain_id=CHAIN_ID,
                expected_genesis_hash=GENESIS,
            )
        assert e.value.field == "genesis_hash"

    def test_empty_identity_with_current_version_still_refused(self) -> None:
        with pytest.raises(ChainIdentityMismatchError):
            validate_peer_chain_status(
                _attested_status(chain_id="", genesis_hash=""),
                expected_chain_id=CHAIN_ID,
                expected_genesis_hash=GENESIS,
            )

    def test_typed_errors_share_base(self) -> None:
        assert issubclass(ProtocolVersionMismatchError, PeerChainMismatchError)
        assert issubclass(ChainIdentityMismatchError, PeerChainMismatchError)


class TestChainVerificationReport:
    def test_verified_outcomes_are_ok(self) -> None:
        for outcome in (
            ChainVerificationOutcome.FULLY_VERIFIED,
            ChainVerificationOutcome.VERIFIED_SUFFIX_FROM_CHECKPOINT,
        ):
            assert ChainVerificationReport(outcome=outcome).ok

    def test_failed_and_refused_are_not_ok(self) -> None:
        for outcome in (
            ChainVerificationOutcome.FAILED,
            ChainVerificationOutcome.REFUSED,
        ):
            assert not ChainVerificationReport(outcome=outcome).ok

    def test_report_carries_first_failure_coordinates(self) -> None:
        report = ChainVerificationReport(
            outcome=ChainVerificationOutcome.FAILED,
            first_failure=FailureCoordinate(
                check_number=7,
                check_name="transaction_content_hashes",
                block_index=12,
                tx_index=3,
                reason="content hash mismatch",
            ),
            checks=[
                VerificationCheck(
                    number=7,
                    name="transaction_content_hashes",
                    status=CheckStatus.FAIL,
                    first_failing_block=12,
                    first_failing_tx=3,
                ),
            ],
        )
        assert report.first_failure is not None
        assert report.first_failure.block_index == 12
        assert report.first_failure.tx_index == 3
        # JSON roundtrip (transportable evidence)
        again = ChainVerificationReport.model_validate_json(
            report.model_dump_json()
        )
        assert again.first_failure == report.first_failure

    def test_verified_suffix_is_typed(self) -> None:
        suffix = VerifiedSuffixFromCheckpoint(
            checkpoint_block_index=99,
            checkpoint_block_hash="d" * 64,
            suffix_start_index=100,
            suffix_end_index=150,
            suffix_tip_hash="e" * 64,
            pruned_body_blocks=99,
        )
        report = ChainVerificationReport(
            outcome=ChainVerificationOutcome.VERIFIED_SUFFIX_FROM_CHECKPOINT,
            verified_suffix=suffix,
        )
        assert report.ok
        assert report.outcome is not ChainVerificationOutcome.FULLY_VERIFIED
        assert report.verified_suffix.suffix_start_index == 100
