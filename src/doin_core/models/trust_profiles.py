"""Typed trust profiles — doc 40 §2 schema spike (NON-DEPLOYED branch).

Status labels (work_plan doc 40, WP1 truth split):

* This module is a typed-schema PROPOSAL living on an isolated spike branch.
  It does NOT alter active chain behavior: nothing in the deployed consensus
  path imports it. It exists so that a later, owner-ratified integration has
  fail-closed types to build on.
* ``trusted_consortium`` describes the profile that is OPERATING NOW
  (``trusted_consortium_current``).
* ``untrusted_generated_gate`` is ``conditional_untrusted_research``:
  doc 39 owns the admission program, and no current domain passes it, so no
  current domain can construct this profile object — which is exactly the
  fail-closed property the schema enforces.

Fail-closed contract:

* Unknown profile names refuse (``UnknownProfileError``); they never map to a
  default profile or a partial authority.
* An ``untrusted_generated_gate`` profile missing ANY doc-39 admission
  requirement cannot be constructed (``IncompleteAdmissionError``) and
  therefore has ZERO challenge authority (``challenge_authority`` returns
  0.0 for anything that does not validate).
* Evidence carries an explicit semantics tag. A block whose profile and
  evidence semantics disagree refuses (``MixedEvidenceError``); untrusted-gate
  evidence must additionally bind the admitted generator manifest
  (``EvidenceBindingError``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from doin_core.models.generator_identity import DrawCustodyEvidence

# ── Profile names (the only two known profiles; anything else fails closed) ──

TRUSTED_CONSORTIUM: Literal["trusted_consortium"] = "trusted_consortium"
UNTRUSTED_GENERATED_GATE: Literal["untrusted_generated_gate"] = (
    "untrusted_generated_gate"
)

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


# ── Typed refusals ───────────────────────────────────────────────────

class ProfileRefusal(ValueError):
    """Base class for every fail-closed refusal in this module."""


class UnknownProfileError(ProfileRefusal):
    """Raised for a profile name that is not a known trust profile."""


class IncompleteAdmissionError(ProfileRefusal):
    """Raised when an untrusted-gate profile misses any doc-39 requirement."""


class InvalidProfileError(ProfileRefusal):
    """Raised when a known profile's payload violates its typed contract."""


class MixedEvidenceError(ProfileRefusal):
    """Raised when evidence semantics do not match the block's profile."""


class EvidenceBindingError(ProfileRefusal):
    """Raised when untrusted-gate evidence is not bound to the admitted
    generator manifest."""


# ── trusted_consortium (doc 40 §2.1) ─────────────────────────────────

class PerformanceReEvaluation(BaseModel):
    """NAMED capability: performance re-evaluation policy (doc 40 §2.1).

    Skipping re-evaluation is a declared profile capability of the trusted
    profile — never an implicit default and never a claim that verification,
    hashes or lineage are unnecessary.  ``mode`` must be one of:

    * ``real_domain_criterion`` — re-evaluation runs against a declared real
      domain criterion (``criterion`` required);
    * ``explicitly_disabled`` — the operator accepts the report
      (``disabled_reason`` required).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["real_domain_criterion", "explicitly_disabled"]
    criterion: str | None = None
    disabled_reason: str | None = None

    @model_validator(mode="after")
    def _check_mode_pairing(self) -> PerformanceReEvaluation:
        if self.mode == "real_domain_criterion":
            if not self.criterion:
                raise ValueError(
                    "real_domain_criterion re-evaluation requires a declared "
                    "criterion (fail closed)"
                )
            if self.disabled_reason is not None:
                raise ValueError(
                    "criterion mode must not carry a disabled_reason"
                )
        else:  # explicitly_disabled
            if not self.disabled_reason:
                raise ValueError(
                    "explicitly_disabled re-evaluation requires a declared "
                    "reason (fail closed)"
                )
            if self.criterion is not None:
                raise ValueError("disabled mode must not carry a criterion")
        return self


class TrustedConsortiumProfile(BaseModel):
    """The currently-operating profile (doc 40 §2.1).

    It STILL verifies candidate identity, ancestry, artifact integrity,
    duplicate claims, chain consistency and lineage — these obligations are
    typed as ``Literal[True]`` so a profile that tries to waive any of them
    cannot be constructed.  Only performance re-evaluation is a named,
    configurable capability.  No native coin is required.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["trusted_consortium"]

    # Non-waivable verification obligations (refuse on anything but True).
    verifies_candidate_identity: Literal[True]
    verifies_ancestry: Literal[True]
    verifies_artifact_integrity: Literal[True]
    verifies_duplicate_claims: Literal[True]
    verifies_chain_consistency: Literal[True]
    verifies_lineage: Literal[True]

    # The one named capability.
    performance_reevaluation: PerformanceReEvaluation

    # Doc 40 §2.1: "No native coin is required for this profile."
    native_coin_required: Literal[False] = False


