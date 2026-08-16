"""WP2 tests — event vs progress-certificate blocks and reward policies
(doc 40 §4/§5), every refusal exercised.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from doin_core.models import coin
from doin_core.models.progress_certificates import (
    EventBlockSchema,
    InvalidPolicyError,
    PolicyRefusal,
    ProgressBinQualityContract,
    ProgressBinRewardPolicy,
    ProgressCertificate,
    ProgressCertificateBlockSchema,
    PrototypeRewardPolicy,
    UnknownPolicyError,
    VerifiedContribution,
    parse_reward_policy,
)
from doin_core.models.transaction import Transaction, TransactionType


def make_contract(required: float = 1.0) -> ProgressBinQualityContract:
    return ProgressBinQualityContract(
        contract_id="bin-contract-1",
        domain_id="dom-1",
        metric="mae_improvement",
        required_verified_increment=required,
        derivation="fixed_quality_contract",
        cadence_adjustable=False,
        wall_clock_relaxation=False,
    )


def make_certificate(total: float, required: float = 1.0) -> ProgressCertificate:
    return ProgressCertificate(
        certificate_id="cert-1",
        contract=make_contract(required),
        contributions=(
            VerifiedContribution(
                contributor_id="opt-1",
                verified_increment=total * 0.75,
                evidence_ref="quorum-evidence-1",
            ),
            VerifiedContribution(
                contributor_id="opt-2",
                verified_increment=total * 0.25,
                evidence_ref="quorum-evidence-2",
            ),
        ),
        verification_evidence_ref="quorum-packet-1",
    )


# ── Progress-bin quality contract ────────────────────────────────────

class TestQualityContract:
    def test_valid_contract(self):
        contract = make_contract()
        assert contract.required_verified_increment == 1.0

    def test_refuses_cadence_adjustable_contract(self):
        """Doc 40 §4: the bin does NOT get easier to meet cadence — a
        cadence-adjustable contract cannot be constructed."""
        with pytest.raises(ValidationError):
            ProgressBinQualityContract(
                contract_id="bin-contract-1",
                domain_id="dom-1",
                metric="mae_improvement",
                required_verified_increment=1.0,
                derivation="fixed_quality_contract",
                cadence_adjustable=True,
                wall_clock_relaxation=False,
            )

    def test_refuses_wall_clock_relaxation(self):
        with pytest.raises(ValidationError):
            ProgressBinQualityContract(
                contract_id="bin-contract-1",
                domain_id="dom-1",
                metric="mae_improvement",
                required_verified_increment=1.0,
                derivation="fixed_quality_contract",
                cadence_adjustable=False,
                wall_clock_relaxation=True,
            )

    def test_refuses_non_fixed_derivation(self):
        with pytest.raises(ValidationError):
            ProgressBinQualityContract(
                contract_id="bin-contract-1",
                domain_id="dom-1",
                metric="mae_improvement",
                required_verified_increment=1.0,
                derivation="block_time_targeted",
                cadence_adjustable=False,
                wall_clock_relaxation=False,
            )

    def test_refuses_zero_or_negative_bin_size(self):
        for bad in (0.0, -1.0):
            with pytest.raises(ValidationError):
                make_contract(required=bad)

    def test_contract_is_immutable(self):
        contract = make_contract()
        with pytest.raises(ValidationError):
            contract.required_verified_increment = 0.001


# ── Event block vs progress-certificate block ────────────────────────

class TestBlockKinds:
    def test_event_block_carries_zero_issuance(self):
        tx = Transaction(
            tx_type=TransactionType.TASK_COMPLETED,
            domain_id="dom-1",
            peer_id="peer-1",
        )
        block = EventBlockSchema(block_kind="event", transactions=(tx,))
        assert block.issuance_units == 0

    def test_event_block_refuses_nonzero_issuance(self):
        with pytest.raises(ValidationError):
            EventBlockSchema(block_kind="event", issuance_units=1)

    def test_heartbeat_event_block_may_be_empty(self):
        block = EventBlockSchema(block_kind="event")
        assert block.transactions == ()
        assert block.issuance_units == 0

    def test_certificate_block_requires_completely_filled_certificate(self):
        block = ProgressCertificateBlockSchema(
            block_kind="progress_certificate",
            certificate=make_certificate(total=1.0),
        )
        assert block.issuance_units == 1
        assert block.certificate.is_completely_filled

    def test_certificate_block_refuses_unfilled_certificate(self):
        """An unfilled bin issues ZERO — it cannot ride a certificate block."""
        with pytest.raises(ValidationError):
            ProgressCertificateBlockSchema(
                block_kind="progress_certificate",
                certificate=make_certificate(total=0.5),
            )

    def test_certificate_block_refuses_fractional_issuance(self):
        with pytest.raises(ValidationError):
            ProgressCertificateBlockSchema(
                block_kind="progress_certificate",
                certificate=make_certificate(total=1.0),
                issuance_units=2,
            )

    def test_block_kinds_cannot_be_swapped(self):
        with pytest.raises(ValidationError):
            EventBlockSchema(block_kind="progress_certificate")
        with pytest.raises(ValidationError):
            ProgressCertificateBlockSchema(
                block_kind="event",
                certificate=make_certificate(total=1.0),
            )

    def test_partial_contribution_affects_distribution_not_issuance(self):
        """Two contributors fill one bin: issuance stays exactly 1 unit;
        their shares are distribution facts inside the certificate."""
        cert = make_certificate(total=2.0)  # overfilled by two contributors
        block = ProgressCertificateBlockSchema(
            block_kind="progress_certificate", certificate=cert
        )
        assert block.issuance_units == 1
        shares = {c.contributor_id: c.verified_increment for c in cert.contributions}
        assert shares["opt-1"] == pytest.approx(1.5)
        assert shares["opt-2"] == pytest.approx(0.5)


# ── Reward policies: prototype vs target ─────────────────────────────

class TestRewardPolicies:
    def test_prototype_policy_tracks_implemented_constants(self):
        policy = PrototypeRewardPolicy.from_code()
        assert policy.status == "implemented_prototype"
        assert policy.initial_block_reward == coin.INITIAL_BLOCK_REWARD
        assert policy.halving_interval == coin.HALVING_INTERVAL
        assert policy.max_supply == coin.MAX_SUPPLY
        assert policy.generator_fee_fraction == coin.GENERATOR_FEE_FRACTION
        assert policy.optimizer_pool_fraction == coin.OPTIMIZER_POOL_FRACTION
        assert policy.evaluator_pool_fraction == coin.EVALUATOR_POOL_FRACTION

    def test_prototype_policy_declares_conservation_defect(self):
        policy = PrototypeRewardPolicy.from_code()
        assert policy.known_conservation_defect is True
        assert "67.15" in policy.conservation_defect_ref

    def test_prototype_policy_cannot_hide_the_defect(self):
        payload = PrototypeRewardPolicy.from_code().model_dump()
        payload["known_conservation_defect"] = False
        with pytest.raises(InvalidPolicyError):
            parse_reward_policy(payload)

    def test_target_policy_literals(self):
        policy = ProgressBinRewardPolicy(
            policy_kind="target_progress_bin",
            status="owner_directed_target",
        )
        assert policy.units_per_filled_certificate == 1
        assert policy.units_for_empty_bin == 0
        assert policy.fractional_issuance_for_unfilled_bin is False
        assert policy.partial_contribution_affects_distribution_only is True

    def test_target_policy_refuses_fractional_issuance(self):
        with pytest.raises(ValidationError):
            ProgressBinRewardPolicy(
                policy_kind="target_progress_bin",
                status="owner_directed_target",
                fractional_issuance_for_unfilled_bin=True,
            )

    def test_prototype_cannot_claim_target_status(self):
        """The two policies can never be silently relabeled into each other."""
        payload = PrototypeRewardPolicy.from_code().model_dump()
        payload["status"] = "owner_directed_target"
        with pytest.raises(InvalidPolicyError):
            parse_reward_policy(payload)

    def test_target_cannot_claim_implemented_status(self):
        with pytest.raises(InvalidPolicyError):
            parse_reward_policy(
                {
                    "policy_kind": "target_progress_bin",
                    "status": "implemented_prototype",
                }
            )

    def test_parse_dispatches_both_policies(self):
        proto = parse_reward_policy(PrototypeRewardPolicy.from_code().model_dump())
        target = parse_reward_policy(
            {
                "policy_kind": "target_progress_bin",
                "status": "owner_directed_target",
            }
        )
        assert isinstance(proto, PrototypeRewardPolicy)
        assert isinstance(target, ProgressBinRewardPolicy)
        assert type(proto) is not type(target)

    def test_unknown_policy_kind_refuses(self):
        with pytest.raises(UnknownPolicyError):
            parse_reward_policy({"policy_kind": "universal_basic_hashrate"})

    def test_non_mapping_refuses(self):
        with pytest.raises(UnknownPolicyError):
            parse_reward_policy("target_progress_bin")

    def test_refusals_share_a_typed_base(self):
        assert issubclass(UnknownPolicyError, PolicyRefusal)
        assert issubclass(InvalidPolicyError, PolicyRefusal)
