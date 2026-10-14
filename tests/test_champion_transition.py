"""Network champion transitions are checked independently of storage."""

import pytest

from doin_core.consensus.champion import acceptance_records, advance_champions, performance_gain
from doin_core.models import Block, BlockHeader, Transaction, TransactionType
from doin_core.crypto.hashing import compute_merkle_root


def candidate(score, ident="opt-1", peer="origin", generator="origin"):
    tx = Transaction(tx_type=TransactionType.OPTIMAE_ACCEPTED,
                     domain_id="d", peer_id=peer,
                     payload={"optimae_id": ident, "verified_performance": score,
                              "parameters": {"seed": 42}})
    return Block(header=BlockHeader(index=1, previous_hash="0" * 64,
                 merkle_root=compute_merkle_root([tx.id]), generator_id=generator,
                 weighted_performance_sum=0.1, threshold=0.01), transactions=[tx])


@pytest.mark.parametrize("higher,previous,next_score", [(False, -0.1, -0.2), (True, 0.1, 0.2)])
def test_strict_improvement(higher, previous, next_score):
    best, seen = advance_champions(candidate(next_score), {"d": previous}, set(), {"d": higher})
    assert best == {"d": next_score}
    assert seen == {("d", "opt-1")}


@pytest.mark.parametrize("score", [-0.1, 0, 0.3, float("nan"), float("inf"), True])
def test_reject_nonimprovement_and_invalid_numbers(score):
    with pytest.raises(ValueError):
        advance_champions(candidate(score), {"d": -0.1}, set(), {"d": False})


def test_duplicate_rejected_without_mutating_state():
    best, seen = {"d": -0.1}, {("d", "opt-1")}
    with pytest.raises(ValueError):
        advance_champions(candidate(-0.2), best, seen, {"d": False})
    assert best == {"d": -0.1} and seen == {("d", "opt-1")}


def test_remote_mint_rejected():
    with pytest.raises(ValueError, match="ORIGINATOR"):
        advance_champions(candidate(-0.2, generator="receiver"), {}, set(), {"d": False})


def test_pair_is_one_acceptance_and_conflicting_score_is_rejected():
    block = candidate(-0.2)
    companion = Transaction(tx_type=TransactionType.OPTIMAE_ACCEPTED, domain_id="d",
                            peer_id="origin", payload={"optimae_id": "opt-1", "performance": -0.2, "increment": 0.1})
    block.transactions.insert(0, companion)
    assert len(acceptance_records(block)) == 1
    companion.payload["performance"] = -0.3
    with pytest.raises(ValueError, match="SCORE_CONFLICT"):
        acceptance_records(block)


def test_unknown_domain_and_absent_score_rejected():
    with pytest.raises(ValueError, match="UNKNOWN_DOMAIN"):
        advance_champions(candidate(-0.2), {}, set(), {})
    block = candidate(-0.2)
    block.transactions[0].payload.pop("verified_performance")
    with pytest.raises(ValueError, match="MISSING_SCORE"):
        acceptance_records(block)


def test_duplicate_full_record_rejected():
    block = candidate(-0.2)
    block.transactions.append(block.transactions[0].model_copy(deep=True))
    with pytest.raises(ValueError):
        acceptance_records(block)


@pytest.mark.parametrize("previous,value,higher", [(-0.2, -0.3, False), (0.2, 0.3, True)])
def test_work_measures_improvement_not_absolute_fitness(previous, value, higher):
    assert performance_gain(value, previous, higher) == pytest.approx(0.1)
    with pytest.raises(ValueError):
        performance_gain(previous, value, higher)


def test_verified_zero_is_not_replaced_by_reported_score():
    from doin_core.consensus import ProofOfOptimization
    from doin_core.models import Domain, DomainConfig, Optimae

    consensus = ProofOfOptimization()
    consensus.register_domain(Domain(id="d", name="d", performance_metric="mae",
                                     config=DomainConfig(optimization_plugin="fixture",
                                                         inference_plugin="fixture")))
    consensus.record_optimae(Optimae(domain_id="d", optimizer_id="origin",
                                    reported_performance=0.1, verified_performance=0.0,
                                    performance_increment=0.1, parameters={"seed": 42}))
    assert consensus.state.pending_transactions[0].payload["performance"] == 0.0


def test_fork_work_counts_paired_acceptance_once():
    from doin_core.consensus.fork_choice import ForkChoiceRule

    tx = {"tx_type": "optimae_accepted", "domain_id": "d", "peer_id": "origin",
          "payload": {"optimae_id": "opt", "effective_increment": 10}}
    score = ForkChoiceRule().score_chain("hash", 2, [{"height": 1, "transactions": [tx, tx]}])
    assert score.cumulative_increment == 10
    assert score.optimae_accepted_count == 1


def test_fork_work_rejects_conflicting_duplicate():
    from doin_core.consensus.fork_choice import ForkChoiceRule

    def tx(work):
        return {"tx_type": "optimae_accepted", "domain_id": "d", "peer_id": "origin",
                "payload": {"optimae_id": "opt", "effective_increment": work}}
    with pytest.raises(ValueError):
        ForkChoiceRule().score_chain("hash", 2, [{"height": 1, "transactions": [tx(10), tx(20)]}])


def test_non_genesis_block_requires_an_accepted_improvement():
    block = candidate(-0.2)
    block.transactions.clear()
    with pytest.raises(ValueError, match="BLOCK_WITHOUT_CHAMPION_IMPROVEMENT"):
        advance_champions(block, {}, set(), {"d": False})


@pytest.mark.parametrize("field", ["effective_increment", "increment"])
def test_forged_work_cannot_buy_a_heavier_fork(field):
    block = candidate(-0.100000001)
    block.transactions[0].payload[field] = 1e12
    with pytest.raises(ValueError, match="ACCEPTANCE_WORK_EXCEEDS_IMPROVEMENT"):
        advance_champions(block, {"d": -0.1}, set(), {"d": False})


def test_header_cannot_invent_work_after_a_small_real_improvement():
    block = candidate(-0.100000001)
    block.header.weighted_performance_sum = 1e12
    with pytest.raises(ValueError, match="BLOCK_WORK_EXCEEDS_IMPROVEMENT"):
        advance_champions(block, {"d": -0.1}, set(), {"d": False})


def test_raw_work_must_equal_the_actual_champion_increment():
    block = candidate(-0.2)
    block.transactions[0].payload['raw_increment'] = 0.2
    with pytest.raises(ValueError, match="ACCEPTANCE_RAW_WORK_MISMATCH"):
        advance_champions(block, {"d": -0.1}, set(), {"d": False})


def test_configured_incentives_and_domain_weight_keep_their_existing_effect():
    block = candidate(-0.3)
    block.transactions[0].payload.update(raw_increment=0.2, effective_increment=0.26)
    block.header.weighted_performance_sum = 0.13
    advance_champions(block, {'d': -0.1}, set(), {'d': False},
                      max_work_multipliers={'d': 1.3}, domain_weights={'d': 0.5})
