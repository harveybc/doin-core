"""Deterministic seed requirement — prevents hidden randomness in optimization.

Optimizers MUST declare a seed in their optimae submission.  Evaluators
use the same seed during verification.  This ensures:

1. Reproducibility: any evaluator can reproduce the exact training run
2. No hidden randomness: optimizer can't cherry-pick lucky seeds
3. Auditability: results are deterministic given (params, seed, data)

The seed is derived from the commitment hash + a domain-specific salt
so it's unpredictable at commitment time but deterministic at reveal time.

Defense against attack #12 (non-deterministic optimization results).
"""

from __future__ import annotations

import hashlib
import struct


def derive_seed(commitment_hash: str, domain_id: str, salt: str = "") -> int:
    """Derive a deterministic seed from commitment + domain.

    The seed is a 32-bit integer suitable for numpy/torch/random seeding.
    It's deterministic: same inputs always produce the same seed.

    Args:
        commitment_hash: The optimae commitment hash (from commit-reveal).
        domain_id: The domain being optimized.
        salt: Optional additional salt (e.g. evaluation round number).

    Returns:
        32-bit integer seed.
    """
    payload = f"{commitment_hash}:{domain_id}:{salt}"
    h = hashlib.sha256(payload.encode()).digest()
    # Take first 4 bytes as unsigned 32-bit int
    return struct.unpack(">I", h[:4])[0]


def verify_seed(
    commitment_hash: str,
    domain_id: str,
    claimed_seed: int,
    salt: str = "",
) -> bool:
    """Verify that a claimed seed matches the deterministic derivation."""
    expected = derive_seed(commitment_hash, domain_id, salt)
    return claimed_seed == expected


class DeterministicSeedPolicy:
    """Enforces deterministic seed usage across the network.

    Optimizer seed: derived from commitment_hash + domain_id.
    The optimizer knows this seed (they created the commitment).
    This ensures reproducibility of the optimizer's training run.

    Evaluator synthetic data seed: derived from commitment_hash + domain_id
    + evaluator_id + chain_tip_hash. The optimizer CANNOT predict this because:
      - They don't know which evaluators will be selected (random quorum)
      - They don't know the chain tip at quorum selection time
      - Each evaluator gets a DIFFERENT seed → different synthetic data

    This means each evaluator tests on different synthetic data, preventing
    the optimizer from pre-generating and training on the verification data.
    A genuinely good model generalizes across all synthetic datasets
    (within the incentive tolerance margin).
    """

    def __init__(self, require_seed: bool = True) -> None:
        self._require_seed = require_seed

    @property
    def required(self) -> bool:
        return self._require_seed

    def get_seed_for_optimae(
        self,
        commitment_hash: str,
        domain_id: str,
    ) -> int:
        """Get the seed an optimizer must use for a given optimae.

        The optimizer knows this seed (it's their commitment).
        Used for reproducibility of the optimization run.
        """
        return derive_seed(commitment_hash, domain_id)

    def get_seed_for_synthetic_data(
        self,
        commitment_hash: str,
        domain_id: str,
        evaluator_id: str,
        chain_tip_hash: str,
    ) -> int:
        """Get a per-evaluator seed for synthetic data generation.

        Each evaluator gets a DIFFERENT seed because evaluator_id and
        chain_tip_hash are mixed in.  The optimizer cannot predict this
        because they don't know:
          - Which evaluators will be selected (random quorum)
          - The chain tip hash at quorum selection time

        This prevents the optimizer from generating the same synthetic data
        and overfitting to it.
        """
        salt = f"{evaluator_id}:{chain_tip_hash}"
        return derive_seed(commitment_hash, domain_id, salt=salt)

    def get_seed_for_evaluation(
        self,
        commitment_hash: str,
        domain_id: str,
        evaluation_round: int = 0,
    ) -> int:
        """Get a seed for the evaluation model training (not for synthetic data).

        This controls the randomness in the model training process itself
        (weight initialization, batch shuffling, etc.).
        """
        return derive_seed(commitment_hash, domain_id, salt=str(evaluation_round))

    def validate_submission(
        self,
        commitment_hash: str,
        domain_id: str,
        declared_seed: int | None,
    ) -> tuple[bool, str]:
        """Validate an optimae submission's seed declaration.

        Returns (is_valid, reason).
        """
        if not self._require_seed:
            return True, ""

        if declared_seed is None:
            return False, "Seed not declared (deterministic seed required)"

        expected = derive_seed(commitment_hash, domain_id)
        if declared_seed != expected:
            return False, (
                f"Declared seed {declared_seed} does not match "
                f"expected {expected} for commitment {commitment_hash[:16]}..."
            )

        return True, ""
