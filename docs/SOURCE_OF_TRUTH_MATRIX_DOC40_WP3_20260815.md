# Source-of-Truth Matrix — WP3 Synthetic Contradictions (doc 40 / doc 39)

Date: 2026-08-15
Branch: `satoshi/typed-profiles-spike-20260815` (NON-DEPLOYED spike)
Fixtures: `tests/test_contradictions_doctrine40.py` — each test PASSES by
demonstrating the current contradictory behavior on this commit. When a
contradiction is corrected under owner/auditor disposition, its fixture must
fail and be retired together with its row here.

Authority rule applied (doc 40): present tense belongs to observed
trusted-mode behavior labeled `implemented_prototype`; the untrusted gate is
`conditional_untrusted_research` under doc 39's admission program; neither an
ABC docstring nor a code default constitutes an owner economic decision.

| # | Claim | Where the spec says it | Where the code does otherwise | Which is authoritative under doc 40 | Disposition |
|---|-------|------------------------|-------------------------------|--------------------------------------|-------------|
| 1 | The evaluator quorum shares ONE seed/sample, verified by hash consensus | `src/doin_core/plugins/base.py` `SyntheticDataPlugin` class docstring ("All evaluators in a quorum use the same seed … verified via hash consensus"), `generate()` docstring ("all evaluators get the same seed"), `generate_with_hash()` docstring ("identical synthetic data"); `src/doin_core/models/quorum.py` `evaluate_quorum` docstring step 1 ("hash must match") | `src/doin_core/consensus/deterministic_seed.py` `get_seed_for_synthetic_data()` mixes `evaluator_id` + `chain_tip_hash` → DISTINCT per-evaluator seeds; `quorum.py` `evaluate_quorum` body never compares hashes ("not for consensus") | The RUNTIME direction (distinct draws) — doc 40 §3 ratifies it: "Evaluators may use distinct draws … quorum aggregates a calibrated ensemble statistic; it does not require different draws to have equal hashes." The ABC docstrings and the `evaluate_quorum` docstring are the drift. | Doc-safe: docstring truth-split owned by WP1 (`satoshi/doctrine-truth-split-20260815`); this branch types the correct semantics (`DrawReconstruction`, `DrawCustodyEvidence`). Fixture `test_contradiction_1_…` pins the pre-state. No consensus change needed for the seed policy itself. |
| 2 | No synthetic-data generator ⇒ ZERO consensus weight | `src/doin_core/plugins/base.py` `SyntheticDataPlugin` docstring ("domains without a synthetic data plugin get ZERO consensus weight"); doc 39 §8 ("absence of an admitted generator means zero challenge authority" — untrusted profile) | `src/doin_core/consensus/weights.py` `compute_weights()` grants `verification_strength = 0.5` and `get_effective_increment()` converts it into nonzero consensus-effective increments | PROFILE-DEPENDENT under doc 40: the 0.5 fallback is an `implemented_prototype` code fact tolerable only inside `trusted_consortium`; in `untrusted_generated_gate` ZERO is authoritative (doc 40 §5 lists "treating missing synthetic verification as half-trusted in the untrusted profile" as drift). | Schema-safe done: `UntrustedGeneratedGateProfile` cannot be constructed without an admitted generator; `challenge_authority()` fails closed to 0.0. Behavior change to `weights.py` isolated in the NOT-FOR-DEPLOYMENT commit (opt-in `untrusted_gate_zero_authority` flag, default preserves legacy 0.5). Fixture `test_contradiction_2_…`. |
| 3 | A draw/sample hash identifies the challenge generator | Doc 40 §3 / doc 39 §5.3 state the required rule ("A draw hash must never replace the generator identity"); the code has no spec text distinguishing them — that absence IS the defect | `src/doin_core/models/quorum.py` `VerificationVote.synthetic_data_hash` is the ONLY hash slot in the verification path, an untyped string fed by `generate_with_hash()`; no generator-identity field exists in vote/state/result, and any 64-hex string (including a manifest hash) is accepted there | Doc 40 §3: two DISTINCT typed objects, generator identity vs draw custody; the sample hash may never stand in for the mechanism identity. | Schema-safe done: `GeneratorIdentityManifest` vs `DrawCustodyEvidence` with `require_generator_identity()` typed refusal (this branch). Wiring manifests into quorum votes changes deployed consensus → DEFERRED to owner/auditor disposition. Fixture `test_contradiction_3_…`. |
| 4 | Distinct synthetic draws may be accepted on performance tolerance alone | Doc 40 §3: distinct draws are legitimate ONLY when "each draw must be reproducible after the fact from its recorded seed_i and immutable manifest"; doc 39 §5.2 requires seed basis + generator hashes in signed evidence | `src/doin_core/models/quorum.py` `evaluate_quorum()` accepts distinct-hash votes within `QuorumConfig.tolerance` while carrying ZERO manifest evidence — nothing binds the draws to one immutable generator, and the tolerance itself is uncalibrated (doc 39 §7 prohibits arbitrary margins) | Doc 40 §3 / doc 39 §7: tolerance acceptance is conditional on manifest binding + calibration; the current unconditional acceptance is prototype drift. | Schema-safe done: `DrawCustodyEvidence.manifest_hash` binding, `verify_draw_reproduction()`, and `EvidenceQuorumTolerance.calibration_artifact_hash` (this branch). Enforcing them inside `QuorumManager` changes deployed consensus → DEFERRED. Fixture `test_contradiction_4_…`. |
| 5 | Missing generator-admission evidence still influences consensus | Doc 39 §8 / doc 40 §2.2: "No current domain has passed the complete admission program. Therefore no current domain has nonzero authority under this untrusted profile." | End-to-end path: `weights.py` 0.5 fallback → `get_effective_increment()` > 0 → `proof_of_optimization.py` `record_optimae()`/`can_generate_block()` → `generate_block()` mints a block; `quorum.py` also accepts votes with `used_synthetic=False` and empty hash | PROFILE-DEPENDENT: legal inside `trusted_consortium` as the NAMED re-evaluation capability (doc 40 §2.1); ZERO authority in the untrusted profile. The runtime has no profile gate at all, which is the defect. | Schema-safe done: typed profiles + `validate_evidence_for_profile()` fail closed on unknown/mixed semantics (this branch). Runtime profile gating of weights/quorum/PoO changes deployed consensus → DEFERRED (exemplar opt-in patch in the NOT-FOR-DEPLOYMENT commit). Fixture `test_contradiction_5_…`. |

## Pre/post state on this branch

* PRE (reproduced): all five fixtures pass against unmodified consensus
  modules — the contradictions are executable facts on this commit.
* POST (schema-safe corrections, this branch): typed fail-closed objects
  exist for every contradicted concept; legacy replay is pinned by
  `tests/test_legacy_replay_preservation.py` (genesis hash, field surfaces,
  round-trip hashes, balance replay, prototype distribution).
* POST (behavior-changing, NOT deployed): one exemplar opt-in patch
  (`weights.py` `untrusted_gate_zero_authority`, default off) sits in its own
  commit marked NOT-FOR-DEPLOYMENT; quorum manifest binding and PoO profile
  gating remain design work for owner/auditor disposition.

No owner decision is inferred from code comments; no current-behavior claim
is rewritten as target behavior — prototype facts stay labeled
`implemented_prototype` and target policy objects stay labeled
`owner_directed_target` at the type level.
