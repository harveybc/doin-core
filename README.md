# doin-core

**Status: ACTIVE — core library of the DOIN family.**

`doin-core` is the shared protocol library of DOIN, the Decentralized
Optimization and Inference Network (older code docstrings abbreviate it
**DON**). It defines the primitives every DOIN participant agrees on:
proof-of-optimization consensus rules, block/transaction/optimae data models,
the wire message schema, cryptographic peer identity, and the plugin abstract
base classes plus the setuptools entry-point groups through which domain
plugins are discovered. It contains no runtime: nodes, networking loops,
storage, and analytics live in
[doin-node](https://github.com/harveybc/doin-node).

## Truth labels (doctrine)

Every economic or trust claim in this repository carries exactly one of four
labels (work-plan document 40, doctrine alignment order 2026-08-15):

- `implemented_prototype` — what the code does today; a reproducible code
  fact, whether or not anyone ratified it as policy.
- `trusted_consortium_current` — the operating profile: one trusted
  owner/consortium fleet. Present tense belongs only here and to code facts.
- `owner_directed_target` — directed design boundary the code does not yet
  implement. Conditional tense, always.
- `conditional_untrusted_research` — the untrusted generated-gate profile,
  valid only when the full generator-admission program exists. No current
  domain qualifies.

Labeled claims about this library:

- [implemented_prototype] `models/coin.py` mints 50 DOIN per block with
  Bitcoin-like halving to a 21,000,000 bound and splits rewards 5% generator
  / 65% optimizer pool / 30% evaluator pool. These are code facts, not
  owner-ratified production economics, and must not be cited as canonical
  DOIN economics.
- [implemented_prototype] `distribute_block_reward()` has a known
  fee-conservation defect (AUD-DOIN-20260815-248): block_reward=50 +
  tx_fees=10 with no contributors distributes 67.15 from 60 available. A
  separately audited arithmetic correction must preserve the declared shares
  and enforce `sum(outputs) == block_reward + tx_fees`.
- [implemented_prototype] `consensus/difficulty.py` and
  `consensus/proof_of_optimization.py` time-target the optimization
  threshold: the quality bar moves (including downward) to meet wall-clock
  block cadence. Recorded drift relative to the owner-directed fixed
  progress-bin design.
- [implemented_prototype] `consensus/weights.py` grants a 0.5
  verification-strength fallback to domains without synthetic data. This
  contradicts the plugin ABC docstring (which says zero) — a recorded
  contradiction, resolved separately.
- [implemented_prototype] `EVALUATION_SERVED` transactions are recorded on
  chain and feed only the task-count statistic
  `observed_on_chain_task_share` — a censored operational statistic, not a
  price; the coinbase does not pay served inference.
- [trusted_consortium_current] The library operates today inside a trusted
  owner/consortium fleet; identity, ancestry, artifact integrity, duplicate
  claims, chain consistency and lineage are verified. It does not provide
  Byzantine, Sybil, collusion or permissionless economic security. No native
  coin is required for this profile to be useful.
- [owner_directed_target] Issuance would be one unit per completely filled
  verified progress certificate, zero for an empty bin; event/heartbeat
  blocks would carry zero issuance; a node could charge for hosted inference
  when it accepts a bid. None of this is implemented here.
- [conditional_untrusted_research] An untrusted generated-gate deployment
  would additionally require the full admission program of work-plan
  document 39 (authenticated participants, commit-before-challenge entropy,
  admitted content-addressed generator, deterministic draw reconstruction,
  calibrated ensemble tolerance, adversarial admission). No current domain
  passes it.

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

Verified 2026-08-10 in the maintainer's Python 3.12 environment:
`python -c "import doin_core; print(doin_core.__version__)"` prints `0.1.0`.
There is no PyPI release; install from source.

## Smallest working example

The snippet below exercises identity, deterministic seeds, synthetic-data
hashing, and block construction. Executed successfully on 2026-08-10:

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

Note: `hash_synthetic_data` requires `numpy`, which is a dependency of
`doin-plugins` rather than of this package; the rest of the library needs only
`pydantic` and `cryptography`.

## Plugin interface and entry-point groups

[`src/doin_core/plugins/base.py`](src/doin_core/plugins/base.py) defines the
three ABCs:

- `OptimizationPlugin` — `configure()`, `optimize(current_best_params,
  current_best_performance)`, `get_domain_metadata()`
- `InferencePlugin` — `configure()`, `evaluate(parameters, data)`
- `SyntheticDataPlugin` — `configure()`, deterministic `generate(seed)` and
  `generate_with_hash(seed)`. [implemented_prototype] The ABC docstring
  states that domains without a synthetic-data plugin get zero consensus
  weight, but the implemented weight calculator
  ([`consensus/weights.py`](src/doin_core/consensus/weights.py)) grants them
  a 0.5 verification-strength fallback — a recorded contradiction (work-plan
  document 40 §5), resolved separately. Under the conditional untrusted
  profile such domains would have zero authority.

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
pip install -e .[dev]
pytest -q
```

Observed 2026-08-10: `pytest -q --collect-only | tail -1` reports
**280 tests collected** across 20 test files in [`tests/`](tests).
(Collection count only; run `pytest -q` for a full pass.)

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
  model. [trusted_consortium_current] These defenses operate today inside a
  trusted owner/consortium fleet; they do not provide Byzantine, Sybil,
  collusion or permissionless economic security (see "Truth labels" above).
- This repository needs no exchange, broker, or API credentials.

## Limitations

- Version `0.1.0` (alpha). Wire and schema compatibility between versions is
  not yet guaranteed; peers should run matching versions.
- No PyPI distribution; source installs only.
- Some older documents under [`docs/`](docs) predate the unified runtime and
  may still describe the retired standalone optimizer/evaluator clients; the
  package boundaries stated in this README are current.
- Older documents under [`docs/`](docs) (including NETWORK/SECURITY/
  SCALABILITY and the paper HTML/PDF) present block rewards, fees, and
  economics without truth labels. Read every such claim as at most
  `implemented_prototype` — none of it is owner-ratified production
  economics; the labeled section above is authoritative.

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
