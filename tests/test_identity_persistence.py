"""Tests for PeerIdentity persistence (load_or_generate)."""

import os
import tempfile
from pathlib import Path

import pytest

from doin_core.crypto.identity import PeerIdentity


class TestIdentityPersistence:

    def test_generate_and_save(self, tmp_path):
        key_file = tmp_path / "identity.pem"
        identity = PeerIdentity.load_or_generate(key_file)
        assert key_file.exists()
        assert len(identity.peer_id) == 40

    def test_load_existing(self, tmp_path):
        key_file = tmp_path / "identity.pem"
        id1 = PeerIdentity.load_or_generate(key_file)
        id2 = PeerIdentity.load_or_generate(key_file)
        assert id1.peer_id == id2.peer_id

    def test_different_files_different_ids(self, tmp_path):
        id1 = PeerIdentity.load_or_generate(tmp_path / "a.pem")
        id2 = PeerIdentity.load_or_generate(tmp_path / "b.pem")
        assert id1.peer_id != id2.peer_id

    def test_file_permissions(self, tmp_path):
        key_file = tmp_path / "identity.pem"
        PeerIdentity.load_or_generate(key_file)
        mode = oct(key_file.stat().st_mode & 0o777)
        assert mode == "0o600"

    def test_creates_parent_dirs(self, tmp_path):
        key_file = tmp_path / "deep" / "nested" / "identity.pem"
        identity = PeerIdentity.load_or_generate(key_file)
        assert key_file.exists()
        assert len(identity.peer_id) == 40

    def test_signing_persists(self, tmp_path):
        key_file = tmp_path / "identity.pem"
        id1 = PeerIdentity.load_or_generate(key_file)
        data = b"test message"
        sig = id1.sign(data)

        id2 = PeerIdentity.load_or_generate(key_file)
        assert id2.verify(sig, data)

    def test_save_then_from_file(self, tmp_path):
        key_file = tmp_path / "identity.pem"
        id1 = PeerIdentity.generate()
        id1.save(key_file)
        id2 = PeerIdentity.from_file(key_file)
        assert id1.peer_id == id2.peer_id

    def test_corrupt_file_raises(self, tmp_path):
        key_file = tmp_path / "identity.pem"
        key_file.write_text("not a pem file")
        with pytest.raises(Exception):
            PeerIdentity.from_file(key_file)
