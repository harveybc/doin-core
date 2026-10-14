"""Deterministic incentive replay from committed optimization evidence."""

from __future__ import annotations

import math
from typing import Mapping, Sequence

from doin_core.consensus.champion import acceptance_records, finite_score, performance_gain
from doin_core.consensus.incentives import IncentiveConfig, evaluate_verification_incentive
from doin_core.consensus.weights import VerifiedUtilityWeights
from doin_core.models import Block
from doin_core.models.reputation import (
    DECAY_HALF_LIFE_SECONDS, PENALTY_OPTIMAE_REJECTED,
    PENALTY_EVALUATION_DIVERGENT, REWARD_OPTIMAE_ACCEPTED,
    REWARD_EVALUATION_COMPLETED, REWARD_EVALUATION_AGREED_WITH_QUORUM,
)


def derive_work(blocks: Sequence[Block], domains: Mapping[str, dict], *, domain_id: str,
                optimizer_id: str, verified: float, reported: float, timestamp: float) -> dict:
    """Replay parent history, counting paired acceptances once, then this proposal.

    ``timestamp`` is committed in the proof, not the receiver's wall clock.
    Utility weights and reputation retain the existing formulas; private,
    uncommitted observations cannot contribute to their consensus values.
    """
    if not math.isfinite(timestamp):
        raise ValueError('WORK_TIMESTAMP_INVALID')
    verified, reported = finite_score(verified), finite_score(reported)
    weights = VerifiedUtilityWeights()
    for ident, policy in domains.items():
        weights.register_domain(ident, base_weight=policy['weight'],
                                has_synthetic_data=policy['has_synthetic_data'])
    best = {}
    scores: dict[str, tuple[float, float]] = {}

    def reward(peer, when, amount, penalty=False):
        old, last = scores.get(peer, (0.0, when))
        if when < last:
            raise ValueError('WORK_HISTORY_TIME_REVERSED')
        old *= math.pow(0.5, (when - last) / DECAY_HALF_LIFE_SECONDS)
        scores[peer] = (max(0.0, old - amount) if penalty else old + amount, when)

    for block in blocks:
        accepted = acceptance_records(block)
        for record in accepted:
            when = block.header.timestamp.timestamp()
            reward(record.optimizer_id, when, REWARD_OPTIMAE_ACCEPTED)
            best[record.domain_id] = record.performance
            work = record.payload.get('effective_increment', record.payload.get('increment', 0.0))
            weights.update_from_block([dict(tx_type='optimae_accepted', domain_id=record.domain_id,
                                            payload={'increment': work})])
        other = []
        for tx in block.transactions:
            kind = tx.tx_type.value
            if kind == 'optimae_accepted':
                continue
            other.append(dict(tx_type=kind, domain_id=tx.domain_id, payload=tx.payload))
            when = block.header.timestamp.timestamp()
            if kind == 'optimae_rejected':
                reward(tx.peer_id, when, PENALTY_OPTIMAE_REJECTED, True)
            elif kind == 'task_completed':
                agreed = tx.payload.get('agreed_with_quorum', True)
                reward(tx.peer_id, when, REWARD_EVALUATION_COMPLETED + REWARD_EVALUATION_AGREED_WITH_QUORUM
                       if agreed else PENALTY_EVALUATION_DIVERGENT, not agreed)
        weights.update_from_block(other)
    # Same accepted-proposal reward as the existing mint path, at its pinned time.
    reward(optimizer_id, timestamp, REWARD_OPTIMAE_ACCEPTED)
    score = scores[optimizer_id][0]
    factor = min(1.0, math.log1p(score) / math.log1p(10.0)) if score > 0 else 0.0
    policy = domains[domain_id]
    raw = performance_gain(verified, best.get(domain_id), policy['higher_is_better'])
    weight = weights.compute_weights()[domain_id]
    result = evaluate_verification_incentive(reported, verified, raw, weight, factor,
                                             IncentiveConfig(**policy['incentive']))
    return dict(schema='doin.champion_work.v1', timestamp=timestamp, raw_increment=raw,
                reported_performance=reported, verified_performance=verified,
                domain_weight=weight, reputation_factor=factor,
                reward_fraction=result.reward_fraction, effective_increment=result.effective_increment)


def validate_work(block: Block, parents: Sequence[Block], domains: Mapping[str, dict]) -> None:
    """Require exact replay of every accepted work proof and the block's work sum."""
    virtual = list(parents)
    prior_records = []
    total = 0.0
    lower_time = parents[-1].header.timestamp.timestamp() if parents else 0.0
    upper_time = block.header.timestamp.timestamp()
    for record in acceptance_records(block):
        proof = record.payload.get('work_proof')
        if not isinstance(proof, dict) or proof.get('schema') != 'doin.champion_work.v1':
            raise ValueError('CHAMPION_WORK_PROOF_REQUIRED')
        if set(proof) != {'schema', 'timestamp', 'raw_increment', 'reported_performance',
                          'verified_performance', 'domain_weight', 'reputation_factor',
                          'reward_fraction', 'effective_increment'}:
            raise ValueError('CHAMPION_WORK_PROOF_FIELDS')
        when = proof.get('timestamp')
        if isinstance(when, bool) or not isinstance(when, (int, float)) or not lower_time <= when <= upper_time:
            raise ValueError('WORK_TIMESTAMP_OUTSIDE_PARENT_BLOCK')
        expected = derive_work(virtual, domains, domain_id=record.domain_id,
                               optimizer_id=record.optimizer_id, verified=record.performance,
                               reported=proof['reported_performance'], timestamp=when)
        if set(expected) != set(proof):
            raise ValueError('CHAMPION_WORK_PROOF_FIELDS')
        for key, value in expected.items():
            observed = proof[key]
            if key == 'schema':
                continue
            if isinstance(observed, bool) or not isinstance(observed, (int, float)) or not math.isclose(
                    value, observed, rel_tol=1e-12, abs_tol=0):
                raise ValueError('CHAMPION_WORK_PROOF_MISMATCH: ' + key)
        for key in ('raw_increment', 'effective_increment', 'reward_fraction'):
            if key not in record.payload or not math.isclose(finite_score(record.payload[key]), expected[key], rel_tol=1e-12, abs_tol=0):
                raise ValueError('CHAMPION_WORK_PAYLOAD_MISMATCH: ' + key)
        total += expected['effective_increment'] * domains[record.domain_id]['weight']
        prior_records.extend(tx for tx in block.transactions
                             if tx.payload.get('optimae_id') == record.optimae_id and tx.domain_id == record.domain_id)
        from datetime import datetime, timezone
        header = block.header.model_copy(update={'timestamp': datetime.fromtimestamp(when, timezone.utc)})
        virtual = list(parents) + [block.model_copy(update={'header': header, 'transactions': list(prior_records)})]
        lower_time = when
    if not math.isclose(total, block.header.weighted_performance_sum, rel_tol=1e-12, abs_tol=0):
        raise ValueError('CHAMPION_BLOCK_WORK_MISMATCH')
