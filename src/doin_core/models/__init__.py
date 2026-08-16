"""Data models for DOIN — blocks, optimae, domains, tasks, reputation, quorum, transactions, coins."""

from doin_core.models.block import Block, BlockHeader
from doin_core.models.fee_market import FeeConfig, FeeMarket
from doin_core.models.coin import (
    BalanceTracker,
    CoinbaseOutput,
    CoinbaseTransaction,
    ContributorWork,
    TransferTransaction,
    compute_block_reward,
    distribute_block_reward,
)
from doin_core.models.commit_reveal import (
    Commitment,
    CommitRevealManager,
    Reveal,
    compute_commitment,
    verify_commitment,
)
from doin_core.models.domain import Domain, DomainConfig
from doin_core.models.generator_identity import (
    DrawCustodyEvidence,
    GeneratorIdentityManifest,
    GeneratorIdentityRequired,
    require_generator_identity,
    verify_draw_reproduction,
)
from doin_core.models.optimae import Optimae
from doin_core.models.progress_certificates import (
    EventBlockSchema,
    ProgressBinQualityContract,
    ProgressBinRewardPolicy,
    ProgressCertificate,
    ProgressCertificateBlockSchema,
    PrototypeRewardPolicy,
    UnknownPolicyError,
    VerifiedContribution,
    parse_reward_policy,
)
from doin_core.models.trust_profiles import (
    MixedEvidenceError,
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
from doin_core.models.quorum import QuorumConfig, QuorumManager, QuorumResult, QuorumState
from doin_core.models.reputation import ReputationScore, ReputationTracker
from doin_core.models.resource_limits import BoundsValidator, ResourceLimits
from doin_core.models.task import Task, TaskQueue, TaskStatus, TaskType
from doin_core.models.transaction import Transaction, TransactionType

__all__ = [
    "BalanceTracker",
    "Block",
    "BlockHeader",
    "BoundsValidator",
    "CoinbaseOutput",
    "CoinbaseTransaction",
    "ContributorWork",
    "DrawCustodyEvidence",
    "EventBlockSchema",
    "FeeConfig",
    "FeeMarket",
    "Commitment",
    "CommitRevealManager",
    "Domain",
    "DomainConfig",
    "GeneratorIdentityManifest",
    "GeneratorIdentityRequired",
    "MixedEvidenceError",
    "Optimae",
    "ProfileRefusal",
    "ProgressBinQualityContract",
    "ProgressBinRewardPolicy",
    "ProgressCertificate",
    "ProgressCertificateBlockSchema",
    "PrototypeRewardPolicy",
    "QuorumConfig",
    "QuorumManager",
    "QuorumResult",
    "QuorumState",
    "ReputationScore",
    "ReputationTracker",
    "ResourceLimits",
    "Reveal",
    "Task",
    "TaskQueue",
    "TaskStatus",
    "TaskType",
    "Transaction",
    "TransactionType",
    "TransferTransaction",
    "TrustedConsortiumEvidence",
    "TrustedConsortiumProfile",
    "UnknownPolicyError",
    "UnknownProfileError",
    "UntrustedGateEvidence",
    "UntrustedGeneratedGateProfile",
    "VerifiedContribution",
    "challenge_authority",
    "compute_block_reward",
    "compute_commitment",
    "distribute_block_reward",
    "parse_reward_policy",
    "parse_trust_profile",
    "require_generator_identity",
    "validate_evidence_for_profile",
    "verify_commitment",
    "verify_draw_reproduction",
]
