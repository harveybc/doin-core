"""Proof-of-Optimization consensus with full attack hardening."""

from doin_core.consensus.deterministic_seed import (
    DeterministicSeedPolicy,
    derive_seed,
    verify_seed,
)
from doin_core.consensus.finality import (
    Checkpoint,
    ExternalAnchor,
    ExternalAnchorManager,
    FinalityManager,
)
from doin_core.consensus.fork_choice import ChainScore, ForkChoiceRule
from doin_core.consensus.incentives import (
    IncentiveConfig,
    VerificationIncentiveResult,
    compute_reward_fraction,
    evaluate_verification_incentive,
)
from doin_core.consensus.proof_of_optimization import ProofOfOptimization
from doin_core.consensus.weights import DomainStats, VerifiedUtilityWeights, WeightConfig

__all__ = [
    "ChainScore",
    "Checkpoint",
    "DeterministicSeedPolicy",
    "DomainStats",
    "ExternalAnchor",
    "ExternalAnchorManager",
    "FinalityManager",
    "ForkChoiceRule",
    "IncentiveConfig",
    "ProofOfOptimization",
    "VerifiedUtilityWeights",
    "VerificationIncentiveResult",
    "WeightConfig",
    "compute_reward_fraction",
    "derive_seed",
    "evaluate_verification_incentive",
    "verify_seed",
]
