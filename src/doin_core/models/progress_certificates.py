"""Event blocks, progress certificates and reward policies — doc 40 §4/§5.

Status: schema spike on a NON-DEPLOYED branch. Nothing in the deployed
consensus path imports this module; it does not alter active chain behavior.
The legacy ``Block``/``CoinbaseTransaction`` models are untouched and legacy
chain databases replay unchanged.

Doc 40 §4 separates three controls:

* Ledger liveness — ``EventBlockSchema``: event/heartbeat blocks MAY carry
  zero issuance (typed here as exactly zero: liveness never mints).
* Progress bin — ``ProgressBinQualityContract``: a FIXED quality contract
  that does NOT get easier to satisfy merely to meet wall-clock cadence
  (typed as ``Literal[False]`` anti-drift declarations).
* Issuance/distribution — ``ProgressCertificateBlockSchema``: one unit per
  COMPLETELY FILLED verified certificate; zero for an empty bin; fractional
  issuance for an unfilled bin refuses.

Reward policies are two DISTINCT typed objects:

* ``PrototypeRewardPolicy`` (``implemented_prototype``) — the constants that
  the current code actually implements (50/halving/21M, 5/65/30 splits,
  including the reproduced fee-conservation defect). Code facts, not
  ratified production economics.
* ``ProgressBinRewardPolicy`` (``owner_directed_target``) — the owner's
  target progress-bin issuance concept. A target, not a statement about the
  current code.

``parse_reward_policy`` fails closed on unknown policy kinds.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from doin_core.models import coin as _coin
from doin_core.models.transaction import Transaction


class PolicyRefusal(ValueError):
    """Base class for fail-closed refusals in this module."""


class UnknownPolicyError(PolicyRefusal):
    """Raised for a reward-policy kind that is not a known policy."""


class InvalidPolicyError(PolicyRefusal):
    """Raised when a known policy's payload violates its typed contract."""


# ── Progress bin (doc 40 §4, row 2) ──────────────────────────────────

class ProgressBinQualityContract(BaseModel):
    """FIXED quality contract for one progress bin.

    Doc 40 §4: the progress bin 'does not become easier to satisfy merely to
    meet wall-clock cadence'.  The anti-drift declarations are typed as
    ``Literal[False]`` so a cadence-relaxable contract cannot be constructed,
    and the model is frozen so a contract cannot be loosened after issuance
    references it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_id: str = Field(min_length=1)
    domain_id: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    required_verified_increment: float = Field(
        gt=0.0,
        description="Verified useful improvement that fills ONE certificate",
    )
    derivation: Literal["fixed_quality_contract"]
    # Anti-drift declarations (refuse on anything but False):
    cadence_adjustable: Literal[False]
    wall_clock_relaxation: Literal[False]


class VerifiedContribution(BaseModel):
    """One contributor's verified share inside a progress bin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contributor_id: str = Field(min_length=1)
    verified_increment: float = Field(ge=0.0)
    evidence_ref: str = Field(min_length=1)


class ProgressCertificate(BaseModel):
    """One progress certificate: a fixed quality contract plus the verified
    contributions accumulated toward it.

    ``is_completely_filled`` is the ONLY condition under which the target
    policy issues a unit.  Partial contribution inside a filled certificate
    affects DISTRIBUTION shares; it never creates fractional issuance for an
    unfilled bin (doc 40 §4).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    certificate_id: str = Field(min_length=1)
    contract: ProgressBinQualityContract
    contributions: tuple[VerifiedContribution, ...] = ()
    verification_evidence_ref: str = Field(
        min_length=1,
        description="Reference to the quorum/verification evidence packet",
    )

    @property
    def total_verified_increment(self) -> float:
        return sum(c.verified_increment for c in self.contributions)

    @property
    def is_completely_filled(self) -> bool:
        return (
            self.total_verified_increment
            >= self.contract.required_verified_increment
        )


# ── Block kinds (doc 40 §4, row 1 vs row 3) ──────────────────────────

class EventBlockSchema(BaseModel):
    """Ledger-liveness block: preserves ordered events, mints NOTHING.

    Doc 40 §4: event/heartbeat blocks may carry zero issuance.  Typed as
    exactly zero — a nonzero issuance on an event block refuses.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    block_kind: Literal["event"]
    issuance_units: Literal[0] = 0
    transactions: tuple[Transaction, ...] = ()


