# AGENTS.md — doin-core

Guidance for AI coding agents working in this repository. See [agents.md](https://agents.md).

## Project overview

doin-core is the shared protocol library of DOIN, the Decentralized
Optimization and Inference Network (older docstrings abbreviate it **DON**). It
defines the primitives every participant must agree on: proof-of-optimization
consensus rules, the block/transaction/optimae data models, the wire message
schema, ECDSA peer identity and hashing, and the plugin abstract base classes
plus the entry-point groups through which domain plugins are discovered.

It is a **pure library with no runtime**. There is no node process, no event
loop, no HTTP transport, no storage backend, no database, no OLAP layer, no
web UI and no command-line tool — those belong to
[doin-node](https://github.com/harveybc/doin-node). It contains no plugin
*implementations* either; those live in
[doin-plugins](https://github.com/harveybc/doin-plugins). Nothing here opens a
socket or writes a file, except `PeerIdentity.save()` when a caller asks for it.

## Agent quickstart (install → run → show the user results)

Verified on 2026-08-16 with Python 3.12.13.

### 1. Environment

`requires-python = ">=3.10"`; CI runs 3.12.

```bash
conda create -n doin-core python=3.12 -y && conda activate doin-core
# or: python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" numpy
```

**The trailing `numpy` is required and is not a mistake.**
`src/doin_core/plugins/base.py:21` does a module-level `import numpy as np`, but
numpy is not declared in `pyproject.toml` (runtime deps are only `pydantic>=2.0`
and `cryptography>=41.0`). Without it, importing `doin_core.plugins` — including
the loader — fails, and `tests/test_synthetic_hash.py` errors at collection. CI
avoids this only because `requirements-ci.txt` pins numpy. Either add numpy to
`[project.dependencies]` or move the import inside `hash_synthetic_data`; until
then, install it explicitly.

### 2. Smoke test

```bash
pytest -q
```

Verified: **280 passed in 0.50 s**, across 20 test files. This is the whole
suite, it is fast, and it is green — treat any failure as a real regression.

Import check:

```bash
python -c "import doin_core; print(doin_core.__version__)"   # 0.1.0
```

### 3. Representative run: build a chain and verify it

There is no service to start and no example script in the repository, so the
representative run is a snippet. Save it as `chain_demo.py` outside the
repository (or in a scratch directory) and run it:

```python
"""Build a small DOIN chain with proof-of-optimization, then verify it."""
from doin_core.consensus import ProofOfOptimization
from doin_core.models import Block, Domain, DomainConfig, Optimae

poo = ProofOfOptimization(target_block_time=600.0, initial_threshold=0.5)
poo.register_domain(Domain(
    id="demo", name="Demo Domain", performance_metric="accuracy",
    higher_is_better=True, weight=1.0,
    config=DomainConfig(optimization_plugin="demo_opt", inference_plugin="demo_inf"),
))

chain = [Block.genesis()]
print(f"genesis  height=0 hash={chain[0].hash[:16]}...")

for i in range(1, 4):
    # Feed verified improvements until the dynamic threshold is crossed.
    while not poo.can_generate_block():
        poo.record_optimae(Optimae(
            domain_id="demo", optimizer_id=f"optimizer-{i}",
            parameters={"w": [i]}, reported_performance=0.5 + 0.1 * i,
            performance_increment=0.6, accepted=True,
        ))
    block = poo.generate_block(chain[-1], f"node-{i}")
    chain.append(block)
    print(f"block {i}  height={block.header.index} hash={block.hash[:16]}... "
          f"prev={block.header.previous_hash[:16]}... "
          f"threshold={block.header.threshold:.3f}")

for prev, cur in zip(chain, chain[1:]):
    assert cur.header.previous_hash == prev.hash, "broken link"
    assert cur.header.index == prev.header.index + 1, "bad height"
    assert cur.header.compute_hash() == cur.hash, "hash mismatch / tampered block"
print(f"\nOK: {len(chain)} blocks; links, heights and hashes all verify")
```

Verified output shape:

```
genesis  height=0 hash=4e19257e8941caec...
block 1  height=1 hash=1fd7c44a032fc71e... prev=4e19257e8941caec... threshold=0.500
block 2  height=2 hash=7063beae48e1767a... prev=1fd7c44a032fc71e... threshold=0.667
block 3  height=3 hash=835edff502484966... prev=7063beae48e1767a... threshold=0.889

OK: 4 blocks; links, heights and hashes all verify
```

Block hashes differ per run because headers carry a timestamp; the genesis hash
is stable because `Block.genesis()` pins an epoch-0 timestamp so every node
agrees on it.

The `while not poo.can_generate_block()` loop matters: after each block the
threshold self-adjusts toward the target block time, and because a script mints
blocks instantly the threshold climbs (0.500 → 0.667 → 0.889). A fixed number
of increments per block would stop working after the first one.

### 4. OLAP / analytics

**There is none, and none should be added here.** Verified by exhaustive search:
no sqlite, postgres, sqlalchemy, duckdb, star schema, or any SQL. The only grep
hit is the word "Select" in a docstring in
`src/doin_core/consensus/fork_choice.py`. All state is in-memory dataclasses and
pydantic models. The OLAP star schema lives in `doin-node` under
`src/doin_node/stats/`.

Likewise there is **no web UI, no HTTP API and no CLI**: no FastAPI, Flask,
uvicorn, aiohttp or `http.server` anywhere, and `pyproject.toml` declares no
`[project.scripts]`, so installing the package adds no executable. Do not invent
a URL for this repository.

### 5. Final message to give the user

> doin-core is a library — there is no service and no URL. Two things to look
> at:
>
> - **Test output:** `pytest -q` in the repository root, which reports
>   `280 passed` in well under a second. That is the full protocol contract
>   suite: consensus, fork choice, finality, models, crypto and plugin loading.
> - **The example script's output:** the `chain_demo.py` snippet from
>   `AGENTS.md` prints a genesis block plus three minted blocks with their
>   hashes and the rising consensus threshold, then confirms every parent link,
>   height and header hash verifies.
>
> One thing to try first: in `chain_demo.py`, tamper with a block after it is
> minted — for example `chain[2].header.weighted_performance_sum = 99.0` — and
> re-run the verification loop. The `cur.header.compute_hash() == cur.hash`
> assertion fails, which is the concrete demonstration that block headers are
> hash-committed. Then look at `tests/test_fork_choice.py` to see how competing
> chains are scored by verified optimization work rather than by length.

## Build, test and lint commands

Local:

```bash
pip install -e ".[dev]" numpy
pytest -q                  # 280 passed
python -m compileall -q src
```

CI runs one workflow, `.github/workflows/tier-a.yml` (job `consensus-contracts`,
Python 3.12), with exactly these steps:

```bash
sha256sum pyproject.toml requirements-ci.txt
python -m pip install --require-hashes -r requirements-ci.txt
python -m pip install --no-deps -e .
python -m compileall -q src
pytest -q
```

`requirements-ci.txt` is a hash-locked lockfile compiled from
`requirements-ci.in`; it is for CI reproducibility, not for local development.

**`ruff` and `mypy` are configured but never run.** `pyproject.toml` sets
`[tool.ruff]` (target py310, line length 88, lint select `E,F,I,N,W,UP,B,SIM`)
and `[tool.mypy]` with `strict = true`, and both are in the `dev` extra, but no
CI step invokes them and there is no pre-commit config. Do not claim this
codebase is lint-clean or type-clean. If you want to check your own changes:

```bash
ruff check src tests
mypy src            # strict mode; expect pre-existing findings
```

Unverified: neither command was executed for this document, so the size of the
pre-existing backlog is unknown.

## Layout

| Path | Purpose |
|---|---|
| `src/doin_core/consensus/` | Proof-of-optimization, difficulty control, fork choice, finality and external anchoring, verified-utility weights, incentives, dynamic quorum, deterministic seeds |
| `src/doin_core/models/` | `Block`/`BlockHeader`, `Transaction`, `Optimae`, `Domain`, `Task`, quorum, commit-reveal, reputation, coin, payment channel, fee market, resource limits |
| `src/doin_core/protocol/` | `MessageType` enum and 16 pydantic wire payload models — schema only, no transport |
| `src/doin_core/crypto/` | `PeerIdentity` (ECDSA SECP256R1, signing, peer IDs) and hashing/merkle helpers |
| `src/doin_core/plugins/` | The three plugin ABCs and the entry-point loader |
| `tests/` | 280 tests across 20 files; no `conftest.py` |
| `scripts/` | Deployment helpers for **doin-node**, not for this library |
| `docs/` | INSTALL, NETWORK, SECURITY, SCALABILITY, and the DOIN paper PDF |

Total source is roughly 4,500 lines across 31 files — small enough to read.

## Conventions and constraints

- **Protocol source of truth.** Anything that two participants must agree on
  byte-for-byte belongs here. A change to a model field, a hash input, or a
  consensus rule is a wire-compatibility break: peers must run matching
  versions, and version `0.1.0` guarantees no cross-version compatibility.
- **Pure and dependency-light.** Runtime dependencies are `pydantic` and
  `cryptography` only. Do not add I/O, networking, threads or heavy
  dependencies. If a feature needs a socket or a disk, it belongs in `doin-node`.
- **Plugin discovery** is via setuptools entry-point groups: `doin.optimization`,
  `doin.inference`, `doin.synthetic_data`, loaded by
  `load_optimization_plugin(name)`, `load_inference_plugin(name)`,
  `load_synthetic_data_plugin(name)`. This repository defines the ABCs and group
  names; implementations register from other packages.
- **Synthetic data is mandatory for verification trust** — a domain without a
  `SyntheticDataPlugin` gets zero consensus weight.
- **Determinism.** Seeds are derived from commitment hashes via
  `derive_seed`/`verify_seed` so evaluation is reproducible and cannot be
  cherry-picked. `Block.genesis()` pins its timestamp for the same reason. Do
  not introduce wall-clock or unseeded randomness into consensus paths.
- **Tests run with `asyncio_mode = "auto"`**; `testpaths = ["tests"]`.

## Do not touch

- **`PeerIdentity` key files.** `save()` / `load_or_generate()` write private
  keys (mode 0600). Never commit them, print them, copy them, or add them to
  fixtures.
- **Consensus constants and hash inputs** without understanding the
  compatibility break — changing what goes into `compute_hash()` or a merkle
  root forks the network.
- **`scripts/`.** These install and launch `doin-node` across machines and
  reference other repositories; `install.sh` still installs the retired
  `doin-optimizer` / `doin-evaluator`. They are not part of this library's
  workflow and should not be run to verify anything here.
- **Sibling repositories.** Runtime changes go to `doin-node`, plugin
  implementations to `doin-plugins`.
- **Running processes.** This machine may have GPU training workers and DOIN
  nodes live. Nothing in this repository needs them; never start or stop a node
  to test a library change.
- **Secrets in a public repository.** Never write account identifiers, broker
  credentials, private IP addresses or machine host names into files here. Use
  placeholders such as `<your-host>`.
