"""Generator identity vs draw custody — doc 40 §3 / doc 39 §5.3 typed objects.

Status: schema spike on a NON-DEPLOYED branch. Nothing in the deployed
consensus path imports this module; it does not alter active chain behavior.

Two hashes have DIFFERENT meanings and both may be required:

1. ``GeneratorIdentityManifest`` — identifies the challenge MECHANISM: a
   manifest over generator code, model weights, configuration, training-data
   hashes, runtime contract and dependency lock.  Immutable (frozen).
2. ``DrawCustodyEvidence`` — proves WHICH event-specific sample one evaluator
   evaluated: the generated-challenge hash plus the post-commit seed
   derivation inputs for that evaluator.

A draw hash must NEVER substitute a generator identity.  That is a typed
refusal here (``GeneratorIdentityRequired``): ``require_generator_identity``
accepts only a ``GeneratorIdentityManifest`` instance — never a
``DrawCustodyEvidence``, never a bare hash string (a bare string cannot prove
which kind of object it addresses).

Distinct evaluators may hold distinct draws.  Each draw must be reproducible
after the fact from its recorded ``seed_i`` plus the immutable manifest —
``verify_draw_reproduction`` checks exactly that.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class GeneratorIdentityRequired(TypeError):
    """Typed refusal: something other than a GeneratorIdentityManifest was
    offered where the generator identity is required (doc 40 §3: 'A draw hash
    must never replace the generator identity')."""


class GeneratorIdentityManifest(BaseModel):
    """Content-addressed identity of one challenge-generator MECHANISM.

    Doc 40 §3 item 1: manifest hash over generator code, model weights,
    configuration, training-data references/hashes, runtime contract and
    dependency lock.  Frozen: an admitted generator is immutable; changing
    any component is a DIFFERENT generator with a different manifest hash.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_kind: Literal["generator_identity_manifest"]
    code_hash: Sha256Hex
    weights_hash: Sha256Hex
    config_hash: Sha256Hex
    training_data_hashes: tuple[Sha256Hex, ...] = Field(min_length=1)
    runtime_contract: str = Field(
        min_length=1,
        description="Declared deterministic numeric/runtime contract id",
    )
    dependency_lock_hash: Sha256Hex

    @property
    def manifest_hash(self) -> str:
        """Deterministic content address of this generator identity."""
        payload = json.dumps(
            {
                "object_kind": self.object_kind,
                "code_hash": self.code_hash,
                "weights_hash": self.weights_hash,
                "config_hash": self.config_hash,
                "training_data_hashes": list(self.training_data_hashes),
                "runtime_contract": self.runtime_contract,
                "dependency_lock_hash": self.dependency_lock_hash,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


class DrawCustodyEvidence(BaseModel):
    """Custody of ONE evaluator's event-specific generated challenge.

    Doc 40 §3 item 2: the generated-challenge hash plus the post-commit seed
    derivation inputs used by one evaluator.  It binds exactly one immutable
    generator identity via ``manifest_hash`` — a generator hash alone is
    insufficient to replay a vote, and this object alone is insufficient to
    identify the generator mechanism.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    object_kind: Literal["draw_custody_evidence"]
    challenge_data_hash: Sha256Hex
    evaluator_id: str = Field(min_length=1)
    seed_i: int = Field(ge=0, lt=2**32)
    # Post-commit seed derivation inputs (doc 39 §4 / §5.2):
    commitment_hash: str = Field(min_length=1)
    domain_id: str = Field(min_length=1)
    chain_anchor_hash: str = Field(
        min_length=1,
        description="Post-commit entropy anchor mixed into seed derivation",
    )
    derivation_contract_version: str = Field(min_length=1)
    # Binding to ONE immutable generator identity:
    manifest_hash: Sha256Hex


def require_generator_identity(obj: Any) -> GeneratorIdentityManifest:
    """Return the manifest, refusing every substitute with a typed error.

    Doc 40 §3: 'A draw hash must never replace the generator identity.'
    Bare hash strings are refused too: a string cannot prove whether it
    addresses a manifest, a draw or something else entirely.
    """
    if isinstance(obj, GeneratorIdentityManifest):
        return obj
    if isinstance(obj, DrawCustodyEvidence):
        raise GeneratorIdentityRequired(
            "draw-custody evidence offered where the generator identity is "
            "required: a draw hash must never replace the generator identity "
            "(doc 40 §3)"
        )
    raise GeneratorIdentityRequired(
        f"{type(obj).__name__} is not a GeneratorIdentityManifest: refusing "
        "to treat it as a generator identity (fail closed)"
    )


def verify_draw_reproduction(
    evidence: DrawCustodyEvidence,
    manifest: GeneratorIdentityManifest,
    generate_fn: Callable[[GeneratorIdentityManifest, int], Any],
    hash_fn: Callable[[Any], str],
) -> bool:
    """Reproduce one evaluator's draw from ``seed_i`` + the immutable manifest.

    Doc 40 §3: 'Each draw must be reproducible after the fact from its
    recorded seed_i and immutable manifest.'

    Fails closed: evidence bound to a DIFFERENT manifest refuses with
    ``GeneratorIdentityRequired`` rather than silently regenerating from the
    wrong mechanism.

    Args:
        evidence: The recorded draw-custody evidence.
        manifest: The admitted immutable generator identity.
        generate_fn: Deterministic generator: (manifest, seed) -> data.
        hash_fn: Canonical data hash (e.g.
            ``doin_core.plugins.base.hash_synthetic_data``).

    Returns:
        True iff regenerating from (manifest, seed_i) reproduces the recorded
        challenge hash.
    """
    if evidence.manifest_hash != manifest.manifest_hash:
        raise GeneratorIdentityRequired(
            "draw-custody evidence is bound to manifest "
            f"{evidence.manifest_hash[:16]}…, not the offered manifest "
            f"{manifest.manifest_hash[:16]}… (fail closed)"
        )
    regenerated = generate_fn(manifest, evidence.seed_i)
    return hash_fn(regenerated) == evidence.challenge_data_hash
