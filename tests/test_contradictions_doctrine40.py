"""WP3 — synthetic contradiction reproducers (Musashi order §5, doc 40/39).

REPRODUCE BEFORE CORRECTING: each test PASSES by demonstrating the CURRENT
contradictory behavior of the code on this commit.  These fixtures pin the
PRE-correction state; when a contradiction is later corrected (behavior
change, owner/auditor disposition), the corresponding fixture MUST fail and
be retired together with the source-of-truth matrix row
(docs/SOURCE_OF_TRUTH_MATRIX_DOC40_WP3_20260815.md).

None of these tests changes deployed consensus behavior — they only observe
it.  Companion typed schemas (trust_profiles / generator_identity /
progress_certificates) provide the fail-closed target objects; runtime
enforcement is deferred to NOT-FOR-DEPLOYMENT patches.
"""

from __future__ import annotations

import dataclasses
import hashlib
from typing import Any

from doin_core.consensus.deterministic_seed import DeterministicSeedPolicy
from doin_core.consensus.proof_of_optimization import ProofOfOptimization
from doin_core.consensus.weights import VerifiedUtilityWeights
from doin_core.models.block import Block
from doin_core.models.domain import Domain, DomainConfig
from doin_core.models.optimae import Optimae
from doin_core.models.quorum import (
    QuorumConfig,
    QuorumManager,
    QuorumResult,
    QuorumState,
    VerificationVote,
)
from doin_core.plugins.base import SyntheticDataPlugin, hash_synthetic_data


class ToyDeterministicGenerator(SyntheticDataPlugin):
    """Minimal deterministic generator honoring the ABC contract:
    same seed -> same output, always."""

    def configure(self, config: dict[str, Any]) -> None:
        pass

    def generate(self, seed: int | None = None) -> dict[str, Any]:
        digest = hashlib.sha256(f"toy:{seed}".encode()).hexdigest()
        return {"series": [int(c, 16) for c in digest[:16]]}


class MemorizedReplayGenerator(SyntheticDataPlugin):
    """A mechanically DIFFERENT generator (different code path: replay of a
    memorized sample) that emits the same bytes for a chosen seed."""

    def __init__(self, memorized: dict[int, dict[str, Any]]) -> None:
        self._memorized = memorized

    def configure(self, config: dict[str, Any]) -> None:
        pass

    def generate(self, seed: int | None = None) -> dict[str, Any]:
        return self._memorized[seed]


def quorum_with_votes(
    performances_and_hashes: list[tuple[str, float, str]],
    reported: float = 1.0,
    tolerance: float = 0.05,
) -> tuple[QuorumManager, QuorumState | None]:
    manager = QuorumManager(QuorumConfig(min_evaluators=3, tolerance=tolerance))
    evaluators = [e for e, _, _ in performances_and_hashes]
    manager.select_evaluators(
        optimae_id="opt-1",
        domain_id="dom-1",
        optimizer_id="optimizer-x",
        reported_performance=reported,
        eligible_evaluators=evaluators,
        chain_tip_hash="tip-1",
    )
    state = None
    for evaluator_id, performance, data_hash in performances_and_hashes:
        state = manager.add_vote(
            optimae_id="opt-1",
            evaluator_id=evaluator_id,
            verified_performance=performance,
            used_synthetic=bool(data_hash),
            synthetic_data_hash=data_hash,
        )
    return manager, state


# ── Contradiction 1 ──────────────────────────────────────────────────

def test_contradiction_1_abc_same_seed_vs_runtime_distinct_evaluator_seeds():
    """ABC/spec says the quorum shares ONE seed/sample verified by hash
    consensus; the runtime derives a DISTINCT seed per evaluator.

    Spec side: plugins/base.py SyntheticDataPlugin docstrings; quorum.py
    evaluate_quorum docstring step 1 ("hash must match").
    Code side: deterministic_seed.py get_seed_for_synthetic_data mixes
    evaluator_id + chain_tip_hash, so seeds — and therefore samples and
    hashes — differ by design.  Both cannot be true.
    """
    # -- The spec claims (verbatim, from the ABC contract docstrings):
    assert "same seed" in SyntheticDataPlugin.__doc__
    assert "identical synthetic data" in SyntheticDataPlugin.__doc__
    assert "hash consensus" in SyntheticDataPlugin.__doc__
    assert "all evaluators get the same seed" in SyntheticDataPlugin.generate.__doc__
    assert "identical synthetic data" in (
        SyntheticDataPlugin.generate_with_hash.__doc__
    )
    assert "hash must match" in QuorumManager.evaluate_quorum.__doc__

    # -- The runtime does otherwise: distinct per-evaluator seeds.
    policy = DeterministicSeedPolicy()
    seed_a = policy.get_seed_for_synthetic_data(
        "commit-1", "dom-1", "evaluator-a", "tip-1"
    )
    seed_b = policy.get_seed_for_synthetic_data(
        "commit-1", "dom-1", "evaluator-b", "tip-1"
    )
    assert seed_a != seed_b, "runtime derives DISTINCT evaluator seeds"

    # -- Consequence: the hash consensus promised by the ABC is unattainable
    #    even for a perfectly deterministic, contract-honoring generator.
    generator = ToyDeterministicGenerator()
    _, hash_a = generator.generate_with_hash(seed_a)
    _, hash_b = generator.generate_with_hash(seed_b)
    assert hash_a != hash_b, (
        "honest evaluators following the runtime seed policy CANNOT produce "
        "the identical data the ABC contract demands"
    )


