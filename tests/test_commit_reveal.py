"""Tests for the Commit-Reveal scheme."""

import time

from doin_core.models.commit_reveal import (
    Commitment,
    CommitRevealManager,
    Reveal,
    compute_commitment,
    verify_commitment,
)


class TestCommitReveal:
    def test_compute_commitment_deterministic(self):
        params = {"learning_rate": 0.001, "layers": 3}
        nonce = "abc123"
        h1 = compute_commitment(params, nonce)
        h2 = compute_commitment(params, nonce)
        assert h1 == h2

    def test_different_nonce_different_hash(self):
        params = {"learning_rate": 0.001}
        h1 = compute_commitment(params, "nonce1")
        h2 = compute_commitment(params, "nonce2")
        assert h1 != h2

    def test_verify_commitment_correct(self):
        params = {"x": 1.0}
        nonce = "secret"
        h = compute_commitment(params, nonce)
        assert verify_commitment(h, params, nonce)

    def test_verify_commitment_wrong_nonce(self):
        params = {"x": 1.0}
        h = compute_commitment(params, "correct")
        assert not verify_commitment(h, params, "wrong")

    def test_verify_commitment_wrong_params(self):
        params = {"x": 1.0}
        h = compute_commitment(params, "nonce")
        assert not verify_commitment(h, {"x": 2.0}, "nonce")


class TestCommitRevealManager:
    def test_full_flow(self):
        mgr = CommitRevealManager(max_commit_age=60.0)
        params = {"lr": 0.001}
        nonce = "secret123"
        h = compute_commitment(params, nonce)

        # Phase 1: Commit
        commitment = Commitment(
            commitment_hash=h,
            domain_id="test",
            optimizer_id="opt-1",
        )
        assert mgr.add_commitment(commitment)
        assert mgr.pending_count == 1

        # Phase 2: Reveal
        reveal = Reveal(
            commitment_hash=h,
            domain_id="test",
            optimizer_id="opt-1",
            parameters=params,
            nonce=nonce,
            reported_performance=-0.5,
        )
        assert mgr.process_reveal(reveal)
        assert mgr.pending_count == 0  # Revealed

    def test_duplicate_commitment_rejected(self):
        mgr = CommitRevealManager()
        c = Commitment(commitment_hash="abc", domain_id="test", optimizer_id="opt-1")
        assert mgr.add_commitment(c)
        assert not mgr.add_commitment(c)  # Duplicate

    def test_reveal_without_commitment_rejected(self):
        mgr = CommitRevealManager()
        reveal = Reveal(
            commitment_hash="nonexistent",
            domain_id="test",
            optimizer_id="opt-1",
            parameters={},
            nonce="x",
            reported_performance=0,
        )
        assert not mgr.process_reveal(reveal)

    def test_double_reveal_rejected(self):
        mgr = CommitRevealManager()
        params = {"x": 1}
        nonce = "n"
        h = compute_commitment(params, nonce)

        mgr.add_commitment(Commitment(commitment_hash=h, domain_id="t", optimizer_id="o"))

        reveal = Reveal(
            commitment_hash=h, domain_id="t", optimizer_id="o",
            parameters=params, nonce=nonce, reported_performance=0,
        )
        assert mgr.process_reveal(reveal)
        assert not mgr.process_reveal(reveal)  # Already revealed

    def test_wrong_optimizer_rejected(self):
        mgr = CommitRevealManager()
        params = {"x": 1}
        nonce = "n"
        h = compute_commitment(params, nonce)

        mgr.add_commitment(Commitment(commitment_hash=h, domain_id="t", optimizer_id="opt-1"))

        reveal = Reveal(
            commitment_hash=h, domain_id="t", optimizer_id="opt-2",  # Wrong!
            parameters=params, nonce=nonce, reported_performance=0,
        )
        assert not mgr.process_reveal(reveal)

    def test_expired_commitment_rejected(self):
        mgr = CommitRevealManager(max_commit_age=1.0)
        params = {"x": 1}
        nonce = "n"
        h = compute_commitment(params, nonce)

        c = Commitment(commitment_hash=h, domain_id="t", optimizer_id="o")
        c.timestamp = time.time() - 10.0  # 10 seconds ago, but max age is 1
        mgr.add_commitment(c)

        reveal = Reveal(
            commitment_hash=h, domain_id="t", optimizer_id="o",
            parameters=params, nonce=nonce, reported_performance=0,
        )
        assert not mgr.process_reveal(reveal)

    def test_wrong_hash_rejected(self):
        mgr = CommitRevealManager()
        params = {"x": 1}
        nonce = "correct_nonce"
        h = compute_commitment(params, nonce)

        mgr.add_commitment(Commitment(commitment_hash=h, domain_id="t", optimizer_id="o"))

        # Reveal with different params (hash won't match)
        reveal = Reveal(
            commitment_hash=h, domain_id="t", optimizer_id="o",
            parameters={"x": 999}, nonce=nonce, reported_performance=0,
        )
        assert not mgr.process_reveal(reveal)

    def test_cleanup_expired(self):
        mgr = CommitRevealManager(max_commit_age=0.01)
        h = compute_commitment({"x": 1}, "n")
        c = Commitment(commitment_hash=h, domain_id="t", optimizer_id="o")
        c.timestamp = time.time() - 1.0
        mgr._commitments[h] = c

        removed = mgr.cleanup_expired()
        assert removed == 1
        assert mgr.pending_count == 0