class ProgressCertificateBlockSchema(BaseModel):
    """Issuance block: exactly one COMPLETELY FILLED verified certificate.

    Target policy (doc 40 §4): one unit per completely filled verified
    progress certificate; zero for an empty bin (which is an event block,
    not this schema).  An unfilled certificate or fractional issuance
    refuses at construction.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    block_kind: Literal["progress_certificate"]
    certificate: ProgressCertificate
    issuance_units: Literal[1] = 1
    transactions: tuple[Transaction, ...] = ()

    @model_validator(mode="after")
    def _certificate_completely_filled(self) -> ProgressCertificateBlockSchema:
        if not self.certificate.is_completely_filled:
            raise ValueError(
                "progress-certificate block requires a COMPLETELY FILLED "
                "certificate: "
                f"{self.certificate.total_verified_increment} < "
                f"{self.certificate.contract.required_verified_increment} "
                "(unfilled bins issue zero and belong in event blocks)"
            )
        return self


# ── Reward policies (doc 40 §5): prototype vs target ─────────────────

class PrototypeRewardPolicy(BaseModel):
    """The reward policy the code IMPLEMENTS today (``implemented_prototype``).

    These are reproducible code facts from ``doin_core.models.coin`` — they
    are NOT owner-ratified production economics (doc 40 §5).  The known
    fee-conservation defect (50 + 10 -> 67.15 with no contributors) is
    declared as a typed field so this object cannot be presented as a clean
    policy.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_kind: Literal["prototype_block_reward"]
    status: Literal["implemented_prototype"]
    initial_block_reward: float = Field(gt=0.0)
    halving_interval: int = Field(gt=0)
    max_supply: float = Field(gt=0.0)
    generator_fee_fraction: float = Field(ge=0.0, le=1.0)
    optimizer_pool_fraction: float = Field(ge=0.0, le=1.0)
    evaluator_pool_fraction: float = Field(ge=0.0, le=1.0)
    known_conservation_defect: Literal[True]
    conservation_defect_ref: str = Field(min_length=1)

    @classmethod
    def from_code(cls) -> PrototypeRewardPolicy:
        """Build the policy object directly from the implemented constants,
        so the ``implemented_prototype`` label provably tracks the code."""
        return cls(
            policy_kind="prototype_block_reward",
            status="implemented_prototype",
            initial_block_reward=_coin.INITIAL_BLOCK_REWARD,
            halving_interval=_coin.HALVING_INTERVAL,
            max_supply=_coin.MAX_SUPPLY,
            generator_fee_fraction=_coin.GENERATOR_FEE_FRACTION,
            optimizer_pool_fraction=_coin.OPTIMIZER_POOL_FRACTION,
            evaluator_pool_fraction=_coin.EVALUATOR_POOL_FRACTION,
            known_conservation_defect=True,
            conservation_defect_ref=(
                "doc40 §5: distribute_block_reward(50 + 10 fees, no "
                "contributors) distributes 67.15 although only 60 exists; "
                "correction owned by WP4 (fee-conservation branch)"
            ),
        )


class ProgressBinRewardPolicy(BaseModel):
    """The owner's TARGET issuance policy (``owner_directed_target``).

    Doc 40 §4: one unit per completely filled verified progress certificate;
    zero for an empty bin; fractional issuance for an unfilled bin is not
    accepted without a later explicit economic experiment.  This is an
    owner-directed normalization target, NOT a statement about current code
    and NOT a salary per elapsed block.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_kind: Literal["target_progress_bin"]
    status: Literal["owner_directed_target"]
    units_per_filled_certificate: Literal[1] = 1
    units_for_empty_bin: Literal[0] = 0
    fractional_issuance_for_unfilled_bin: Literal[False] = False
    partial_contribution_affects_distribution_only: Literal[True] = True


RewardPolicy = Union[PrototypeRewardPolicy, ProgressBinRewardPolicy]

_POLICY_BY_KIND: dict[str, type[BaseModel]] = {
    "prototype_block_reward": PrototypeRewardPolicy,
    "target_progress_bin": ProgressBinRewardPolicy,
}


def parse_reward_policy(data: Any) -> RewardPolicy:
    """Parse a reward-policy payload, refusing unknown kinds (fail closed).

    A prototype policy claiming ``owner_directed_target`` status (or the
    reverse) refuses via the ``Literal`` status fields — the two policies can
    never be silently relabeled into each other.
    """
    if not isinstance(data, Mapping):
        raise UnknownPolicyError(
            f"reward policy payload must be a mapping, got {type(data).__name__}"
        )
    kind = data.get("policy_kind")
    model = _POLICY_BY_KIND.get(kind)  # type: ignore[arg-type]
    if model is None:
        raise UnknownPolicyError(
            f"unknown reward policy kind {kind!r}: fail closed"
        )
    try:
        return model.model_validate(dict(data))  # type: ignore[return-value]
    except ValidationError as exc:
        raise InvalidPolicyError(
            f"{kind} payload violates its typed contract: {exc}"
        ) from exc
