"""WP2 tests — generator identity vs draw custody (doc 40 §3 / doc 39 §5.3).

Covers: the two DISTINCT typed objects, the typed refusal when a draw hash
is offered as generator identity, and reproduction of distinct per-evaluator
draws from seed_i + one immutable manifest.
"""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from doin_core.consensus.deterministic_seed import DeterministicSeedPolicy
from doin_core.models.generator_identity import (
    DrawCustodyEvidence,
    GeneratorIdentityManifest,
    GeneratorIdentityRequired,
    require_generator_identity,
    verify_draw_reproduction,
)
from doin_core.plugins.base import hash_synthetic_data


def make_manifest(**overrides) -> GeneratorIdentityManifest:
    fields = {
        "object_kind": "generator_identity_manifest",
        "code_hash": "1" * 64,
        "weights_hash": "2" * 64,
        "config_hash": "3" * 64,
        "training_data_hashes": ("4" * 64, "5" * 64),
        "runtime_contract": "numpy-1.26-float64-strict",
        "dependency_lock_hash": "6" * 64,
    }
    fields.update(overrides)
    return GeneratorIdentityManifest(**fields)


def toy_generate(manifest: GeneratorIdentityManifest, seed: int) -> dict:
    """Deterministic toy generator keyed to the manifest AND the seed."""
    basis = f"{manifest.manifest_hash}:{seed}"
    digest = hashlib.sha256(basis.encode()).hexdigest()
    return {"series": [int(c, 16) for c in digest[:16]], "seed": seed}


def make_draw_evidence(
    manifest: GeneratorIdentityManifest,
    evaluator_id: str,
    seed_i: int,
) -> DrawCustodyEvidence:
    data = toy_generate(manifest, seed_i)
    return DrawCustodyEvidence(
        object_kind="draw_custody_evidence",
        challenge_data_hash=hash_synthetic_data(data),
        evaluator_id=evaluator_id,
        seed_i=seed_i,
        commitment_hash="commit-xyz",
        domain_id="dom-1",
        chain_anchor_hash="anchor-abc",
        derivation_contract_version="seed-derivation-v1",
        manifest_hash=manifest.manifest_hash,
    )


class TestGeneratorIdentityManifest:
    def test_manifest_hash_is_deterministic(self):
        assert make_manifest().manifest_hash == make_manifest().manifest_hash

    @pytest.mark.parametrize(
        "component, value",
        [
            ("code_hash", "f" * 64),
            ("weights_hash", "f" * 64),
            ("config_hash", "f" * 64),
            ("training_data_hashes", ("f" * 64,)),
            ("runtime_contract", "torch-2.3-float32"),
            ("dependency_lock_hash", "f" * 64),
        ],
    )
    def test_changing_any_component_changes_identity(self, component, value):
        """Changing code, weights, config, training data, runtime contract or
        dependency lock produces a DIFFERENT generator identity."""
        base = make_manifest()
        changed = make_manifest(**{component: value})
        assert base.manifest_hash != changed.manifest_hash

    def test_manifest_is_immutable(self):
        manifest = make_manifest()
        with pytest.raises(ValidationError):
            manifest.code_hash = "f" * 64

    def test_refuses_empty_training_data(self):
        with pytest.raises(ValidationError):
            make_manifest(training_data_hashes=())

    def test_refuses_malformed_component_hash(self):
        with pytest.raises(ValidationError):
            make_manifest(code_hash="deadbeef")


class TestTypedRefusal:
    """Doc 40 §3: a draw hash must NEVER substitute a generator identity."""

    def test_manifest_is_accepted(self):
        manifest = make_manifest()
        assert require_generator_identity(manifest) is manifest

    def test_draw_custody_evidence_is_refused(self):
        manifest = make_manifest()
        evidence = make_draw_evidence(manifest, "eval-a", 42)
        with pytest.raises(GeneratorIdentityRequired):
            require_generator_identity(evidence)

    def test_bare_hash_string_is_refused(self):
        """Even a well-formed 64-hex string is refused: a bare string cannot
        prove which KIND of object it addresses."""
        with pytest.raises(GeneratorIdentityRequired):
            require_generator_identity("a" * 64)

    def test_none_is_refused(self):
        with pytest.raises(GeneratorIdentityRequired):
            require_generator_identity(None)


class TestDrawReproduction:
    """Doc 40 §3: distinct draws, each reproducible from seed_i + manifest."""

    def test_distinct_evaluator_seeds_produce_distinct_reproducible_draws(self):
        manifest = make_manifest()
        policy = DeterministicSeedPolicy()
        seed_a = policy.get_seed_for_synthetic_data(
            "commit-xyz", "dom-1", "eval-a", "tip-1"
        )
        seed_b = policy.get_seed_for_synthetic_data(
            "commit-xyz", "dom-1", "eval-b", "tip-1"
        )
        assert seed_a != seed_b  # distinct draws by design

        ev_a = make_draw_evidence(manifest, "eval-a", seed_a)
        ev_b = make_draw_evidence(manifest, "eval-b", seed_b)
        assert ev_a.challenge_data_hash != ev_b.challenge_data_hash

        # Each draw is reproducible after the fact from seed_i + manifest.
        for ev in (ev_a, ev_b):
            assert verify_draw_reproduction(
                ev, manifest, toy_generate, hash_synthetic_data
            )

    def test_tampered_seed_fails_reproduction(self):
        manifest = make_manifest()
        evidence = make_draw_evidence(manifest, "eval-a", 42)
        tampered = evidence.model_copy(update={"seed_i": 43})
        assert not verify_draw_reproduction(
            tampered, manifest, toy_generate, hash_synthetic_data
        )

    def test_tampered_challenge_hash_fails_reproduction(self):
        manifest = make_manifest()
        evidence = make_draw_evidence(manifest, "eval-a", 42)
        tampered = evidence.model_copy(
            update={"challenge_data_hash": "f" * 64}
        )
        assert not verify_draw_reproduction(
            tampered, manifest, toy_generate, hash_synthetic_data
        )

    def test_evidence_bound_to_other_manifest_refuses(self):
        """Fails closed rather than regenerating from the wrong mechanism."""
        manifest = make_manifest()
        other = make_manifest(code_hash="f" * 64)
        evidence = make_draw_evidence(other, "eval-a", 42)
        with pytest.raises(GeneratorIdentityRequired):
            verify_draw_reproduction(
                evidence, manifest, toy_generate, hash_synthetic_data
            )

    def test_draw_evidence_is_immutable(self):
        manifest = make_manifest()
        evidence = make_draw_evidence(manifest, "eval-a", 42)
        with pytest.raises(ValidationError):
            evidence.seed_i = 99

    def test_two_objects_are_distinct_types(self):
        """The manifest and the draw evidence are two DISTINCT typed objects,
        distinguishable by construction — never by string convention."""
        manifest = make_manifest()
        evidence = make_draw_evidence(manifest, "eval-a", 42)
        assert manifest.object_kind == "generator_identity_manifest"
        assert evidence.object_kind == "draw_custody_evidence"
        assert not isinstance(evidence, GeneratorIdentityManifest)
        assert not isinstance(manifest, DrawCustodyEvidence)
