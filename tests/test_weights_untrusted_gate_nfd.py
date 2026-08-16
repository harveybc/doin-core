"""NOT-FOR-DEPLOYMENT — opt-in zero-authority gate for unverified domains.

Behavior-changing candidate isolated per Musashi order §5: correcting
contradictions 2/5 (weights.py 0.5 fallback vs 'no generator means zero')
changes deployed consensus, so the change ships as an OPT-IN flag with the
legacy default preserved.  Flipping the default is an owner/auditor
decision; nothing in this commit is deployed.

These tests verify BOTH sides:
* default (deployed prototype) behavior is byte-for-byte unchanged; and
* the opt-in flag implements the doc 40 §2.2 / doc 39 §8 target: zero
  challenge authority without an admitted generator.
"""

from __future__ import annotations

from doin_core.consensus.weights import VerifiedUtilityWeights, WeightConfig


def test_nfd_default_preserves_legacy_half_fallback():
    """The deployed prototype behavior MUST remain the default."""
    vuw = VerifiedUtilityWeights()  # no config: legacy path
    vuw.register_domain("dom-1", base_weight=1.0, has_synthetic_data=False)
    assert vuw.compute_weights()["dom-1"] == 0.5
    assert not vuw.config.untrusted_gate_zero_authority


def test_nfd_opt_in_grants_zero_authority_without_generator():
    """Doc 39 §8: absence of an admitted generator means zero authority."""
    vuw = VerifiedUtilityWeights(WeightConfig(untrusted_gate_zero_authority=True))
    vuw.register_domain("dom-1", base_weight=1.0, has_synthetic_data=False)
    assert vuw.compute_weights()["dom-1"] == 0.0

    effective = vuw.get_effective_increment(
        "dom-1", raw_increment=2.5, contributor_reputation=10.0
    )
    assert effective == 0.0, (
        "under the gate, an unverified domain contributes NOTHING to the "
        "block-generation threshold"
    )


def test_nfd_opt_in_keeps_verified_domains_at_full_strength():
    vuw = VerifiedUtilityWeights(WeightConfig(untrusted_gate_zero_authority=True))
    vuw.register_domain("dom-v", base_weight=1.0, has_synthetic_data=True)
    vuw.register_domain("dom-u", base_weight=1.0, has_synthetic_data=False)
    weights = vuw.compute_weights()
    assert weights["dom-v"] > 0.0
    assert weights["dom-u"] == 0.0
