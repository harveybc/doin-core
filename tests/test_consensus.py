"""Tests for proof-of-optimization consensus."""

from doin_core.consensus import ProofOfOptimization
from doin_core.models import Block, Domain, DomainConfig, Optimae


def _make_domain(domain_id: str = "d1", weight: float = 1.0) -> Domain:
    return Domain(
        id=domain_id,
        name=f"Test Domain {domain_id}",
        performance_metric="accuracy",
        higher_is_better=True,
        weight=weight,
        config=DomainConfig(
            optimization_plugin="test_opt",
            inference_plugin="test_inf",
        ),
    )


def _make_optimae(
    domain_id: str = "d1",
    performance: float = 0.9,
    increment: float = 0.1,
) -> Optimae:
    return Optimae(
        domain_id=domain_id,
        optimizer_id="optimizer-1",
        parameters={"w": [1, 2, 3]},
        reported_performance=performance,
        performance_increment=increment,
        accepted=True,
    )


class TestProofOfOptimization:
    def test_initial_state(self) -> None:
        poo = ProofOfOptimization(initial_threshold=1.0)
        assert poo.weighted_sum == 0.0
        assert not poo.can_generate_block()

    def test_single_domain_threshold(self) -> None:
        poo = ProofOfOptimization(initial_threshold=0.5)
        domain = _make_domain("d1", weight=1.0)
        poo.register_domain(domain)

        # Increment of 0.3 — below threshold of 0.5
        optimae = _make_optimae("d1", increment=0.3)
        poo.record_optimae(optimae)
        assert not poo.can_generate_block()

        # Another 0.3 — total 0.6 > threshold 0.5
        optimae2 = _make_optimae("d1", increment=0.3)
        poo.record_optimae(optimae2)
        assert poo.can_generate_block()

    def test_multi_domain_weighted_sum(self) -> None:
        poo = ProofOfOptimization(initial_threshold=1.0)
        d1 = _make_domain("d1", weight=2.0)
        d2 = _make_domain("d2", weight=0.5)
        poo.register_domain(d1)
        poo.register_domain(d2)

        # d1: 0.3 * 2.0 = 0.6
        poo.record_optimae(_make_optimae("d1", increment=0.3))
        assert poo.weighted_sum == 0.6
        assert not poo.can_generate_block()

        # d2: 1.0 * 0.5 = 0.5 → total = 1.1 > 1.0
        poo.record_optimae(_make_optimae("d2", increment=1.0))
        assert poo.weighted_sum == 1.1
        assert poo.can_generate_block()

    def test_block_generation(self) -> None:
        poo = ProofOfOptimization(initial_threshold=0.5)
        poo.register_domain(_make_domain("d1"))

        poo.record_optimae(_make_optimae("d1", increment=0.6))
        genesis = Block.genesis()
        block = poo.generate_block(genesis, "node-1")

        assert block is not None
        assert block.header.index == 1
        assert block.header.previous_hash == genesis.hash
        assert block.header.generator_id == "node-1"
        assert len(block.transactions) == 1

        # State should reset after block generation
        assert poo.weighted_sum == 0.0
        assert not poo.can_generate_block()

    def test_no_block_below_threshold(self) -> None:
        poo = ProofOfOptimization(initial_threshold=10.0)
        poo.register_domain(_make_domain("d1"))

        poo.record_optimae(_make_optimae("d1", increment=0.1))
        genesis = Block.genesis()
        block = poo.generate_block(genesis, "node-1")
        assert block is None
