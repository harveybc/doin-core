# DOIN Security Model: Attack Vectors & Defenses

> **Version:** 1.0 — February 2026
> **Test Coverage:** 291 tests validate the security hardening measures described in this document.

## Summary Table

| # | Attack | Category | Primary Defense | Implementation |
|---|--------|----------|----------------|----------------|
| 1 | Sybil Attack | Consensus | Min reputation threshold (2.0) | `ReputationTracker` |
| 2 | 51% Attack | Consensus | External checkpoint anchoring | `ExternalAnchorManager` |
| 3 | Selfish Mining / Fork Manipulation | Consensus | Heaviest-chain fork choice rule | `ForkChoiceRule` |
| 4 | Block Withholding | Consensus | Finality checkpoints | `FinalityManager` |
| 5 | Nothing-at-Stake | Consensus | Reputation-weighted voting | `ReputationTracker` |
| 6 | Grinding Attack | Consensus | Deterministic seed + commit-reveal | `DeterministicSeedPolicy` |
| 7 | Eclipse Attack | Consensus | Reputation quorum + external anchors | `QuorumManager`, `ExternalAnchorManager` |
| 8 | Long-Range History Rewrite | Long-Range | Finality checkpoints (depth=6) | `FinalityManager` |
| 9 | Checkpoint Manipulation | Long-Range | External ledger anchoring | `ExternalAnchorManager` |
| 10 | Stake Redistribution | Long-Range | EMA reputation decay | `ReputationTracker` |
| 11 | Time-Warp Attack | Long-Range | Timestamp validation + finality | `FinalityManager` |
| 12 | Hidden Randomness | Optimization Gaming | Deterministic seed policy | `DeterministicSeedPolicy` |
| 13 | Front-Running | Optimization Gaming | Commit-reveal protocol | `CommitRevealManager` |
| 14 | Parameter Theft | Optimization Gaming | Commit-reveal + blockchain timestamping | `CommitRevealManager` |
| 15 | DoS via Expensive Tasks | Resource | Resource limits + bounds validation | `ResourceLimits`, `BoundsValidator` |
| 16 | Storage Bloat | Resource | Parameter bounds + block size limits | `BoundsValidator` |
| 17 | Rubber-Stamp Evaluators | Verification Gaming | Asymmetric reputation penalties | `ReputationTracker` |
| 18 | Lazy Evaluation | Verification Gaming | Asymmetric penalties + quorum consensus | `ReputationTracker`, `QuorumManager` |
| 19 | Parameter Theft via Evaluation | Verification Gaming | Commit-reveal priority proof | `CommitRevealManager` |
| 20 | Evaluator Collusion | Verification Gaming | Random quorum selection | `QuorumManager` |
| 21 | OOM Attack | Resource | Resource limits + bounds validation | `ResourceLimits`, `BoundsValidator` |
| 22 | Incentive Manipulation | Reputation | Tolerance margin + bonus cap | `IncentiveModel` |
| 23 | Reputation Farming | Reputation | EMA decay (half-life 1 week) | `ReputationTracker` |
| 24 | Under-Reporting | Reputation | Bonus cap (max 1.2×) | `IncentiveModel` |
| 25 | Training on Verification Data | Synthetic Data | Per-evaluator seeds | `get_seed_for_synthetic_data` |

---

## 10 Implemented Hardening Measures

| # | Measure | Module |
|---|---------|--------|
| 1 | Commit-reveal for optimae | `doin_core/models/commit_reveal.py` |
| 2 | Random quorum selection | `doin_core/models/quorum.py` |
| 3 | Asymmetric reputation penalties | `doin_core/models/reputation.py` |
| 4 | Resource limits + bounds validation | `doin_core/models/resource_limits.py` |
| 5 | Finality checkpoints | `doin_core/consensus/finality.py` |
| 6 | Reputation decay (EMA) | `doin_core/models/reputation.py` |
| 7 | Min reputation threshold | `doin_core/models/reputation.py` |
| 8 | External checkpoint anchoring | `doin_core/consensus/finality.py` |
| 9 | Fork choice rule | `doin_core/consensus/fork_choice.py` |
| 10 | Deterministic seed requirement | `doin_core/consensus/deterministic_seed.py` |

