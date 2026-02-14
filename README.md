# DOIN — Decentralized Optimization and Inference Network

> **Proof of Optimization**: Block generation triggered by verified ML improvements, not wasted hash computations.

DOIN is a decentralized system where nodes collaboratively optimize machine learning models using blockchain consensus. Instead of proof-of-work, blocks are generated when the weighted sum of verified optimization improvements exceeds a dynamic threshold — making every unit of compute count toward real progress.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   doin-core  │     │  doin-node   │     │ doin-plugins │
│              │     │              │     │              │
│ • Consensus  │◄────│ • Transport  │────►│ • Quadratic  │
│ • Models     │     │ • Chain      │     │ • Predictor  │
│ • Crypto     │     │ • Sync       │     │ • (custom)   │
│ • Protocol   │     │ • Flooding   │     │              │
│ • Plugins    │     │ • Unified    │     │              │
│ • Coin       │     │   Node       │     │              │
│ • Difficulty  │     │              │     │              │
└──────────────┘     └──────────────┘     └──────────────┘
```

**5 packages:**

| Package | Description | Tests |
|---------|-------------|-------|
| [doin-core](https://github.com/harveybc/doin-core) | Consensus, models, crypto, protocol, coin, difficulty | 196 |
| [doin-node](https://github.com/harveybc/doin-node) | Unified node: transport, chain, sync, flooding | 83 |
| [doin-optimizer](https://github.com/harveybc/doin-optimizer) | Standalone optimizer runner | 5 |
| [doin-evaluator](https://github.com/harveybc/doin-evaluator) | Standalone evaluator service | 7 |
| [doin-plugins](https://github.com/harveybc/doin-plugins) | Domain plugins (quadratic reference + predictor ML) | 43 |

**Total: 334 tests passing**

## Quick Install (Linux)

### One-Line Install
```bash
curl -sSL https://raw.githubusercontent.com/harveybc/doin-core/master/scripts/install.sh | bash
```

### Manual Install
```bash
# Prerequisites: Python 3.10+, pip, git
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git

# Create virtual environment (recommended)
python3 -m venv ~/doin-venv && source ~/doin-venv/bin/activate

# Install packages (order matters — core first)
pip install git+https://github.com/harveybc/doin-core.git
pip install git+https://github.com/harveybc/doin-node.git
pip install git+https://github.com/harveybc/doin-optimizer.git
pip install git+https://github.com/harveybc/doin-evaluator.git
pip install git+https://github.com/harveybc/doin-plugins.git
```

### Developer Install (editable)
```bash
mkdir ~/doin && cd ~/doin

# Clone all repos
for pkg in doin-core doin-node doin-optimizer doin-evaluator doin-plugins; do
  git clone https://github.com/harveybc/$pkg.git
done

# Install in editable mode
pip install -e doin-core
pip install -e doin-node
pip install -e doin-optimizer
pip install -e doin-evaluator
pip install -e doin-plugins

# Install dev dependencies
pip install pytest pytest-asyncio pytest-cov

# Run all tests
for pkg in doin-core doin-node doin-optimizer doin-evaluator doin-plugins; do
  echo "=== $pkg ===" && cd $pkg && python -m pytest tests/ -q && cd ..
done
```

## Run a Node

### Single Node (Quadratic Domain — No ML Frameworks Needed)

```bash
cat > config.json << 'EOF'
{
  "host": "0.0.0.0",
  "port": 8470,
  "data_dir": "./doin-data",
  "bootstrap_peers": [],
  "domains": [{
    "domain_id": "quadratic",
    "optimize": true,
    "evaluate": true,
    "has_synthetic_data": true
  }]
}
EOF

doin-node --config config.json
```

### Multi-Node Testnet (localhost)

```bash
# Launch 3 nodes automatically
./scripts/deploy-testnet.sh 3

# Or 5 nodes with clean data
./scripts/deploy-testnet.sh 5 --clean
```

### Deploy to Remote Machine

```bash
# Deploy evaluator node to a remote server
./scripts/deploy-remote.sh user@server --port 8470 --peers seed1.doin.net:8470,seed2.doin.net:8470

