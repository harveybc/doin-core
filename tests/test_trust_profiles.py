"""WP2 tests — typed trust profiles (doc 40 §2), every refusal exercised.

Schema spike on a NON-DEPLOYED branch. These tests cover:
* trusted_consortium: non-waivable verification obligations, the NAMED
  performance re-evaluation capability, no coin required;
* untrusted_generated_gate: all seven doc-39 admission requirements as
  REQUIRED typed fields — missing ANY one refuses (zero authority);
* fail-closed parsing (unknown profile, malformed payload);
* mixed evidence semantics refusals in both directions;
* generator-manifest binding of untrusted-gate evidence.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from doin_core.models.generator_identity import DrawCustodyEvidence
from doin_core.models.trust_profiles import (
    EvidenceBindingError,
    IncompleteAdmissionError,
    InvalidProfileError,
    MixedEvidenceError,
    PerformanceReEvaluation,
    ProfileRefusal,
    TrustedConsortiumEvidence,
    TrustedConsortiumProfile,
    UnknownProfileError,
    UntrustedGateEvidence,
    UntrustedGeneratedGateProfile,
    challenge_authority,
    parse_trust_profile,
    validate_evidence_for_profile,
)

HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64


def trusted_payload() -> dict:
    return {
        "profile": "trusted_consortium",
        "verifies_candidate_identity": True,
        "verifies_ancestry": True,
        "verifies_artifact_integrity": True,
        "verifies_duplicate_claims": True,
        "verifies_chain_consistency": True,
        "verifies_lineage": True,
        "performance_reevaluation": {
            "mode": "real_domain_criterion",
            "criterion": "chronological_oos_mae",
        },
    }


def untrusted_payload() -> dict:
    return {
        "profile": "untrusted_generated_gate",
        "sybil_model": {
            "participants_authenticated": True,
            "sybil_collusion_model": "explicit-k-of-n-collusion-bound",
        },
        "commit_before_challenge": {
            "commit_before_challenge": True,
            "post_commit_entropy_source": "finalized_chain_anchor",
            "commitment_precedes_anchor_proof": True,
        },
        "admitted_generator": {
            "content_addressed": True,
            "generator_manifest_hash": HEX_A,
            "admission_evidence_ref": "doc39-admission-record-001",
        },
        "draw_reconstruction": {
            "per_evaluator_distinct_draws": True,
            "deterministic_reconstruction": True,
            "derivation_contract_version": "seed-derivation-v1",
        },
        "evidence_quorum_tolerance": {
            "signed_evidence_required": True,
            "quorum_rule": "2-of-3-median-ensemble",
            "tolerance_calibrated": True,
            "calibration_artifact_hash": HEX_B,
        },
        "generator_falsification": {
            "optimize_against_generator_attempted": True,
            "outcome": "bounded",
            "evidence_ref": "doc39-falsification-report-001",
        },
        "progress_comparison": {
            "within_domain_rule": "declared-metric-delta",
        },
    }


def draw_custody(manifest_hash: str = HEX_A) -> DrawCustodyEvidence:
    return DrawCustodyEvidence(
        object_kind="draw_custody_evidence",
        challenge_data_hash=HEX_C,
        evaluator_id="eval-1",
        seed_i=1234,
        commitment_hash="commit-1",
        domain_id="dom-1",
        chain_anchor_hash="anchor-1",
        derivation_contract_version="seed-derivation-v1",
        manifest_hash=manifest_hash,
    )


# ── trusted_consortium ───────────────────────────────────────────────

class TestTrustedConsortium:
    def test_valid_profile_parses(self):
        profile = parse_trust_profile(trusted_payload())
        assert isinstance(profile, TrustedConsortiumProfile)
        assert profile.native_coin_required is False

    @pytest.mark.parametrize(
        "obligation",
        [
            "verifies_candidate_identity",
            "verifies_ancestry",
            "verifies_artifact_integrity",
            "verifies_duplicate_claims",
            "verifies_chain_consistency",
            "verifies_lineage",
        ],
    )
    def test_refuses_waiving_any_verification_obligation(self, obligation):
        payload = trusted_payload()
        payload[obligation] = False
        with pytest.raises(InvalidProfileError):
            parse_trust_profile(payload)

    def test_refuses_requiring_native_coin(self):
        payload = trusted_payload()
        payload["native_coin_required"] = True
        with pytest.raises(InvalidProfileError):
            parse_trust_profile(payload)

    def test_reevaluation_may_be_explicitly_disabled(self):
        payload = trusted_payload()
        payload["performance_reevaluation"] = {
            "mode": "explicitly_disabled",
            "disabled_reason": "operator accepts the report (doc 40 §2.1)",
        }
        profile = parse_trust_profile(payload)
        assert profile.performance_reevaluation.mode == "explicitly_disabled"

    def test_refuses_criterion_mode_without_criterion(self):
        with pytest.raises(ValidationError):
            PerformanceReEvaluation(mode="real_domain_criterion")

    def test_refuses_disabled_mode_without_reason(self):
        with pytest.raises(ValidationError):
            PerformanceReEvaluation(mode="explicitly_disabled")

    def test_refuses_unknown_reevaluation_mode(self):
        with pytest.raises(ValidationError):
            PerformanceReEvaluation(mode="silent_skip")

    def test_refuses_extra_fields(self):
        payload = trusted_payload()
        payload["bonus_capability"] = "anything"
        with pytest.raises(InvalidProfileError):
            parse_trust_profile(payload)

    def test_profile_is_frozen(self):
        profile = parse_trust_profile(trusted_payload())
        with pytest.raises(ValidationError):
            profile.verifies_lineage = False


# ── untrusted_generated_gate ─────────────────────────────────────────

ADMISSION_REQUIREMENTS = [
    "sybil_model",
    "commit_before_challenge",
    "admitted_generator",
    "draw_reconstruction",
    "evidence_quorum_tolerance",
    "generator_falsification",
    "progress_comparison",
]


class TestUntrustedGeneratedGate:
    def test_complete_admission_program_parses(self):
        profile = parse_trust_profile(untrusted_payload())
        assert isinstance(profile, UntrustedGeneratedGateProfile)

    @pytest.mark.parametrize("requirement", ADMISSION_REQUIREMENTS)
    def test_missing_any_admission_requirement_refuses(self, requirement):
        """Doc 39 §8 / doc 40 §2.2: a domain missing ANY admission
        requirement has ZERO authority — the profile cannot even be built."""
        payload = untrusted_payload()
        del payload[requirement]
        with pytest.raises(IncompleteAdmissionError):
            parse_trust_profile(payload)

    @pytest.mark.parametrize("requirement", ADMISSION_REQUIREMENTS)
    def test_missing_any_requirement_means_zero_authority(self, requirement):
        payload = untrusted_payload()
        del payload[requirement]
        assert challenge_authority(payload) == 0.0

    def test_refuses_unauthenticated_participants(self):
        payload = untrusted_payload()
        payload["sybil_model"]["participants_authenticated"] = False
        with pytest.raises(IncompleteAdmissionError):
            parse_trust_profile(payload)

    def test_refuses_uncalibrated_tolerance(self):
        payload = untrusted_payload()
        payload["evidence_quorum_tolerance"]["tolerance_calibrated"] = False
        with pytest.raises(IncompleteAdmissionError):
            parse_trust_profile(payload)

    def test_refuses_unfalsified_generator_gaming(self):
        payload = untrusted_payload()
        payload["generator_falsification"]["outcome"] = "not_attempted"
        with pytest.raises(IncompleteAdmissionError):
            parse_trust_profile(payload)

    def test_refuses_non_content_addressed_generator(self):
        payload = untrusted_payload()
        payload["admitted_generator"]["content_addressed"] = False
        with pytest.raises(IncompleteAdmissionError):
            parse_trust_profile(payload)

    def test_refuses_malformed_manifest_hash(self):
        payload = untrusted_payload()
        payload["admitted_generator"]["generator_manifest_hash"] = "not-a-hash"
        with pytest.raises(IncompleteAdmissionError):
            parse_trust_profile(payload)


# ── fail-closed parsing and authority ────────────────────────────────

class TestFailClosed:
    def test_unknown_profile_refuses(self):
        with pytest.raises(UnknownProfileError):
            parse_trust_profile({"profile": "benevolent_dictator"})

    def test_missing_profile_field_refuses(self):
        with pytest.raises(UnknownProfileError):
            parse_trust_profile({"verifies_lineage": True})

    def test_non_mapping_refuses(self):
        with pytest.raises(UnknownProfileError):
            parse_trust_profile("trusted_consortium")

    def test_none_has_zero_authority(self):
        assert challenge_authority(None) == 0.0

    def test_unknown_profile_has_zero_authority(self):
        assert challenge_authority({"profile": "benevolent_dictator"}) == 0.0

    def test_valid_profiles_have_bounded_authority(self):
        assert challenge_authority(trusted_payload()) == 1.0
        assert challenge_authority(untrusted_payload()) == 1.0

    def test_all_refusals_share_a_typed_base(self):
        for exc_type in (
            UnknownProfileError,
            IncompleteAdmissionError,
            InvalidProfileError,
            MixedEvidenceError,
            EvidenceBindingError,
        ):
            assert issubclass(exc_type, ProfileRefusal)


# ── mixed evidence semantics ─────────────────────────────────────────

def trusted_evidence() -> TrustedConsortiumEvidence:
    return TrustedConsortiumEvidence(
        evidence_semantics="trusted_consortium",
        operator_id="owner-fleet",
        verification_record_ref="lineage-record-001",
    )


def untrusted_evidence(manifest_hash: str = HEX_A) -> UntrustedGateEvidence:
    return UntrustedGateEvidence(
        evidence_semantics="untrusted_generated_gate",
        evaluator_id="eval-1",
        signature="sig-1",
        generator_manifest_hash=manifest_hash,
        draw_custody=draw_custody(manifest_hash),
    )


class TestMixedEvidence:
    def test_matching_trusted_evidence_passes(self):
        profile = parse_trust_profile(trusted_payload())
        validate_evidence_for_profile(profile, [trusted_evidence()])

    def test_matching_untrusted_evidence_passes(self):
        profile = parse_trust_profile(untrusted_payload())
        validate_evidence_for_profile(profile, [untrusted_evidence()])

    def test_untrusted_block_with_trusted_evidence_refuses(self):
        """The order's canonical example: an untrusted-gate block carrying
        trusted-consortium evidence MUST refuse."""
        profile = parse_trust_profile(untrusted_payload())
        with pytest.raises(MixedEvidenceError):
            validate_evidence_for_profile(profile, [trusted_evidence()])

    def test_trusted_block_with_untrusted_evidence_refuses(self):
        profile = parse_trust_profile(trusted_payload())
        with pytest.raises(MixedEvidenceError):
            validate_evidence_for_profile(profile, [untrusted_evidence()])

    def test_one_mixed_item_among_many_refuses(self):
        profile = parse_trust_profile(untrusted_payload())
        with pytest.raises(MixedEvidenceError):
            validate_evidence_for_profile(
                profile, [untrusted_evidence(), trusted_evidence()]
            )

    def test_untyped_evidence_refuses(self):
        profile = parse_trust_profile(trusted_payload())
        with pytest.raises(MixedEvidenceError):
            validate_evidence_for_profile(
                profile, [{"evidence_semantics": "trusted_consortium"}]
            )

    def test_evidence_bound_to_wrong_generator_refuses(self):
        """Evidence must bind the ADMITTED generator manifest."""
        profile = parse_trust_profile(untrusted_payload())  # admits HEX_A
        with pytest.raises(EvidenceBindingError):
            validate_evidence_for_profile(
                profile, [untrusted_evidence(manifest_hash=HEX_B)]
            )

    def test_evidence_with_inconsistent_draw_binding_refuses(self):
        """UntrustedGateEvidence whose draw custody points at a different
        manifest than the evidence claims cannot even be constructed."""
        with pytest.raises(ValidationError):
            UntrustedGateEvidence(
                evidence_semantics="untrusted_generated_gate",
                evaluator_id="eval-1",
                signature="sig-1",
                generator_manifest_hash=HEX_A,
                draw_custody=draw_custody(HEX_B),
            )

    def test_evidence_semantics_tag_cannot_lie(self):
        """A trusted-evidence object cannot claim untrusted semantics."""
        with pytest.raises(ValidationError):
            TrustedConsortiumEvidence(
                evidence_semantics="untrusted_generated_gate",
                operator_id="owner-fleet",
                verification_record_ref="lineage-record-001",
            )
