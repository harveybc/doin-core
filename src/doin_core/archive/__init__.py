"""Versioned, deterministic archive documents for an existing DOIN block.

Serialization only. Persistence lives in the node shadow adapter.
"""

from doin_core.archive.body import (
    BODY_SCHEMA,
    DIGEST_IDENTITY,
    MANIFEST_SCHEMA,
    UNANCHORED_SCHEMA,
    ArchiveEnvelope,
    ArchiveRefusal,
    Section,
    VerifiedArchive,
    build_archive,
    canonical_bytes,
    digest_bytes,
    verify_archive_bytes,
    verify_envelope,
)

__all__ = [
    "BODY_SCHEMA",
    "DIGEST_IDENTITY",
    "MANIFEST_SCHEMA",
    "UNANCHORED_SCHEMA",
    "ArchiveEnvelope",
    "ArchiveRefusal",
    "Section",
    "VerifiedArchive",
    "build_archive",
    "canonical_bytes",
    "digest_bytes",
    "verify_archive_bytes",
    "verify_envelope",
]
