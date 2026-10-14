"""Canonical incentive replay rejects work and header claims inside the old cap."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from doin_core.consensus.champion_work import derive_work, validate_work
from doin_core.crypto.hashing import compute_merkle_root
from doin_core.models import Block, BlockHeader, Transaction, TransactionType


POLICY = {'d': dict(weight=1.0, has_synthetic_data=False, higher_is_better=False,
                    incentive={'higher_is_better': False})}


def mint(parents, value, ident):
    timestamp = max(1000.0, parents[-1].header.timestamp.timestamp() + 10)
    proof = derive_work(parents, POLICY, domain_id='d', optimizer_id='origin',
                        verified=value, reported=value, timestamp=timestamp)
    tx = Transaction(tx_type=TransactionType.OPTIMAE_ACCEPTED, domain_id='d', peer_id='origin',
                     payload=dict(optimae_id=ident, verified_performance=value, work_proof=proof,
                                  raw_increment=proof['raw_increment'],
                                  effective_increment=proof['effective_increment'],
                                  reward_fraction=proof['reward_fraction']))
    return Block(header=BlockHeader(index=len(parents), previous_hash=parents[-1].hash,
                  timestamp=datetime.fromtimestamp(timestamp + 1, timezone.utc), generator_id='origin',
                  weighted_performance_sum=proof['effective_increment'], threshold=1e-8,
                  merkle_root=compute_merkle_root([tx.id])), transactions=[tx])


def test_canonical_parent_replay_and_incentive_formulas():
    parents = [Block.genesis()]
    first = mint(parents, -0.1, 'first')
    validate_work(first, parents, POLICY)
    second = mint(parents + [first], -0.2, 'second')
    validate_work(second, parents + [first], POLICY)
    assert second.transactions[0].payload['work_proof']['reputation_factor'] > first.transactions[0].payload['work_proof']['reputation_factor']


@pytest.mark.parametrize('key', ['effective_increment', 'reputation_factor', 'domain_weight', 'reward_fraction', 'raw_increment'])
def test_within_cap_proof_forgery_is_rejected(key):
    parents = [Block.genesis()]
    block = mint(parents, -0.1, 'first')
    block.transactions[0].payload['work_proof'][key] *= 1.01
    with pytest.raises(ValueError, match='WORK_PROOF_MISMATCH'):
        validate_work(block, parents, POLICY)


def test_header_must_equal_verified_effective_work():
    parents = [Block.genesis()]
    block = mint(parents, -0.1, 'first')
    block.header.weighted_performance_sum *= 1.01
    with pytest.raises(ValueError, match='BLOCK_WORK_MISMATCH'):
        validate_work(block, parents, POLICY)


def test_missing_raw_proof_is_rejected():
    parents = [Block.genesis()]
    block = mint(parents, -0.1, 'first')
    del block.transactions[0].payload['raw_increment']
    with pytest.raises(ValueError, match='WORK_PAYLOAD_MISMATCH'):
        validate_work(block, parents, POLICY)
