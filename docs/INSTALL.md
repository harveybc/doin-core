# DOIN Installation & Quick Start

## Prerequisites

- Python 3.10+
- pip
- Git

## Quick Install (from GitHub)

```bash
# Install all packages
pip install git+https://github.com/harveybc/doin-core.git \
            git+https://github.com/harveybc/doin-node.git \
            git+https://github.com/harveybc/doin-optimizer.git \
            git+https://github.com/harveybc/doin-evaluator.git \
            git+https://github.com/harveybc/doin-plugins.git
```

## Developer Install (editable)

```bash
# Clone all repos
for pkg in doin-core doin-node doin-optimizer doin-evaluator doin-plugins; do
  git clone git@github.com:harveybc/$pkg.git
done

# Install in editable mode (order matters — core first)
pip install -e doin-core
pip install -e doin-node
pip install -e doin-optimizer
pip install -e doin-evaluator
pip install -e doin-plugins
```

## Run Tests

```bash
# All packages
for pkg in doin-core doin-node doin-optimizer doin-evaluator doin-plugins; do
  echo "=== $pkg ===" && cd $pkg && python -m pytest tests/ -q && cd ..
done

# Multi-node network test only
cd doin-node && python -m pytest tests/test_multinode.py -v

# End-to-end lifecycle test only
cd doin-plugins && python -m pytest tests/test_e2e_lifecycle.py -v
```

## Run a Node

### Single Node (Quadratic Domain — No ML Frameworks Needed)

```bash
doin-node --config config.json
```

Example `config.json`:
```json
{
  "host": "0.0.0.0",
  "port": 8470,
  "data_dir": "./doin-data",
  "bootstrap_peers": [],
  "domains": [
    {
      "domain_id": "quadratic",
      "optimize": true,
      "evaluate": true,
      "optimization_plugin": "quadratic",
      "inference_plugin": "quadratic",
      "synthetic_data_plugin": "quadratic",
      "has_synthetic_data": true
    }
  ]
}
```

### Multi-Node Test Network (localhost)

Terminal 1 — Optimizer node:
```bash
doin-node --config node1.json
```

`node1.json`:
```json
{
  "host": "127.0.0.1",
  "port": 8470,
  "data_dir": "./doin-data-1",
  "bootstrap_peers": ["127.0.0.1:8471", "127.0.0.1:8472"],
  "domains": [{"domain_id": "quadratic", "optimize": true, "evaluate": false,
               "has_synthetic_data": true}]
}
```

Terminal 2 — Evaluator node:
```bash
doin-node --config node2.json
```

`node2.json`:
```json
{
  "host": "127.0.0.1",
  "port": 8471,
  "data_dir": "./doin-data-2",
  "bootstrap_peers": ["127.0.0.1:8470", "127.0.0.1:8472"],
  "domains": [{"domain_id": "quadratic", "optimize": false, "evaluate": true,
               "has_synthetic_data": true}]
}
```

Terminal 3 — Another evaluator:
```bash
doin-node --config node3.json
```

`node3.json`:
```json
{
  "host": "127.0.0.1",
  "port": 8472,
  "data_dir": "./doin-data-3",
  "bootstrap_peers": ["127.0.0.1:8470", "127.0.0.1:8471"],
  "domains": [{"domain_id": "quadratic", "optimize": false, "evaluate": true,
               "has_synthetic_data": true}]
}
```

### Check Node Status

```bash
curl http://127.0.0.1:8470/status | python -m json.tool
curl http://127.0.0.1:8470/chain/status | python -m json.tool
```

## Predictor Domain (Requires TensorFlow)

For the real ML domain wrapping `harveybc/predictor`:

```bash
# Additional dependencies
pip install tensorflow
pip install git+https://github.com/harveybc/predictor.git
pip install git+https://github.com/harveybc/timeseries-gan.git  # For synthetic data

# Use the predictor config
doin-node --config doin-node/examples/predictor_node_config.json
```

## Package Overview

| Package | Description |
|---------|-------------|
| `doin-core` | Consensus, models, crypto, protocol — the foundation |
| `doin-node` | Unified node with transport, chain, sync, flooding |
| `doin-optimizer` | Standalone optimizer runner (legacy, use unified node) |
| `doin-evaluator` | Standalone evaluator service (legacy, use unified node) |
| `doin-plugins` | Domain plugins — quadratic (reference) + predictor (ML) |
