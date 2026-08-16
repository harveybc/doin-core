# doin-core

**Status: ACTIVE.**

`doin-core` is the shared protocol library of DOIN, the Decentralized
Optimization and Inference Network (older code docstrings abbreviate it
**DON**). It defines the primitives every DOIN participant agrees on:
proof-of-optimization consensus rules, block/transaction/optimae data models,
the wire message schema, cryptographic peer identity, and the plugin abstract
base classes plus the setuptools entry-point groups through which domain
plugins are discovered. It contains no runtime: nodes, networking loops,
storage, and analytics live in
[doin-node](https://github.com/harveybc/doin-node).

## Run this with an AI agent

Paste this into Claude Code, Cursor, Codex, GitHub Copilot or any coding agent
with shell access:

> Read `AGENTS.md` in this repository and follow the **Agent quickstart**
> section end to end: set up the environment, run the smoke test, execute the
> example chain-build-and-verify script, then tell me the exact file paths
> where I can see the results and one thing I should try first.

`AGENTS.md` is the [agents.md](https://agents.md) convention, read natively by
most coding agents.

## Role and non-responsibilities

**Role:** the single source of truth for protocol data structures and
consensus logic shared by all DOIN packages.

**Not in this repository:**

- No participant runtime, event loops, HTTP transport, or storage backends —
  that is [doin-node](https://github.com/harveybc/doin-node), the unified
  participant runtime.
- No OLAP / analytics schema. The OLAP-on-blockchain code (star schema,
  experiment tracker, chain metrics) lives in `doin-node` under its
  `src/doin_node/stats/` package, not here.
- No plugin implementations — reference and production plugins live in
  [doin-plugins](https://github.com/harveybc/doin-plugins); this repository
  only defines the abstract interfaces and entry-point groups.
- No domain models or optimizers. Domain optimizers remain external
  installable packages that must work locally without DOIN and implement the
  plugin interfaces defined here.

## Architecture

| Package | Contents |
|---|---|
| [`doin_core.consensus`](src/doin_core/consensus) | Proof-of-optimization, fork choice, finality checkpoints and external anchoring, difficulty, evaluation weights, incentives, dynamic quorum, deterministic seed derivation |
| [`doin_core.models`](src/doin_core/models) | `Block`/`BlockHeader`, `Transaction` (optimae, task, evaluation, domain and candidate transaction types), `Optimae`, `Domain`, `Task`, quorum, commit-reveal, reputation, coin, payment channel, fee market, resource limits |
| [`doin_core.protocol`](src/doin_core/protocol) | `MessageType` enum and pydantic payload models for the wire protocol |
| [`doin_core.crypto`](src/doin_core/crypto) | `PeerIdentity` (elliptic-curve keys, signing/verification, peer IDs) and hashing helpers |
| [`doin_core.plugins`](src/doin_core/plugins) | Plugin ABCs and the entry-point loader (see below) |

Consumers: `doin-node` (runtime), `doin-plugins` (implementations), and the
retired `doin-optimizer` / `doin-evaluator` clients (historical only).

## Requirements

From [`pyproject.toml`](pyproject.toml):

- Python `>=3.10`
- `pydantic>=2.0`, `cryptography>=41.0`
- Dev extras: `pytest`, `pytest-cov`, `pytest-asyncio`, `mypy`, `ruff`

## Installation

```bash
git clone https://github.com/harveybc/doin-core.git
cd doin-core
pip install -e .          # add [dev] for the test toolchain
```

`python -c "import doin_core; print(doin_core.__version__)"` prints `0.1.0`.
There is no PyPI release; install from source.

Note that `numpy` is needed in practice but is not declared as a dependency:
`src/doin_core/plugins/base.py` imports it at module level, so
`import doin_core.plugins` and the test suite both fail without it. Install it
alongside the dev extras until this is fixed.

## Smallest working example

The snippet below exercises identity, deterministic seeds, synthetic-data
hashing, and block construction:

```python
from doin_core.consensus.deterministic_seed import derive_seed, verify_seed
from doin_core.crypto.identity import PeerIdentity
from doin_core.models.block import Block, BlockHeader
from doin_core.plugins.base import hash_synthetic_data

# 1. Node identity: generate, sign, verify
identity = PeerIdentity.generate()
payload = b"optimae payload"
signature = identity.sign(payload)
assert identity.verify(signature, payload)

# 2. Deterministic evaluation seed derived from a commitment hash
commitment = "ab" * 32
seed = derive_seed(commitment, domain_id="quadratic")
assert verify_seed(commitment, "quadratic", seed)

# 3. Consensus hash of synthetic evaluation data
digest = hash_synthetic_data({"x": [1.0, 2.0, 3.0]})

# 4. Build a block (hash computed automatically)
header = BlockHeader(
    index=0,
    previous_hash="0" * 64,
    merkle_root="0" * 64,
    generator_id=identity.peer_id,
    weighted_performance_sum=0.0,
    threshold=1.0,
)
block = Block(header=header)
print(identity.peer_id[:16], seed, digest[:16], block.hash[:16])
```

Note: the `doin_core.plugins` package requires `numpy` (see Installation). The
consensus, models, protocol and crypto packages need only `pydantic` and
`cryptography`.

## Plugin interface and entry-point groups

[`src/doin_core/plugins/base.py`](src/doin_core/plugins/base.py) defines the
three ABCs:

- `OptimizationPlugin` — `configure()`, `optimize(current_best_params,
  current_best_performance)`, `get_domain_metadata()`
- `InferencePlugin` — `configure()`, `evaluate(parameters, data)`
- `SyntheticDataPlugin` — `configure()`, deterministic `generate(seed)` and
  `generate_with_hash(seed)`; synthetic data is mandatory for verification
  trust (domains without it get zero consensus weight)

[`src/doin_core/plugins/loader.py`](src/doin_core/plugins/loader.py) discovers
implementations through these setuptools entry-point groups:

| Group | Loader function |
|---|---|
| `doin.optimization` | `load_optimization_plugin(name)` |
| `doin.inference` | `load_inference_plugin(name)` |
| `doin.synthetic_data` | `load_synthetic_data_plugin(name)` |

Any external package can register plugins in these groups;
[doin-plugins](https://github.com/harveybc/doin-plugins) provides the
reference and production implementations consumed by
[doin-node](https://github.com/harveybc/doin-node).

## Tests

```bash
pip install -e .[dev] numpy
pytest -q
```

`pytest -q` reports **280 passed** across 20 test files in [`tests/`](tests).
`ruff` and `mypy` are configured in `pyproject.toml` and shipped in the dev
extras, but CI runs neither, so the codebase is not known to be lint- or
type-clean.

## Artifacts and outputs

This is a pure library: it writes nothing on import. `PeerIdentity.save()` /
`load_or_generate()` persist private key material to a caller-chosen path —
treat those files as secrets (see below).

## Security notes

- `PeerIdentity` files contain private keys. Keep them out of version control
  and readable only by the node's user.
- Consensus defenses implemented here include commit-reveal for optimae,
  deterministic seed derivation (reproducible training, no cherry-picked
  seeds), quorum verification with tolerance, finality checkpoints, and
  external anchoring. See [docs/SECURITY.md](docs/SECURITY.md) for the threat
  model.

## Limitations

- Version `0.1.0` (alpha). Wire and schema compatibility between versions is
  not yet guaranteed; peers should run matching versions.
- No PyPI distribution; source installs only.
- Some older documents under [`docs/`](docs) predate the unified runtime and
  may still describe the retired standalone optimizer/evaluator clients; the
  package boundaries stated in this README are current.

## Related repositories and docs

- [doin-node](https://github.com/harveybc/doin-node) — unified participant
  runtime (optimizer/evaluator/network roles selected by per-machine JSON
  config)
- [doin-plugins](https://github.com/harveybc/doin-plugins) — plugin
  implementations and the agent-multi trading bridge
- [doin-optimizer](https://github.com/harveybc/doin-optimizer),
  [doin-evaluator](https://github.com/harveybc/doin-evaluator) — legacy
  standalone clients, superseded by `doin-node`
- Deeper docs in this repo: [INSTALL](docs/INSTALL.md),
  [NETWORK](docs/NETWORK.md), [SECURITY](docs/SECURITY.md),
  [SCALABILITY](docs/SCALABILITY.md), and the
  [DOIN paper (PDF)](docs/doin-paper.pdf)

## License

Declared MIT in [`pyproject.toml`](pyproject.toml); the repository does not
currently ship a standalone `LICENSE` file.