# ── Contradiction 2 ──────────────────────────────────────────────────

def test_contradiction_2_abc_zero_weight_vs_runtime_half_fallback():
    """ABC/spec says no synthetic-data plugin means ZERO consensus weight;
    the runtime grants a 0.5 verification-strength fallback.

    Spec side: plugins/base.py SyntheticDataPlugin docstring ("domains
    without a synthetic data plugin get ZERO consensus weight"); doc 39 §8
    ("absence of an admitted generator means zero challenge authority").
    Code side: weights.py compute_weights uses verification_strength = 0.5.
    """
    # -- The spec claims:
    assert "ZERO consensus weight" in SyntheticDataPlugin.__doc__

    # -- The runtime does otherwise:
    vuw = VerifiedUtilityWeights()
    vuw.register_domain("dom-1", base_weight=1.0, has_synthetic_data=False)
    weights = vuw.compute_weights()
    assert weights["dom-1"] == 0.5, (
        "a domain with NO synthetic data plugin still receives weight 0.5, "
        "not the ZERO the ABC contract declares"
    )

    # And that nonzero weight converts raw increments into consensus-effective
    # increments:
    effective = vuw.get_effective_increment(
        "dom-1", raw_increment=1.0, contributor_reputation=10.0
    )
    assert effective > 0.0, (
        "the 0.5 fallback lets an unverified domain contribute a nonzero "
        "effective increment to the block-generation threshold"
    )


# ── Contradiction 3 ──────────────────────────────────────────────────

def test_contradiction_3_sample_hash_mistaken_for_generator_identity():
    """The only hash slot in the verification path is the SAMPLE hash — the
    code cannot distinguish a draw hash from a generator identity.

    Doc 40 §3: 'A draw hash must never replace the generator identity.'
    Code side: VerificationVote.synthetic_data_hash (quorum.py) is an
    untyped string fed by SyntheticDataPlugin.generate_with_hash(); no
    generator-identity field exists anywhere in the vote/state/result, so a
    sample hash IS the de-facto identity of the challenge mechanism.
    """
    # -- (a) No generator-identity field exists in the verification path.
    vote_fields = {f.name for f in dataclasses.fields(VerificationVote)}
    assert vote_fields == {
        "evaluator_id",
        "verified_performance",
        "used_synthetic",
        "synthetic_data_hash",
        "timestamp",
    }
    assert not any("generator" in f or "manifest" in f for f in vote_fields), (
        "the vote carries a sample hash and NOTHING identifying the "
        "generator mechanism"
    )

    # -- (b) Two mechanically DIFFERENT generators produce byte-identical
    #    samples, hence identical sample hashes: the draw hash cannot
    #    identify the mechanism that produced it.
    honest = ToyDeterministicGenerator()
    seed = 1234
    sample, honest_hash = honest.generate_with_hash(seed)
    replayer = MemorizedReplayGenerator({seed: sample})
    _, replay_hash = replayer.generate_with_hash(seed)
    assert honest_hash == replay_hash, (
        "different generator code, same sample hash — hash_synthetic_data "
        "identifies the DRAW, never the GENERATOR"
    )

    # -- (c) The quorum accepts ANY string in the hash slot — including one
    #    that is semantically a generator-manifest hash — with no typed
    #    refusal.  The conflation is accepted end to end.
    fake_generator_manifest_hash = hashlib.sha256(
        b"generator-code+weights+config+lock"
    ).hexdigest()
    _, state = quorum_with_votes(
        [
            ("evaluator-a", 1.0, honest_hash),  # a real DRAW hash
            ("evaluator-b", 1.0, fake_generator_manifest_hash),  # a MANIFEST hash
            ("evaluator-c", 1.0, honest_hash),
        ]
    )
    assert state is not None and state.has_quorum
    stored = {v.evaluator_id: v.synthetic_data_hash for v in state.votes}
    assert stored["evaluator-b"] == fake_generator_manifest_hash, (
        "a generator-identity hash rides in the sample-hash slot untyped "
        "and unrefused"
    )


