"""Peer identity management — key generation and signing."""

from __future__ import annotations

import hashlib
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDSA,
    EllipticCurvePrivateKey,
    EllipticCurvePublicKey,
)


class PeerIdentity:
    """Manages a peer's cryptographic identity.

    Uses ECDSA with SECP256R1 for signing. The peer ID is derived
    from the SHA-256 hash of the public key.
    """

    def __init__(self, private_key: EllipticCurvePrivateKey) -> None:
        self._private_key = private_key
        self._public_key = private_key.public_key()
        self._peer_id = self._compute_peer_id()

    @classmethod
    def generate(cls) -> PeerIdentity:
        """Generate a new random identity."""
        private_key = ec.generate_private_key(ec.SECP256R1())
        return cls(private_key)

    @classmethod
    def from_file(cls, path: str | Path) -> PeerIdentity:
        """Load identity from a PEM private key file."""
        path = Path(path)
        key_data = path.read_bytes()
        private_key = serialization.load_pem_private_key(key_data, password=None)
        if not isinstance(private_key, EllipticCurvePrivateKey):
            msg = "Key file must contain an EC private key"
            raise TypeError(msg)
        return cls(private_key)

    @classmethod
    def load_or_generate(cls, path: str | Path) -> PeerIdentity:
        """Load identity from file if it exists, otherwise generate and save.

        This is the recommended way to initialize identity — ensures the
        same peer ID persists across restarts.
        """
        path = Path(path)
        if path.exists():
            identity = cls.from_file(path)
        else:
            identity = cls.generate()
            identity.save(path)
            # Restrict permissions (owner read/write only)
            path.chmod(0o600)
        return identity

    def save(self, path: str | Path) -> None:
        """Save the private key to a PEM file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        key_bytes = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        path.write_bytes(key_bytes)

    @property
    def peer_id(self) -> str:
        """The peer's unique identifier (hex-encoded hash of public key)."""
        return self._peer_id

    @property
    def public_key(self) -> EllipticCurvePublicKey:
        """The peer's public key."""
        return self._public_key

    def sign(self, data: bytes) -> bytes:
        """Sign data with the peer's private key."""
        return self._private_key.sign(data, ECDSA(hashes.SHA256()))

    def verify(self, signature: bytes, data: bytes) -> bool:
        """Verify a signature against data using this peer's public key."""
        try:
            self._public_key.verify(signature, data, ECDSA(hashes.SHA256()))
            return True
        except Exception:
            return False

    @staticmethod
    def verify_with_public_key(
        public_key: EllipticCurvePublicKey,
        signature: bytes,
        data: bytes,
    ) -> bool:
        """Verify a signature using an arbitrary public key."""
        try:
            public_key.verify(signature, data, ECDSA(hashes.SHA256()))
            return True
        except Exception:
            return False

    def _compute_peer_id(self) -> str:
        """Derive peer ID from public key."""
        pub_bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return hashlib.sha256(pub_bytes).hexdigest()[:40]