# Deploy optimizer node
./scripts/deploy-remote.sh user@gpu-server --optimize --port 8470 --peers seed1.doin.net:8470
```

### Check Node Status

```bash
curl http://localhost:8470/status | python3 -m json.tool
curl http://localhost:8470/chain/status
```

## How It Works

### Optimae Lifecycle
```
Optimizer                    Network                      Evaluators
    │                           │                             │
    │ 1. Optimize ML model      │                             │
    │ 2. Commit hash(params)  ──►│ Flood to all nodes         │
    │                           │                             │
    │ 3. Reveal params + nonce──►│ Verify hash matches        │
    │                           │                             │
    │                           │ 4. Select random quorum  ──►│
    │                           │                             │
    │                           │    5. Generate synthetic ──►│ (different per evaluator)
    │                           │    6. Evaluate model     ──►│
    │                           │    7. Vote on performance──►│
    │                           │                             │
    │                           │ 8. Quorum decides           │
    │                           │ 9. Distribute coin reward   │
    │                           │ 10. Update reputation       │
    │◄── Coins + reputation ────│                             │
    │                           │◄── Coins + reputation ──────│
```

### DOIN Coin Economics
- **Block reward**: 50 DOIN (halves every 210,000 blocks)
- **Max supply**: 21,000,000 DOIN
- **Distribution**: 65% optimizers, 30% evaluators, 5% block generator
- **Proportional to work**: optimizer share scaled by `effective_increment × reward_fraction`

### Difficulty Adjustment (Bitcoin/Ethereum Hybrid)
- **Epoch-based** (every 100 blocks): Major correction, clamped to 4× max change
- **Per-block EMA** (α=0.1): Smooth inter-epoch corrections, ±2% max per block
- **Target**: 10-minute block time (configurable)

### Security (10 Hardening Measures)
1. Commit-reveal (anti-front-running)
2. Random quorum selection (anti-collusion)
3. Asymmetric reputation penalties (3× penalty vs 1× reward)
4. Resource limits + bounds validation (anti-DoS)
5. Finality checkpoints (anti-rewrite)
6. Reputation decay — EMA (anti-farming)
7. Min reputation threshold (anti-sybil)
8. External checkpoint anchoring (51% defense)
9. Fork choice — heaviest chain (anti-selfish-mining)
10. Per-evaluator deterministic seeds (anti-overfitting)

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/status` | GET | Full node status (chain, peers, tasks, security, coin, difficulty) |
| `/chain/status` | GET | Chain height, tip hash, finalized height |
| `/chain/blocks?from=X&to=Y` | GET | Fetch blocks by range (max 50) |
| `/chain/block/{index}` | GET | Fetch single block |
| `/tasks/pending` | GET | List pending tasks |
| `/tasks/claim` | POST | Claim a task |
| `/tasks/complete` | POST | Complete a task |
| `/inference` | POST | Submit inference request |

## Documentation

| Document | Description |
|----------|-------------|
| [NETWORK.md](docs/NETWORK.md) | Network architecture & protocol |
| [SECURITY.md](docs/SECURITY.md) | 25 attack vectors & defenses |
| [SCALABILITY.md](docs/SCALABILITY.md) | Scalability analysis & roadmap |
| [INSTALL.md](docs/INSTALL.md) | Detailed installation guide |
| [doin-paper.pdf](docs/doin-paper.pdf) | IEEE-style academic paper |

## Plugin System

Create custom domains by implementing three plugin interfaces:

```python
from doin_core.plugins.base import OptimizationPlugin, InferencePlugin, SyntheticDataPlugin

class MyOptimizer(OptimizationPlugin):
    def optimize(self, current_best_params, current_best_performance):
        # Your ML training logic here
        return new_params, new_performance

class MyInferencer(InferencePlugin):
    def evaluate(self, parameters, data=None):
        # Evaluate the model
        return performance_score

class MySyntheticData(SyntheticDataPlugin):
    def generate(self, seed=None):
        # Generate synthetic test data
        return {"data": [...], "labels": [...]}
```

Register via `pyproject.toml` entry points:
```toml
[project.entry-points."doin.optimization"]
my_domain = "my_package:MyOptimizer"

[project.entry-points."doin.inference"]
my_domain = "my_package:MyInferencer"

[project.entry-points."doin.synthetic_data"]
my_domain = "my_package:MySyntheticData"
```

## Contributing

1. Fork the relevant repo
2. Create a feature branch
3. Make changes + add tests
4. Run full test suite
5. Submit a pull request

## License

MIT License — see each package for details.

## Author

Harvey Bastidas — [harveybc](https://github.com/harveybc)