# ── untrusted_generated_gate (doc 40 §2.2, doc 39) ───────────────────
#
# Every doc-39 admission requirement is a REQUIRED typed field.  A domain
# missing ANY of them cannot construct this profile and therefore has ZERO
# authority (fail closed) — matching doc 39 §8: "absence of an admitted
# generator means zero challenge authority".

class SybilModel(BaseModel):
    """Authenticated participants plus an explicit Sybil/collusion model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    participants_authenticated: Literal[True]
    sybil_collusion_model: str = Field(min_length=1)


class CommitBeforeChallenge(BaseModel):
    """Commit-before-challenge ordering with post-commit entropy (doc 39 §4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    commit_before_challenge: Literal[True]
    post_commit_entropy_source: str = Field(
        min_length=1,
        description=(
            "e.g. 'finalized_chain_anchor' or a bounded multiparty "
            "commit/reveal/VRF contribution unavailable at candidate commit"
        ),
    )
    commitment_precedes_anchor_proof: Literal[True]


class AdmittedGenerator(BaseModel):
    """An admitted, content-addressed challenge generator (doc 39 §5-§7)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content_addressed: Literal[True]
    generator_manifest_hash: Sha256Hex = Field(
        description="manifest_hash of one immutable GeneratorIdentityManifest",
    )
    admission_evidence_ref: str = Field(
        min_length=1,
        description="Reference to the doc-39 admission program record",
    )


class DrawReconstruction(BaseModel):
    """Deterministic reconstruction of each evaluator's DISTINCT draw."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    per_evaluator_distinct_draws: Literal[True]
    deterministic_reconstruction: Literal[True]
    derivation_contract_version: str = Field(min_length=1)


class EvidenceQuorumTolerance(BaseModel):
    """Signed evidence, quorum rules and CALIBRATED aggregation tolerance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signed_evidence_required: Literal[True]
    quorum_rule: str = Field(min_length=1)
    tolerance_calibrated: Literal[True]
    calibration_artifact_hash: Sha256Hex


class GeneratorFalsification(BaseModel):
    """A falsified-or-bounded attempt to optimize against the generator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    optimize_against_generator_attempted: Literal[True]
    outcome: Literal["falsified", "bounded"]
    evidence_ref: str = Field(min_length=1)


class ProgressComparisonRule(BaseModel):
    """Declared rule for comparing progress within (and across) domains."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    within_domain_rule: str = Field(min_length=1)
    cross_domain_rule: str | None = Field(
        default=None,
        description=(
            "Optional: doc 40 §7 keeps cross-domain commensurability an OPEN "
            "question; if declared, it names a rule, it does not claim "
            "economic optimality"
        ),
    )


class UntrustedGeneratedGateProfile(BaseModel):
    """Conditional research profile (doc 40 §2.2).

    All seven doc-39 admission requirements are REQUIRED fields with no
    defaults.  No current domain passes the admission program, therefore no
    current domain can construct this object — zero authority, fail closed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: Literal["untrusted_generated_gate"]

    sybil_model: SybilModel
    commit_before_challenge: CommitBeforeChallenge
    admitted_generator: AdmittedGenerator
    draw_reconstruction: DrawReconstruction
    evidence_quorum_tolerance: EvidenceQuorumTolerance
    generator_falsification: GeneratorFalsification
    progress_comparison: ProgressComparisonRule


TrustProfile = Union[TrustedConsortiumProfile, UntrustedGeneratedGateProfile]


# ── Parsing / authority (fail closed) ────────────────────────────────

def parse_trust_profile(data: Any) -> TrustProfile:
    """Parse a trust profile payload, refusing anything unknown or partial.

    Raises:
        UnknownProfileError: profile name is not a known profile.
        IncompleteAdmissionError: untrusted-gate payload misses any doc-39
            admission requirement.
        InvalidProfileError: known profile with an invalid payload.
    """
    if not isinstance(data, Mapping):
        raise UnknownProfileError(
            f"trust profile payload must be a mapping, got {type(data).__name__}"
        )

    kind = data.get("profile")
    if kind == TRUSTED_CONSORTIUM:
        try:
            return TrustedConsortiumProfile.model_validate(dict(data))
        except ValidationError as exc:
            raise InvalidProfileError(
                f"trusted_consortium payload violates its typed contract: {exc}"
            ) from exc
    if kind == UNTRUSTED_GENERATED_GATE:
        try:
            return UntrustedGeneratedGateProfile.model_validate(dict(data))
        except ValidationError as exc:
            raise IncompleteAdmissionError(
                "untrusted_generated_gate payload does not satisfy the "
                f"complete doc-39 admission program (zero authority): {exc}"
            ) from exc
    raise UnknownProfileError(
        f"unknown trust profile {kind!r}: fail closed, zero authority"
    )


def challenge_authority(profile_data: Any) -> float:
    """Challenge authority granted by a profile payload. FAIL CLOSED.

    Returns 0.0 for anything that is not a completely valid profile —
    unknown profiles, partial admission evidence, malformed payloads and
    ``None`` all yield zero.  A fully valid profile yields 1.0 (a bounded
    normalized authority, not an economic weight).
    """
    if profile_data is None:
        return 0.0
    if isinstance(
        profile_data, (TrustedConsortiumProfile, UntrustedGeneratedGateProfile)
    ):
        return 1.0
    try:
        parse_trust_profile(profile_data)
    except ProfileRefusal:
        return 0.0
    return 1.0


# ── Evidence semantics (mixed semantics refuse) ──────────────────────

class TrustedConsortiumEvidence(BaseModel):
    """Evidence produced under operator/consortium trust (doc 40 §2.1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_semantics: Literal["trusted_consortium"]
    operator_id: str = Field(min_length=1)
    verification_record_ref: str = Field(
        min_length=1,
        description=(
            "Reference to the identity/ancestry/integrity/duplicate/lineage "
            "verification record"
        ),
    )


class UntrustedGateEvidence(BaseModel):
    """Signed per-evaluator evidence under the untrusted gate (doc 39 §5.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_semantics: Literal["untrusted_generated_gate"]
    evaluator_id: str = Field(min_length=1)
    signature: str = Field(min_length=1)
    generator_manifest_hash: Sha256Hex
    draw_custody: DrawCustodyEvidence

    @model_validator(mode="after")
    def _draw_bound_to_same_manifest(self) -> UntrustedGateEvidence:
        if self.draw_custody.manifest_hash != self.generator_manifest_hash:
            raise ValueError(
                "draw-custody evidence is bound to a different generator "
                "manifest than this evidence claims (fail closed)"
            )
        return self


ProfileEvidence = Union[TrustedConsortiumEvidence, UntrustedGateEvidence]


def validate_evidence_for_profile(
    profile: TrustProfile,
    evidence_items: Sequence[ProfileEvidence],
) -> None:
    """Refuse mixed evidence semantics and unbound generator evidence.

    * Every evidence item's ``evidence_semantics`` must equal the block
      profile's name; otherwise ``MixedEvidenceError`` (e.g. an
      untrusted-gate block carrying trusted-consortium evidence).
    * Under ``untrusted_generated_gate``, every evidence item must bind the
      profile's ADMITTED generator manifest; otherwise
      ``EvidenceBindingError``.
    """
    expected = profile.profile
    for item in evidence_items:
        if not isinstance(
            item, (TrustedConsortiumEvidence, UntrustedGateEvidence)
        ):
            raise MixedEvidenceError(
                f"untyped evidence {type(item).__name__} refused (fail closed)"
            )
        if item.evidence_semantics != expected:
            raise MixedEvidenceError(
                f"block profile {expected!r} cannot carry evidence with "
                f"semantics {item.evidence_semantics!r} (fail closed)"
            )
    if isinstance(profile, UntrustedGeneratedGateProfile):
        admitted = profile.admitted_generator.generator_manifest_hash
        for item in evidence_items:
            assert isinstance(item, UntrustedGateEvidence)  # narrowed above
            if item.generator_manifest_hash != admitted:
                raise EvidenceBindingError(
                    "evidence generator manifest "
                    f"{item.generator_manifest_hash[:16]}… does not match the "
                    f"admitted generator {admitted[:16]}… (fail closed)"
                )