**Additional mechanisms:**
- **Incentive model** (`doin_core/consensus/incentives.py`) — tolerance margin for verification variance
- **Per-evaluator synthetic data seeds** — prevents overfitting to verification data

---

## Category 1: Consensus Attacks

### Attack #1 — Sybil Attack

**Description:** An attacker creates many fake node identities to dominate consensus voting, attempting to outnumber honest participants and control block validation outcomes.

**Impact:** If successful, the attacker gains disproportionate influence over which optimae are accepted, potentially approving fraudulent results or censoring legitimate ones.

**Defense:** DOIN requires a minimum reputation of `MIN_REPUTATION_FOR_CONSENSUS = 2.0` to participate in consensus. Reputation cannot be purchased or transferred — it must be earned through verified optimization or evaluation work over time. Creating 100 fake nodes yields 100 nodes with zero reputation and zero voting power.

**Implementation:** `doin_core/models/reputation.py` — `ReputationTracker` class enforces the minimum threshold before any node's vote is counted in consensus rounds.

---

### Attack #2 — 51% Attack / External Validation

**Description:** An attacker acquires majority compute power on the network, allowing them to validate their own blocks and potentially rewrite recent history.

**Impact:** Complete control over which blocks are accepted, ability to double-spend optimization rewards or censor competitors.

**Defense:** DOIN anchors chain state to an external ledger via `ExternalAnchorManager`. Periodically, the hash of the current chain state is published to an external, independently-secured ledger. Even if an attacker controls 100% of DOIN nodes, they cannot rewrite history that has been externally anchored without also compromising the external system.

**Implementation:** `doin_core/consensus/finality.py` — `ExternalAnchorManager` publishes chain hashes to an external ledger at configurable intervals, creating tamper-evident checkpoints.

---

### Attack #3 — Selfish Mining / Fork Manipulation

**Description:** An attacker withholds validated blocks, building a private chain, then releases it strategically to orphan honest nodes' work and claim their rewards.

**Impact:** Honest optimizers and evaluators lose rewards for work that gets orphaned; attacker captures disproportionate share of incentives.

**Defense:** DOIN's fork choice rule (`ForkChoiceRule`) selects the **heaviest** chain — the chain with the most cumulative verified optimization work — not simply the longest chain. This means a private chain without real verified work carries less weight, and strategically timed releases cannot easily overtake a chain backed by genuine optimization results.

**Implementation:** `doin_core/consensus/fork_choice.py` — `ForkChoiceRule` class scores chains by total verified optimization work rather than block count.

---

### Attack #4 — Block Withholding

**Description:** A node participates in consensus but strategically withholds certain blocks to delay or disrupt finality.

**Impact:** Network stalls or slowdowns; delayed confirmation of legitimate optimization results.

**Defense:** Finality checkpoints ensure that once a block reaches `confirmation_depth = 6`, it is finalized regardless of any single node's participation. The network progresses without requiring universal participation.

**Implementation:** `doin_core/consensus/finality.py` — `FinalityManager` finalizes blocks at the configured confirmation depth.

---

### Attack #5 — Nothing-at-Stake

**Description:** In proof-of-stake-like systems, validators can vote on multiple forks simultaneously at no cost, undermining consensus convergence.

**Impact:** Persistent forks, inability to reach consensus, chain instability.

**Defense:** DOIN uses reputation-weighted voting where reputation is a scarce, earned resource. Voting on a fork that loses costs reputation (diverging from the eventual quorum consensus), making nothing-at-stake economically irrational. The asymmetric penalty structure (PENALTY=3.0 vs REWARD=0.3) ensures that reckless multi-fork voting is punished severely.

**Implementation:** `doin_core/models/reputation.py` — `ReputationTracker` applies penalties when a node's votes diverge from the finalized consensus outcome.

---

### Attack #6 — Grinding Attack