# ── Contradiction 4 ──────────────────────────────────────────────────

def test_contradiction_4_distinct_draws_accepted_without_immutable_manifest():
    """Distinct synthetic draws are accepted purely by performance tolerance
    with NO immutable generator manifest anywhere in the decision.

    Doc 40 §3 permits distinct draws ONLY when each is reproducible from its
    recorded seed_i plus one immutable manifest.  The runtime quorum accepts
    distinct-hash votes within tolerance while carrying zero manifest
    evidence — nothing binds the three draws to one generator mechanism.
    """
    manager, state = quorum_with_votes(
        [
            ("evaluator-a", 1.00, "a" * 64),
            ("evaluator-b", 1.02, "b" * 64),  # distinct draw hashes
            ("evaluator-c", 0.99, "c" * 64),
        ],
        reported=1.0,
        tolerance=0.05,
    )
    assert state is not None and state.has_quorum

    result = manager.evaluate_quorum("opt-1")
    assert result.accepted, (
        "quorum ACCEPTS three distinct draws on tolerance alone"
    )

    # No structure consulted by the decision can even carry a manifest:
    for model in (VerificationVote, QuorumState, QuorumResult):
        names = {f.name for f in dataclasses.fields(model)}
        assert not any("manifest" in n or "generator" in n for n in names), (
            f"{model.__name__} has no generator-manifest field — the "
            "tolerance decision is unbound to any generator identity"
        )


# ── Contradiction 5 ──────────────────────────────────────────────────

def test_contradiction_5_missing_admission_evidence_still_influences_consensus():
    """A domain with NO generator-admission evidence still moves consensus:
    its optimae cross the quorum, earn nonzero effective increment via the
    0.5 fallback, and trigger block generation.

    Doc 40 §2.2 / doc 39 §8: no current domain passes the admission program,
    so under the untrusted profile such a domain has ZERO authority.  The
    runtime has no profile gate: missing evidence degrades trust to 0.5,
    never to 0, and blocks are minted from it.
    """
    # -- (a) The quorum happily accepts votes carrying NO synthetic evidence.
    manager, state = quorum_with_votes(
        [
            ("evaluator-a", 1.00, ""),  # used_synthetic=False, no hash
            ("evaluator-b", 1.01, ""),
            ("evaluator-c", 0.99, ""),
        ],
        reported=1.0,
    )
    assert state is not None
    result = manager.evaluate_quorum("opt-1")
    assert result.accepted, "acceptance with zero admission/draw evidence"
    assert all(not v.synthetic_data_hash for v in state.votes)

    # -- (b) The evidence-free domain gets nonzero consensus weight (0.5
    #    fallback) and a nonzero effective increment.
    vuw = VerifiedUtilityWeights()
    vuw.register_domain("dom-1", base_weight=1.0, has_synthetic_data=False)
    effective = vuw.get_effective_increment(
        "dom-1", raw_increment=2.5, contributor_reputation=10.0
    )
    assert effective > 0.0

    # -- (c) That effective increment crosses the proof-of-optimization
    #    threshold and MINTS A BLOCK.
    domain = Domain(
        id="dom-1",
        name="no-admission-evidence-domain",
        performance_metric="mae",
        weight=0.5,  # exactly the fallback verification strength
        config=DomainConfig(
            optimization_plugin="toy.opt",
            inference_plugin="toy.inf",
            synthetic_data_plugin=None,  # <- no admitted generator at all
        ),
    )
    poo = ProofOfOptimization(initial_threshold=1.0)
    poo.register_domain(domain)
    poo.record_optimae(
        Optimae(
            domain_id="dom-1",
            optimizer_id="optimizer-x",
            parameters={"p": 1},
            reported_performance=1.0,
            verified_performance=1.0,
            performance_increment=2.5,
        )
    )
    assert poo.can_generate_block()
    block = poo.generate_block(Block.genesis(), generator_id="gen-1")
    assert block is not None, (
        "a block was generated from a domain with NO generator-admission "
        "evidence — missing evidence influenced consensus"
    )
    assert block.header.weighted_performance_sum >= block.header.threshold
