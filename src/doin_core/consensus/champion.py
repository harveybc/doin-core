"""Pure validation of accepted network-champion transitions.

Storage, archive resolution and model evaluation remain node responsibilities.
Two historical transactions (work and evidence) may describe one acceptance;
they must agree and do not constitute two improvements.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from doin_core.models import Block, TransactionType


@dataclass
class Acceptance:
    """Consensus metadata and evidence for a single optimizer proposal."""

    domain_id: str
    optimae_id: str
    optimizer_id: str
    performance: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)


def finite_score(value: Any) -> float:
    """Reject nonnumeric, boolean and nonfinite fitness values."""
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("INVALID_CHAMPION_SCORE")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError("INVALID_CHAMPION_SCORE") from exc
    if not math.isfinite(result):
        raise ValueError("INVALID_CHAMPION_SCORE")
    return result


def performance_gain(value: float, previous: float | None, higher_is_better: bool) -> float:
    """Measure directional improvement; retain legacy bootstrap work if no best exists."""
    value = finite_score(value)
    if previous is None:
        return abs(value)
    previous = finite_score(previous)
    gain = value - previous if higher_is_better else previous - value
    if gain <= 0:
        raise ValueError("CHAMPION_NOT_IMPROVED")
    return gain


def acceptance_records(block: Block) -> list[Acceptance]:
    """Join work/evidence transactions, rejecting contradictory or repeated data.

    This is a semantic projection, not structural block/hash validation.
    No archive I/O is performed and verified scores are never inferred from
    external raw candidate fitness.
    """
    records: dict[tuple[str, str], Acceptance] = {}
    shapes: dict[tuple[str, str], set[str]] = {}
    for tx in block.transactions:
        if tx.tx_type != TransactionType.OPTIMAE_ACCEPTED:
            continue
        ident = tx.payload.get("optimae_id")
        if not isinstance(ident, str) or not ident or not tx.domain_id or not tx.peer_id:
            raise ValueError("MISSING_ACCEPTANCE_IDENTITY")
        key = (tx.domain_id, ident)
        record = records.setdefault(key, Acceptance(tx.domain_id, ident, tx.peer_id))
        if record.optimizer_id != tx.peer_id:
            raise ValueError("ACCEPTANCE_ORIGINATOR_CONFLICT")
        shape = "work" if "performance" in tx.payload else "evidence"
        if shape in shapes.setdefault(key, set()):
            raise ValueError("DUPLICATE_ACCEPTANCE_RECORD")
        shapes[key].add(shape)
        for name in ("performance", "verified_performance"):
            if name in tx.payload:
                value = finite_score(tx.payload[name])
                if record.performance is not None and record.performance != value:
                    raise ValueError("ACCEPTANCE_SCORE_CONFLICT")
                record.performance = value
        for name, value in tx.payload.items():
            if name in record.payload and record.payload[name] != value:
                raise ValueError("ACCEPTANCE_PAYLOAD_CONFLICT")
            record.payload[name] = value
        for name in ("increment", "effective_increment"):
            if name in record.payload and finite_score(record.payload[name]) < 0:
                raise ValueError("INVALID_ACCEPTANCE_WORK")
        if ("increment" in record.payload and "effective_increment" in record.payload
                and record.payload["increment"] != record.payload["effective_increment"]):
            raise ValueError("ACCEPTANCE_WORK_CONFLICT")
    if any(record.performance is None for record in records.values()):
        raise ValueError("MISSING_SCORE")
    return list(records.values())


def advance_champions(
    block: Block,
    best: Mapping[str, float],
    seen: set[tuple[str, str]],
    higher_is_better: Mapping[str, bool],
) -> tuple[dict[str, float], set[tuple[str, str]]]:
    """Validate a block against its parent state, returning new copies only.

    The caller must supply the state of the actual parent branch, not a local
    uncommitted champion. Failure leaves both input collections unchanged.
    """
    updated, identities = dict(best), set(seen)
    for record in acceptance_records(block):
        domain = record.domain_id
        if domain not in higher_is_better:
            raise ValueError("UNKNOWN_DOMAIN")
        if record.optimizer_id != block.header.generator_id:
            raise ValueError("GENERATOR_NOT_ORIGINATOR")
        key = (domain, record.optimae_id)
        if key in identities:
            raise ValueError("REPEATED_OPTIMUM")
        value = finite_score(record.performance)
        previous = updated.get(domain)
        if previous is not None:
            previous = finite_score(previous)
            improves = value > previous if higher_is_better[domain] else value < previous
            if not improves:
                raise ValueError("CHAMPION_NOT_IMPROVED")
        updated[domain] = value
        identities.add(key)
    return updated, identities