**Description:** An attacker iterates over many possible block parameters (timestamps, orderings) to find one that gives them favorable conditions in the next round (e.g., being selected as evaluator).

**Impact:** Unfair advantage in quorum selection or seed generation; attacker can position themselves favorably.

**Defense:** Deterministic seed derivation (`DeterministicSeedPolicy`) computes seeds from `hash(commitment_hash + domain)`, removing attacker-controlled variables. Combined with commit-reveal, the commitment is locked before the block that determines selection is known.

**Implementation:** `doin_core/consensus/deterministic_seed.py` — `DeterministicSeedPolicy` ensures seeds are deterministic and non-manipulable.

---

### Attack #7 — Eclipse Attack

**Description:** An attacker surrounds a target node with malicious peers, controlling all its network connections, feeding it a false view of the chain.

**Impact:** The eclipsed node accepts a fraudulent chain, potentially losing rewards or accepting invalid optimae.

**Defense:** External checkpoint anchoring allows any node to independently verify chain state against the external ledger, detecting eclipse attacks. Additionally, reputation-based quorum selection means even if connections are controlled, the attacker must still have high-reputation nodes to influence consensus.

**Implementation:** `ExternalAnchorManager` in `doin_core/consensus/finality.py`; `QuorumManager` in `doin_core/models/quorum.py`.

---

## Category 2: Long-Range Attacks

### Attack #8 — Long-Range History Rewrite

**Description:** An attacker with old keys attempts to rewrite chain history from a point far in the past, creating an alternative history that diverges from the canonical chain.

**Impact:** Complete chain rewrite; all optimization results, reputation scores, and reward distributions could be altered.

**Defense:** `FinalityManager` enforces finality at `confirmation_depth = 6`. Once a block is finalized, it cannot be reverted by any fork. Combined with external anchoring, historical blocks are doubly protected — both by protocol-level finality and by external tamper-evidence.

**Implementation:** `doin_core/consensus/finality.py` — `FinalityManager` with `confirmation_depth=6`.

---

### Attack #9 — Checkpoint Manipulation

**Description:** An attacker attempts to forge or tamper with finality checkpoints to make a fraudulent chain appear legitimate.

**Impact:** False chain accepted as canonical; all downstream state (reputation, rewards) corrupted.

**Defense:** Checkpoints are anchored to an external ledger that the attacker does not control. Forging a checkpoint requires compromising the external system, which is an independent security domain.

**Implementation:** `doin_core/consensus/finality.py` — `ExternalAnchorManager`.

---

### Attack #10 — Stake/Reputation Redistribution

**Description:** An attacker accumulates reputation on one identity, transfers or redistributes it to other identities to amplify influence.

**Impact:** Artificial inflation of multiple nodes' voting power from a single source of earned trust.

