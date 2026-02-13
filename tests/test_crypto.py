"""Tests for cryptographic utilities."""

import tempfile
from pathlib import Path

from doin_core.crypto import PeerIdentity, compute_merkle_root


class TestPeerIdentity:
    def test_generate(self) -> None:
        identity = PeerIdentity.generate()
        assert len(identity.peer_id) == 40
        assert identity.public_key is not None

    def test_sign_and_verify(self) -> None:
        identity = PeerIdentity.generate()
        data = b"test message"
        signature = identity.sign(data)
        assert identity.verify(signature, data)

    def test_verify_wrong_data(self) -> None:
        identity = PeerIdentity.generate()
        signature = identity.sign(b"correct data")
        assert not identity.verify(signature, b"wrong data")

    def test_save_and_load(self) -> None:
        identity = PeerIdentity.generate()
        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "key.pem"
            identity.save(key_path)
            loaded = PeerIdentity.from_file(key_path)
            assert loaded.peer_id == identity.peer_id

    def test_unique_identities(self) -> None:
        id1 = PeerIdentity.generate()
        id2 = PeerIdentity.generate()
        assert id1.peer_id != id2.peer_id


class TestMerkleRoot:
    def test_empty(self) -> None:
        assert compute_merkle_root([]) == "0" * 64

    def test_single_hash(self) -> None:
        h = "a" * 64
        assert compute_merkle_root([h]) == h

    def test_two_hashes(self) -> None:
        root = compute_merkle_root(["a" * 64, "b" * 64])
        assert len(root) == 64
        assert root != "a" * 64

    def test_deterministic(self) -> None:
        hashes = ["a" * 64, "b" * 64, "c" * 64]
        r1 = compute_merkle_root(hashes)
        r2 = compute_merkle_root(hashes)
        assert r1 == r2
