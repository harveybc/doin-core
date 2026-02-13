# DON Core

**Core library for the Decentralized Optimization Network (DON)**

DON is a decentralized network for optimization and inference services with a novel blockchain-based timestamping mechanism. Instead of cryptographic proof of work, DON uses **proof of optimization** — blocks are generated when the weighted sum of performance improvements across optimized models exceeds a dynamic threshold.

## Architecture

DON consists of three network roles:

- **Optimizers** — Run optimization plugins to produce *optimae* (optimized model parameters)
- **Evaluators** — Serve inference requests and verify optimizer claims
- **Nodes** — P2P networking, controlled flooding, validation, and block generation

This package (`doin-core`) provides the shared foundations:

- **Data Models** — Block, Optimae, Domain, Transaction
- **Consensus** — Proof-of-optimization engine with dynamic threshold adjustment
- **Plugin System** — Abstract interfaces for optimization, inference, and synthetic data plugins
- **Protocol** — Message definitions for P2P communication
- **Crypto** — Peer identity (ECDSA), signing, Merkle trees

## Installation

```bash
pip install -e ".[dev]"
```

## Quick Start

```python
from doin_core.models import Block, Domain, DomainConfig, Optimae
from doin_core.consensus import ProofOfOptimization

# Define a domain (an optimizable model)
domain = Domain(
    id="predictor-v1",
    name="Time Series Predictor",
    performance_metric="mse",
    higher_is_better=False,
    weight=1.0,
    config=DomainConfig(
        optimization_plugin="genetic_optimizer",
        inference_plugin="keras_predictor",
    ),
)

# Initialize consensus
consensus = ProofOfOptimization(target_block_time=600.0, initial_threshold=1.0)
consensus.register_domain(domain)

# Record an optimization result
optimae = Optimae(
    domain_id="predictor-v1",
    optimizer_id="peer-abc123",
    parameters={"learning_rate": 0.001, "hidden_layers": [128, 64]},
    reported_performance=0.92,
    performance_increment=0.05,
    accepted=True,
)
consensus.record_optimae(optimae)

# Check if we can generate a block
if consensus.can_generate_block():
    genesis = Block.genesis()
    new_block = consensus.generate_block(genesis, generator_id="my-node")
```

## Plugin Development

Create plugins by implementing the abstract interfaces:

```python
from doin_core.plugins import OptimizationPlugin

class MyOptimizer(OptimizationPlugin):
    def configure(self, config):
        self.model = load_model(config["model_path"])

    def optimize(self, current_best_params, current_best_performance):
        # Your optimization logic here
        new_params = genetic_search(self.model, current_best_params)
        performance = evaluate(self.model, new_params)
        return new_params, performance

    def get_domain_metadata(self):
        return {"performance_metric": "accuracy", "higher_is_better": True}
```

Register via entry points in `pyproject.toml`:

```toml
[project.entry-points."doin.optimization"]
my_optimizer = "my_package:MyOptimizer"
```

## Testing

```bash
pytest
```

## License

MIT