**Defense:** Reputation is non-transferable and subject to EMA decay with a half-life of one week. Even if an attacker could somehow clone reputation (they can't), it would decay rapidly without continuous verified contributions from each identity independently.

**Implementation:** `doin_core/models/reputation.py` — `ReputationTracker` with EMA decay.

---

### Attack #11 — Time-Warp Attack

**Description:** An attacker manipulates block timestamps to artificially age blocks, triggering premature finality or skewing time-dependent calculations.

**Impact:** Premature finality on attacker-controlled blocks; manipulated decay calculations.

**Defense:** Timestamp validation ensures blocks have monotonically increasing, reasonable timestamps. Finality is based on block depth (number of confirmations), not wall-clock time, making timestamp manipulation ineffective for triggering early finality.

**Implementation:** `doin_core/consensus/finality.py` — `FinalityManager` uses confirmation depth, not timestamps.

---

## Category 3: Optimization Gaming

### Attack #12 — Hidden Randomness

**Description:** An optimizer uses many random seeds during training, selects the luckiest one that produces anomalously good results, and submits only that result — making their optimization appear better than it genuinely is.

**Impact:** Inflated performance metrics; unfair reward distribution; unreproducible results.

**Defense:** The `DeterministicSeedPolicy` requires that the random seed used in optimization be deterministically derived: `seed = hash(commitment_hash + domain)`. Since the commitment hash is fixed at commit time and the domain is public, the seed is fully determined and verifiable by anyone. The optimizer cannot try multiple seeds — there is exactly one valid seed per commitment.

**Implementation:** `doin_core/consensus/deterministic_seed.py` — `DeterministicSeedPolicy` class.

---

### Attack #13 — Front-Running

**Description:** An attacker monitors the network for submitted optimae (optimization results), sees a good result before it's confirmed, and quickly submits a copy or derivative as their own.

**Impact:** Theft of optimization work; original optimizer loses priority and rewards.

**Defense:** The commit-reveal protocol (`CommitRevealManager`) splits submission into two phases. First, the optimizer commits a hash of their parameters (revealing nothing about the actual values). Later, they reveal the parameters. Since the commitment hash is on-chain before any parameters are visible, front-running is impossible — the attacker has nothing to copy during the commit phase.

**Implementation:** `doin_core/models/commit_reveal.py` — `CommitRevealManager`.

---

### Attack #14 — Parameter Theft

**Description:** After parameters are revealed (phase 2 of commit-reveal), an attacker copies them and claims them as their own work.

**Impact:** Stolen intellectual property; attacker receives credit for another's optimization work.

**Defense:** The blockchain timestamp of the original commitment hash proves priority. The original optimizer's commit transaction has an earlier timestamp than any copy. Dispute resolution can verify that the original commitment predates the theft.

**Implementation:** `doin_core/models/commit_reveal.py` — `CommitRevealManager` records commitment timestamps on-chain.

---

## Category 4: Resource Attacks

### Attack #15 — DoS via Expensive Tasks

**Description:** An attacker submits optimization tasks designed to require excessive computational resources (days of training, terabytes of memory), overwhelming evaluators.

**Impact:** Evaluator nodes crash or become unavailable; network throughput drops; denial of service.

**Defense:** `ResourceLimits` enforces hard caps on all resource-intensive parameters:
- `max_training_seconds` — wall-clock time limit per evaluation
- `max_memory_mb` — memory ceiling
- `max_epochs` — training iteration cap

`BoundsValidator` additionally validates that all submitted parameter values fall within acceptable ranges before any computation begins. Tasks exceeding limits are rejected at submission time.

**Implementation:** `doin_core/models/resource_limits.py` — `ResourceLimits` and `BoundsValidator` classes.

---

### Attack #16 — Storage Bloat

**Description:** An attacker submits blocks with extremely large parameter sets or metadata, bloating chain storage and degrading network performance.

**Impact:** Disk exhaustion on nodes; slower sync times; network degradation.

**Defense:** `BoundsValidator` enforces maximum sizes for parameter vectors and block metadata. Blocks exceeding these bounds are rejected during validation.

**Implementation:** `doin_core/models/resource_limits.py` — `BoundsValidator`.

---

### Attack #21 — OOM (Out-of-Memory) Attack

**Description:** An optimizer submits parameters specifically designed to cause out-of-memory errors when evaluators attempt to load or process them (e.g., extremely high-dimensional parameter tensors).

**Impact:** Evaluator node crashes; potential cascading failures if multiple evaluators are affected simultaneously.

**Defense:** The same `ResourceLimits` and `BoundsValidator` that prevent DoS also prevent OOM attacks. Memory limits (`max_memory_mb`) cap allocation, and bounds validation rejects parameter vectors that would exceed memory when deserialized. Evaluation runs in resource-constrained sandboxes.

**Implementation:** `doin_core/models/resource_limits.py` — `ResourceLimits` (memory caps), `BoundsValidator` (parameter dimension limits).

---

## Category 5: Verification Gaming

### Attack #17 — Rubber-Stamp Evaluators

**Description:** An evaluator always approves every optimum without actually running verification, collecting rewards with zero computational cost.

**Impact:** Invalid optimae accepted into the chain; degraded optimization quality; network loses trustworthiness.

**Defense:** DOIN uses **asymmetric reputation penalties**: the cost of being wrong far exceeds the reward for being right.
- **Reward for correct evaluation:** +0.3 base + 0.1 bonus = 0.4 max
- **Penalty for diverging from quorum:** −3.0

A rubber-stamp evaluator will inevitably approve an optimum that the quorum rejects. A single such disagreement costs 3.0 reputation — wiping out the gains from ~8 correct evaluations. The expected value of rubber-stamping is deeply negative.

**Implementation:** `doin_core/models/reputation.py` — `ReputationTracker` with `PENALTY=3.0`, `REWARD=0.3`, bonus `+0.1`.

---

### Attack #18 — Lazy Evaluation

**Description:** An evaluator returns random or fixed results without performing actual computation, hoping to statistically align with the quorum often enough.

**Impact:** Similar to rubber-stamping — invalid results may be accepted; evaluation quality degrades.

**Defense:** The same asymmetric penalty structure applies. Random results will diverge from the honest quorum frequently enough that the cumulative penalties rapidly destroy the lazy evaluator's reputation, removing them from future consensus participation (below `MIN_REPUTATION_FOR_CONSENSUS=2.0`). Quorum consensus (K-of-N agreement) also means a single random vote is outvoted.

**Implementation:** `doin_core/models/reputation.py` — `ReputationTracker`; `doin_core/models/quorum.py` — `QuorumManager`.

---

### Attack #19 — Parameter Theft via Evaluation

**Description:** An evaluator, who necessarily receives the optimizer's parameters for verification, copies those parameters and submits them as their own optimization work.

**Impact:** Stolen optimization work; evaluator unfairly profits from the optimizer's computational investment.

**Defense:** The commit-reveal protocol proves the optimizer's priority. The optimizer's commitment hash was recorded on-chain before the evaluator ever received the parameters. Any subsequent submission of the same parameters by the evaluator will have a provably later timestamp, making the theft evident and disputable.

**Implementation:** `doin_core/models/commit_reveal.py` — `CommitRevealManager` provides cryptographic priority proof.

---

### Attack #20 — Evaluator Collusion

**Description:** Multiple evaluators conspire to approve or reject specific optimae regardless of actual quality, coordinating their votes to control quorum outcomes.

**Impact:** Fraudulent optimae accepted; legitimate work rejected; colluding group captures rewards.

**Defense:** `QuorumManager` selects evaluators randomly for each verification task. The selection is deterministic based on: `hash(chain_tip_hash + task_id)`, ensuring:
1. **Unpredictability** — evaluators don't know who else is in the quorum until selection
2. **Non-manipulation** — the chain tip hash is not controlled by any single party
3. **Optimizer exclusion** — the optimizer is always excluded from their own evaluation quorum

For collusion to work, the colluding group would need to be selected together, which requires controlling the chain tip hash (see Attack #6) or having enough colluders to statistically dominate random selection (see Attack #1).

**Implementation:** `doin_core/models/quorum.py` — `QuorumManager` with deterministic random selection.

---

## Category 6: Reputation Attacks

### Attack #22 — Incentive Manipulation

**Description:** An attacker exploits the incentive model to extract outsized rewards, for example by strategically timing submissions or gaming tolerance margins.

**Impact:** Unfair reward distribution; economic instability of the network.

**Defense:** The `IncentiveModel` includes a tolerance margin for verification variance (accounting for legitimate floating-point differences across hardware) and a hard bonus cap (`max_bonus_multiplier=1.2`). The tolerance margin is tight enough to catch fraud but loose enough to accommodate honest variance. The bonus cap limits the maximum reward multiplier, preventing any gaming strategy from yielding outsized returns.

**Implementation:** `doin_core/consensus/incentives.py` — `IncentiveModel`.

---

### Attack #23 — Reputation Farming

**Description:** An attacker builds reputation through many easy, uncontroversial tasks, then exploits their high reputation to push through a single fraudulent high-value optimum.

**Impact:** Single high-impact fraud enabled by accumulated trust; damage proportional to the fraudulent optimum's value.

**Defense:** Reputation uses **Exponential Moving Average (EMA) decay** with a half-life of one week. This means:
- Reputation earned a month ago contributes only ~6% of its original value
- An attacker must continuously contribute honest work to maintain high reputation
- A single fraudulent act triggers a −3.0 penalty, which at current decay rates wipes out weeks of farming
- The ratio of farming cost to fraud benefit makes this attack economically irrational

**Implementation:** `doin_core/models/reputation.py` — `ReputationTracker` with EMA decay (half-life = 1 week).

---

### Attack #24 — Under-Reporting

**Description:** An optimizer deliberately reports worse performance than actually achieved, appearing modest to avoid scrutiny, then exploits some assumed advantage of having lower visible metrics.

**Impact:** Minimal — this attack has no viable payoff in DOIN's design.

**Defense:** The bonus cap in the incentive model (`max_bonus_multiplier=1.2`) means there is no advantage to under-reporting. Rewards are based on verified performance, not self-reported metrics. Reporting worse results simply means receiving lower rewards. There is no mechanism by which appearing modest yields future advantage.

**Implementation:** `doin_core/consensus/incentives.py` — `IncentiveModel` with `max_bonus_multiplier=1.2`.

---

## Category 7: Synthetic Data Attacks

### Attack #25 — Training on Verification Data

**Description:** An optimizer reverse-engineers or predicts the synthetic data that evaluators will use for verification, then overfits their model specifically to that data. The submitted optimum performs well on verification but poorly on real tasks.

**Impact:** Fraudulent optimum passes verification despite being overfit/useless; network's optimization quality degrades.

**Defense:** DOIN generates **per-evaluator synthetic data seeds** using: 

```
seed = hash(commitment_hash + domain + evaluator_id + chain_tip_hash)
```

This makes the verification data unpredictable to the optimizer for three independent reasons:

1. **Unknown evaluators** — which evaluators are selected is determined by random quorum selection; the optimizer cannot predict who will evaluate their work
2. **Unknown chain tip** — the chain tip hash at the time of quorum selection is not known at commitment time
3. **Unknown evaluator IDs** — even if the optimizer guessed the evaluators, each evaluator's ID produces a different seed

Each evaluator tests on **different synthetic data**. To overfit, the optimizer would need to predict all three unknowns simultaneously — a computationally infeasible task.

**Implementation:** `get_seed_for_synthetic_data()` function, integrated with `QuorumManager` and `CommitRevealManager`.

---

## Defense-in-Depth Architecture

DOIN's security model is designed as **layered defense-in-depth**. No single mechanism is relied upon in isolation:

```
┌─────────────────────────────────────────────────┐
│             External Anchor Layer                │
│   (ExternalAnchorManager — tamper evidence)      │
├─────────────────────────────────────────────────┤
│             Finality Layer                       │
│   (FinalityManager — irreversible checkpoints)   │
├─────────────────────────────────────────────────┤
│             Consensus Layer                      │
│   (ForkChoiceRule — heaviest chain selection)     │
├─────────────────────────────────────────────────┤
│             Identity & Trust Layer               │
│   (ReputationTracker — earned, decaying trust)   │
├─────────────────────────────────────────────────┤
│             Cryptographic Layer                  │
│   (CommitRevealManager — priority & privacy)     │
│   (DeterministicSeedPolicy — fairness)           │
├─────────────────────────────────────────────────┤
│             Verification Layer                   │
│   (QuorumManager — random, independent eval)     │
│   (Per-evaluator seeds — unique test data)       │
├─────────────────────────────────────────────────┤
│             Resource Layer                       │
│   (ResourceLimits + BoundsValidator — DoS prevention) │
└─────────────────────────────────────────────────┘
```

## Test Coverage

All 10 hardening measures are validated by a comprehensive test suite of **291 tests**, covering:

- Unit tests for each security module
- Integration tests for cross-module interactions (e.g., commit-reveal + quorum selection)
- Adversarial scenario tests simulating each attack vector
- Edge case tests for boundary conditions in resource limits and reputation thresholds

This test suite serves as both validation and living documentation of the security model's implementation completeness.
