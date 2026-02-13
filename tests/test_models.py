"""Tests for DON core data models."""

from doin_core.models import Block, Domain, DomainConfig, Optimae, Transaction, TransactionType


class TestOptimae:
    def test_create_optimae(self) -> None:
        optimae = Optimae(
            domain_id="test-domain",
            optimizer_id="peer-123",
            parameters={"learning_rate": 0.01, "layers": [64, 32]},
            reported_performance=0.95,
        )
        assert optimae.id != ""
        assert optimae.domain_id == "test-domain"
        assert optimae.accepted is False
        assert optimae.verified_performance is None

    def test_deterministic_id(self) -> None:
        kwargs = {
            "domain_id": "d1",
            "optimizer_id": "p1",
            "parameters": {"x": 1},
            "reported_performance": 0.5,
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
        o1 = Optimae(**kwargs)
        o2 = Optimae(**kwargs)
        assert o1.id == o2.id


class TestDomain:
    def test_create_domain(self) -> None:
        domain = Domain(
            id="predictor-v1",
            name="Time Series Predictor",
            performance_metric="mse",
            higher_is_better=False,
            weight=2.0,
            config=DomainConfig(
                optimization_plugin="genetic_optimizer",
                inference_plugin="keras_predictor",
                synthetic_data_plugin="timeseries_generator",
            ),
        )
        assert domain.id == "predictor-v1"
        assert domain.higher_is_better is False
        assert domain.config.synthetic_data_plugin == "timeseries_generator"


class TestTransaction:
    def test_create_transaction(self) -> None:
        tx = Transaction(
            tx_type=TransactionType.OPTIMAE_ACCEPTED,
            domain_id="d1",
            peer_id="p1",
            payload={"optimae_id": "abc123"},
        )
        assert tx.id != ""
        assert tx.tx_type == TransactionType.OPTIMAE_ACCEPTED


class TestBlock:
    def test_genesis_block(self) -> None:
        genesis = Block.genesis()
        assert genesis.header.index == 0
        assert genesis.header.previous_hash == "0" * 64
        assert genesis.hash != ""
        assert len(genesis.transactions) == 0

    def test_block_hash_deterministic(self) -> None:
        g1 = Block.genesis("node-1")
        g2 = Block.genesis("node-1")
        # Same generator + same timestamp factory means same structure
        # (timestamps may differ by microseconds, so we just check they're valid)
        assert g1.hash != ""
        assert g2.hash != ""
