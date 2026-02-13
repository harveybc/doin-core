"""Tests for finality checkpoints and external anchoring."""

from doin_core.consensus.finality import (
    ExternalAnchorManager,
    FinalityManager,
)


class TestFinalityManager:
    def test_initial_finalized_height(self):
        fm = FinalityManager()
        assert fm.finalized_height == -1

    def test_explicit_checkpoint(self):
        fm = FinalityManager()
        cp = fm.add_checkpoint(10, "hash10", source="explicit")
        assert fm.finalized_height == 10
        assert cp.block_hash == "hash10"

    def test_cannot_checkpoint_below_existing(self):
        fm = FinalityManager()
        fm.add_checkpoint(10, "h10")
        try:
            fm.add_checkpoint(5, "h5")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_implicit_checkpoint_on_new_block(self):
        fm = FinalityManager(confirmation_depth=3)
        # Chain reaches height 5, block at depth 3 is height 2
        cp = fm.on_new_block(chain_height=5, block_hash_at_depth="hash2")
        assert cp is not None
        assert cp.block_height == 2
        assert cp.source == "implicit"
        assert fm.finalized_height == 2

    def test_no_implicit_checkpoint_when_chain_too_short(self):
        fm = FinalityManager(confirmation_depth=6)
        cp = fm.on_new_block(chain_height=3, block_hash_at_depth=None)
        assert cp is None

    def test_no_duplicate_implicit_checkpoint(self):
        fm = FinalityManager(confirmation_depth=3)
        fm.on_new_block(5, "hash2")
        # Same height shouldn't create another checkpoint
        cp = fm.on_new_block(5, "hash2")
        assert cp is None

    def test_reorg_allowed_above_finality(self):
        fm = FinalityManager()
        fm.add_checkpoint(10, "h10")
        assert fm.is_reorg_allowed(reorg_depth=3, chain_height=20)  # Reorg to 17, above 10

    def test_reorg_blocked_below_finality(self):
        fm = FinalityManager()
        fm.add_checkpoint(10, "h10")
        assert not fm.is_reorg_allowed(reorg_depth=15, chain_height=20)  # Reorg to 5, below 10

    def test_validate_block_ancestry_matches(self):
        fm = FinalityManager()
        fm.add_checkpoint(10, "correct_hash")
        assert fm.validate_block_ancestry(10, "correct_hash")

    def test_validate_block_ancestry_mismatch(self):
        fm = FinalityManager()
        fm.add_checkpoint(10, "correct_hash")
        assert not fm.validate_block_ancestry(10, "wrong_hash")

    def test_validate_block_ancestry_different_height(self):
        fm = FinalityManager()
        fm.add_checkpoint(10, "h10")
        # Height 11 — no checkpoint exists, should be fine
        assert fm.validate_block_ancestry(11, "any_hash")

    def test_multiple_checkpoints(self):
        fm = FinalityManager()
        fm.add_checkpoint(10, "h10")
        fm.add_checkpoint(20, "h20")
        assert fm.finalized_height == 20
        assert len(fm.all_checkpoints) == 2


class TestExternalAnchorManager:
    def test_should_anchor_at_interval(self):
        eam = ExternalAnchorManager(anchor_interval_blocks=100)
        assert not eam.should_anchor(0)
        assert not eam.should_anchor(50)
        assert eam.should_anchor(100)
        assert eam.should_anchor(200)

    def test_create_anchor(self):
        eam = ExternalAnchorManager()
        anchor = eam.create_anchor(100, "block_hash", "state_hash")
        assert anchor.block_height == 100
        assert eam.latest_anchor is not None

    def test_record_publication(self):
        eam = ExternalAnchorManager()
        eam.create_anchor(100, "bh", "sh")
        ok = eam.record_publication(100, "btc_tx_123", "bitcoin")
        assert ok
        assert eam.latest_anchor.external_tx_id == "btc_tx_123"

    def test_verify_chain_matches(self):
        eam = ExternalAnchorManager()
        eam.create_anchor(100, "bh", "sh")
        assert eam.verify_chain_against_anchor(100, "bh", "sh") is True

    def test_verify_chain_diverges(self):
        eam = ExternalAnchorManager()
        eam.create_anchor(100, "bh", "sh")
        assert eam.verify_chain_against_anchor(100, "wrong", "sh") is False

    def test_verify_no_anchor(self):
        eam = ExternalAnchorManager()
        assert eam.verify_chain_against_anchor(100, "bh", "sh") is None

    def test_compute_chain_state_hash(self):
        eam = ExternalAnchorManager()
        h1 = eam.compute_chain_state_hash(["a", "b", "c"])
        h2 = eam.compute_chain_state_hash(["a", "b", "c"])
        h3 = eam.compute_chain_state_hash(["a", "b", "d"])
        assert h1 == h2
        assert h1 != h3
