"""Economic counterexample packet (WP4, 2026-08-15).

Socket-free fixtures documenting the economic behavior of the doin-core
prototype. Every test is labeled either:

- ``reproduced_current_behavior`` — pins what the code does TODAY. These
  tests are evidence, not endorsement: passing them does NOT declare the
  behavior correct.
- ``proposed_target_behavior`` — expresses owner-directed target economics
  that the current prototype does NOT implement. These are marked
  ``xfail(strict=True)`` so they document the gap without changing code.

SCOPE DISCLAIMER (required by the doctrine order): the only behavior
CORRECTED by this packet is transaction-fee conservation in
``distribute_block_reward`` — an arithmetic bug fix. NO BROADER TOKEN
DISTRIBUTION IS DECLARED CORRECT BY THESE TESTS. In particular the
50-coin subsidy, the halving schedule, the 21M cap, empty-block minting,
time-targeted threshold adjustment, the 0.5 verification-strength
fallback, the task-count demand proxy and the weighted raw cross-domain
sum remain ``implemented_prototype`` facts awaiting versioned replacement
(work plan 40, section 5).

Numeric tolerance statement: conservation is asserted with
``math.isclose(rel_tol=0.0, abs_tol=1e-12)``. The fixed code computes the
generator output as the exact residual ``total_reward - sum(pool outputs)``,
so the invariant holds to a few float64 ULPs (~1e-14 at these magnitudes);
1e-12 is four orders of magnitude below MIN_REWARD (1e-8), the smallest
emittable amount. Amounts below MIN_REWARD are burned by design; no fixture
here produces a sub-MIN_REWARD residual.

Legacy replay note: coinbase outputs are stored data — ``BalanceTracker.
rebuild_from_chain`` replays stored amounts and block header hashes do not
commit to coinbase outputs — so the conservation fix does not invalidate
any historical block or replay. See test class docstrings and the WP4
report for the deployment consideration (fleet-simultaneous upgrade for
consistent go-forward balances).
"""

from __future__ import annotations

import inspect
import math

import pytest

from doin_core.consensus.difficulty import DifficultyController
from doin_core.consensus.proof_of_optimization import ProofOfOptimization
from doin_core.consensus.weights import VerifiedUtilityWeights, WeightConfig
from doin_core.models.block import Block
from doin_core.models.coin import (
    EVALUATOR_POOL_FRACTION,
    GENERATOR_FEE_FRACTION,
    MIN_REWARD,
    OPTIMIZER_POOL_FRACTION,
    BalanceTracker,
    ContributorWork,
    TransferTransaction,
    compute_block_reward,
    distribute_block_reward,
)
from doin_core.models.domain import Domain, DomainConfig
from doin_core.models.optimae import Optimae
from doin_core.models.transaction import TransactionType


def _conserved(coinbase, block_reward: float, tx_fees: float) -> bool:
    """Fee-conservation invariant: every coin allocated exactly once."""
    return math.isclose(
        coinbase.total_distributed,
        block_reward + tx_fees,
        rel_tol=0.0,
        abs_tol=1e-12,
    )


def _domain(domain_id: str, weight: float = 1.0) -> Domain:
    return Domain(
        id=domain_id,
        name=domain_id,
        performance_metric="metric",
        weight=weight,
        config=DomainConfig(
            optimization_plugin="test.opt",
            inference_plugin="test.inf",
        ),
    )


def _optimizer(peer: str, increment: float, fraction: float = 1.0,
               domain: str = "d1") -> ContributorWork:
    return ContributorWork(
        peer_id=peer, role="optimizer", domain_id=domain,
        effective_increment=increment, reward_fraction=fraction,
    )


def _evaluator(peer: str, evaluations: int, agreed: bool = True,
               domain: str = "d1") -> ContributorWork:
    return ContributorWork(
        peer_id=peer, role="evaluator", domain_id=domain,
        evaluations_completed=evaluations, agreed_with_quorum=agreed,
    )


# ─────────────────────────────────────────────────────────────────────
# 1. Fee conservation — the arithmetic bug fix
# ─────────────────────────────────────────────────────────────────────

def _pre_fix_distribution_total(block_reward: float, tx_fees: float) -> float:
    """Verbatim replica of the PRE-FIX arithmetic for the no-contributor
    case, kept as permanent evidence of the defect shape.

    Pre-fix code (models/coin.py before 2026-08-15):
      total_reward       = block_reward + tx_fees
      generator_reward   = total_reward * 0.05 + tx_fees      # fees counted once
      distributable      = total_reward - total_reward * 0.05  # fees counted AGAIN
      optimizer_pool     = distributable * 0.65  -> cascaded to evaluator pool
      evaluator_pool     = distributable * 0.30 + cascade      -> to generator
    Total paid = generator_reward + distributable = total + tx_fees over-mint,
    minus nothing (negative remainder was silently ignored).
    """
    total_reward = block_reward + tx_fees
    generator_reward = total_reward * GENERATOR_FEE_FRACTION + tx_fees
    distributable = total_reward - total_reward * GENERATOR_FEE_FRACTION
    evaluator_bonus = distributable * OPTIMIZER_POOL_FRACTION  # no optimizers
    evaluator_pool = distributable * EVALUATOR_POOL_FRACTION + evaluator_bonus
    generator_reward += evaluator_pool  # no evaluators
    return generator_reward


class TestFeeConservationDefectEvidence:
    """reproduced_current_behavior (pre-fix): the observed 50 + 10 -> 67.15.

    The replica pins the defect arithmetic forever, independent of the
    live code. Observed on the pre-fix module: a block with reward 50,
    tx fees 10 and NO contributors produced a single generator output of
    67.15 although only 60.0 existed (over-mint 7.15 = fees double-counted
    10 minus 2.85 undistributed pool slack).
    """

    def test_pre_fix_formula_reproduces_67_15(self):
        total = _pre_fix_distribution_total(50.0, 10.0)
        assert math.isclose(total, 67.15, rel_tol=0.0, abs_tol=1e-9)
        # And it violates conservation by exactly 7.15:
        assert math.isclose(total - 60.0, 7.15, rel_tol=0.0, abs_tol=1e-9)

    def test_live_code_no_longer_reproduces_the_defect(self):
        """proposed_target_behavior (now implemented — the bug fix)."""
        cb = distribute_block_reward(1, "gen", [], tx_fees=10.0)
        assert math.isclose(cb.total_distributed, 60.0,
                            rel_tol=0.0, abs_tol=1e-12)
        assert not math.isclose(cb.total_distributed, 67.15,
                                rel_tol=0.0, abs_tol=1e-9)


class TestFeeConservationInvariant:
    """proposed_target_behavior (now implemented — the bug fix).

    Invariant: sum(outputs) == block_reward + tx_fees for every
    nonnegative fixture. Each fee allocated exactly once.
    """

    BLOCK_INDEX = 1  # subsidy = 50.0
    SUBSIDY = 50.0

    @pytest.mark.parametrize("tx_fees", [0.0, 10.0, 0.123456789])
    def test_empty_block(self, tx_fees):
        cb = distribute_block_reward(self.BLOCK_INDEX, "gen", [], tx_fees=tx_fees)
        assert _conserved(cb, self.SUBSIDY, tx_fees)
        # Everything (subsidy + fees) goes to the generator.
        assert len(cb.outputs) == 1
        assert cb.outputs[0].recipient == "gen"

    @pytest.mark.parametrize("tx_fees", [0.0, 10.0])
    def test_optimizer_only(self, tx_fees):
        contributors = [_optimizer("opt-1", 2.0), _optimizer("opt-2", 1.0)]
        cb = distribute_block_reward(self.BLOCK_INDEX, "gen", contributors,
                                     tx_fees=tx_fees)
        assert _conserved(cb, self.SUBSIDY, tx_fees)

    @pytest.mark.parametrize("tx_fees", [0.0, 10.0])
    def test_evaluator_only(self, tx_fees):
        contributors = [_evaluator("ev-1", 3), _evaluator("ev-2", 1)]
        cb = distribute_block_reward(self.BLOCK_INDEX, "gen", contributors,
                                     tx_fees=tx_fees)
        assert _conserved(cb, self.SUBSIDY, tx_fees)

    @pytest.mark.parametrize("tx_fees", [0.0, 10.0, 3.7])
    def test_mixed_contributors(self, tx_fees):
        contributors = [
            _optimizer("opt-1", 2.0), _optimizer("opt-2", 1.0, fraction=0.3),
            _evaluator("ev-1", 3), _evaluator("ev-2", 1),
            _evaluator("ev-bad", 5, agreed=False),
        ]
        cb = distribute_block_reward(self.BLOCK_INDEX, "gen", contributors,
                                     tx_fees=tx_fees)
        assert _conserved(cb, self.SUBSIDY, tx_fees)
        # Dishonest evaluator still excluded.
        assert sum(o.amount for o in cb.outputs
                   if o.recipient == "ev-bad") == 0.0

    def test_zero_reward_zero_fees(self):
        # Past the last halving: subsidy is exactly 0.
        idx = 210_000 * 64
        assert compute_block_reward(idx) == 0.0
        cb = distribute_block_reward(idx, "gen", [_optimizer("opt", 1.0)],
                                     tx_fees=0.0)
        assert cb.total_distributed == 0.0
        assert cb.outputs == []

    def test_fees_only_zero_reward(self):
        idx = 210_000 * 64
        cb = distribute_block_reward(idx, "gen", [_optimizer("opt", 1.0)],
                                     tx_fees=10.0)
        assert _conserved(cb, 0.0, 10.0)
        # With zero subsidy the pools are zero: fees go wholly, and only,
        # to the generator — never to pools.
        assert len(cb.outputs) == 1
        assert cb.outputs[0].recipient == "gen"
        assert math.isclose(cb.outputs[0].amount, 10.0,
                            rel_tol=0.0, abs_tol=1e-12)

    def test_declared_prototype_shares_preserved(self):
        """5% generator / 65% optimizer / 30% evaluator of the minted
        subsidy, plus ALL tx fees to the generator (resolution rule)."""
        tx_fees = 10.0
        contributors = [_optimizer("opt", 1.0), _evaluator("ev", 2)]
        cb = distribute_block_reward(self.BLOCK_INDEX, "gen", contributors,
                                     tx_fees=tx_fees)
        gen = sum(o.amount for o in cb.outputs if o.recipient == "gen")
        opt = sum(o.amount for o in cb.outputs if o.recipient == "opt")
        ev = sum(o.amount for o in cb.outputs if o.recipient == "ev")
        assert math.isclose(opt, self.SUBSIDY * OPTIMIZER_POOL_FRACTION,
                            rel_tol=0.0, abs_tol=1e-12)          # 32.5
        assert math.isclose(ev, self.SUBSIDY * EVALUATOR_POOL_FRACTION,
                            rel_tol=0.0, abs_tol=1e-12)          # 15.0
        assert math.isclose(
            gen, self.SUBSIDY * GENERATOR_FEE_FRACTION + tx_fees,
            rel_tol=0.0, abs_tol=1e-12)                          # 2.5 + 10
        assert _conserved(cb, self.SUBSIDY, tx_fees)

    def test_end_to_end_fee_cycle_conserves_supply(self):
        """Fees leave the sender at transfer time and re-enter exactly once
        via the next coinbase: total balances == total subsidies minted."""
        tracker = BalanceTracker()
        cb1 = distribute_block_reward(1, "gen", [], tx_fees=0.0)
        tracker.apply_coinbase(cb1)  # gen: 50

        ok, reason = tracker.apply_transfer(TransferTransaction(
            sender="gen", recipient="alice", amount=20.0, fee=10.0, nonce=1,
        ))
        assert ok, reason
        # 10.0 of fees are momentarily out of circulation, then paid to the
        # next block's generator:
        cb2 = distribute_block_reward(2, "gen2", [], tx_fees=10.0)
        tracker.apply_coinbase(cb2)

        total_balances = sum(tracker.all_balances.values())
        assert math.isclose(total_balances, 50.0 + 50.0,
                            rel_tol=0.0, abs_tol=1e-12)


# ─────────────────────────────────────────────────────────────────────
# 2. Empty event block, zero progress → zero mint (target, not current)
# ─────────────────────────────────────────────────────────────────────

class TestEmptyBlockMinting:
    """Current prototype mints the full subsidy for a block with zero
    progress and zero contributors; the owner-directed target is zero
    mint without progress. Only documented here — the conservation fix
    deliberately does NOT change minting policy."""

    def test_empty_event_block_mints_full_subsidy(self):
        """reproduced_current_behavior."""
        empty_block = Block.genesis("gen")  # no transactions, progress 0.0
        assert empty_block.transactions == []
        assert empty_block.header.weighted_performance_sum == 0.0

        cb = distribute_block_reward(1, "gen", contributors=[], tx_fees=0.0)
        assert cb.total_distributed == pytest.approx(50.0)
        assert cb.outputs[0].recipient == "gen"  # generator paid for nothing

    @pytest.mark.xfail(
        strict=True,
        reason="proposed_target_behavior: an event block with zero verified "
               "progress should mint nothing (issuance follows progress, not "
               "cadence). Current prototype mints the full 50-coin subsidy.",
    )
    def test_empty_event_block_zero_progress_zero_mint(self):
        """proposed_target_behavior."""
        cb = distribute_block_reward(1, "gen", contributors=[], tx_fees=0.0)
        assert cb.total_distributed == 0.0


# ─────────────────────────────────────────────────────────────────────
# 3. Time-targeted threshold: the quality bar moves to meet cadence
# ─────────────────────────────────────────────────────────────────────

class TestThresholdDropsToMeetCadence:
    """reproduced_current_behavior: under the current time-targeted
    adjustment, a network producing only tiny progress does not slow
    issuance — the THRESHOLD drops until tiny progress clears it."""

    def test_tiny_progress_after_long_interval_lowers_the_bar(self):
        controller = DifficultyController(
            target_block_time=600.0,
            initial_threshold=1.0,
            epoch_length=10,
        )
        bar_before = controller.threshold
        tiny_progress = 0.30
        assert tiny_progress < bar_before  # fails the original quality bar

        # Blocks arrive 4x slower than target (2400s instead of 600s)
        # because only tiny increments are being found.
        t = controller.state.last_block_time
        for i in range(1, 11):
            t += 2400.0
            controller.on_new_block(block_index=i, block_timestamp=t)

        bar_after = controller.threshold
        # The bar DROPPED — epoch rule multiplies by clamp(target/actual)=0.25
        # plus per-block EMA corrections in the same direction.
        assert bar_after < bar_before
        assert bar_after <= 0.25 * bar_before
        # The same tiny progress that failed the old bar now clears it:
        assert tiny_progress >= bar_after
        # i.e. the "difficulty" is a cadence controller, not a fixed quality
        # bar: elapsed time alone converts unacceptable progress into an
        # acceptable, fully rewarded block.


# ─────────────────────────────────────────────────────────────────────
# 4. No notion of an external frontier
# ─────────────────────────────────────────────────────────────────────

class TestNoExternalFrontier:
    """reproduced_current_behavior: the protocol has no representation of
    an external (off-chain) frontier, so a local increment is accepted and
    rewarded even when the outside world has already surpassed it — the
    increment is economically stale but paid in full."""

    def _record_local_increment(self) -> ProofOfOptimization:
        poo = ProofOfOptimization(initial_threshold=1.0)
        poo.register_domain(_domain("d1", weight=1.0))
        poo.record_optimae(Optimae(
            domain_id="d1",
            optimizer_id="opt-local",
            parameters={"w": [1.0]},
            reported_performance=0.61,
            verified_performance=0.61,
            performance_increment=0.01,  # tiny improvement over LOCAL best 0.60
        ))
        return poo

    def test_stale_local_increment_is_credited_and_paid_regardless(self):
        # World A: no better model exists anywhere.
        # World B: an external frontier of 0.95 (out of band) dwarfs the
        # local 0.61. The protocol cannot even EXPRESS world B: both worlds
        # produce byte-identical consensus credit and coinbase.
        poo_a = self._record_local_increment()
        poo_b = self._record_local_increment()
        external_frontier_world_b = 0.95  # exists only in this test
        assert external_frontier_world_b > 0.61

        assert poo_a.weighted_sum == poo_b.weighted_sum == pytest.approx(0.01)

        contributors = [_optimizer("opt-local", 0.01)]
        cb_a = distribute_block_reward(1, "gen", contributors)
        cb_b = distribute_block_reward(1, "gen", contributors)
        pay_a = sum(o.amount for o in cb_a.outputs if o.recipient == "opt-local")
        pay_b = sum(o.amount for o in cb_b.outputs if o.recipient == "opt-local")
        assert pay_a == pay_b > 0  # stale increment fully rewarded

    def test_no_api_surface_for_an_external_frontier(self):
        # No model field or consensus parameter can carry an external
        # frontier: acceptance is purely local-history-relative.
        assert not any("frontier" in name.lower()
                       for name in Optimae.model_fields)
        assert not any("frontier" in name.lower()
                       for name in Domain.model_fields)
        sig = inspect.signature(ProofOfOptimization.record_optimae)
        assert list(sig.parameters) == ["self", "optimae"]


# ─────────────────────────────────────────────────────────────────────
# 5. No numeraire: raw weighted sum reverses order under unit rescaling
# ─────────────────────────────────────────────────────────────────────

class TestCrossDomainSumHasNoNumeraire:
    """reproduced_current_behavior: cross-domain progress is a weighted sum
    of RAW increments in incommensurable units. A pure unit change in one
    domain's metric reverses which candidate contribution ranks higher, so
    the sum cannot be an economic value measure."""

    @staticmethod
    def _weighted_sum(acc_increment: float, sharpe_increment: float,
                      sharpe_unit_scale: float) -> float:
        """Run the ACTUAL consensus accounting for one block's worth of
        increments: accuracy domain in [0, 1], Sharpe-like domain whose
        declared unit is scaled by sharpe_unit_scale (same information)."""
        poo = ProofOfOptimization(initial_threshold=1e9)  # never triggers
        poo.register_domain(_domain("acc", weight=1.0))
        poo.register_domain(_domain("sharpe", weight=1.0))
        poo.record_optimae(Optimae(
            domain_id="acc", optimizer_id="a", parameters={},
            reported_performance=0.9,
            performance_increment=acc_increment,
        ))
        poo.record_optimae(Optimae(
            domain_id="sharpe", optimizer_id="b", parameters={},
            reported_performance=2.0 * sharpe_unit_scale,
            performance_increment=sharpe_increment * sharpe_unit_scale,
        ))
        return poo.weighted_sum

    def test_unit_rescaling_reverses_cross_domain_ranking(self):
        # Candidate A: small accuracy gain, large Sharpe gain.
        # Candidate B: large accuracy gain, small Sharpe gain.
        a_acc, a_sharpe = 0.10, 0.50   # Sharpe-like native units in [-3, 3]
        b_acc, b_sharpe = 0.30, 0.20

        # Native units: A ranks above B.
        sum_a = self._weighted_sum(a_acc, a_sharpe, sharpe_unit_scale=1.0)
        sum_b = self._weighted_sum(b_acc, b_sharpe, sharpe_unit_scale=1.0)
        assert sum_a == pytest.approx(0.60)
        assert sum_b == pytest.approx(0.50)
        assert sum_a > sum_b

        # Rescale the Sharpe-like metric to [0, 1] (divide by its 6-wide
        # range) — SAME candidates, SAME information, different unit:
        sum_a2 = self._weighted_sum(a_acc, a_sharpe, sharpe_unit_scale=1 / 6)
        sum_b2 = self._weighted_sum(b_acc, b_sharpe, sharpe_unit_scale=1 / 6)
        assert sum_a2 == pytest.approx(0.10 + 0.50 / 6)  # ~0.1833
        assert sum_b2 == pytest.approx(0.30 + 0.20 / 6)  # ~0.3333
        assert sum_b2 > sum_a2  # ranking REVERSED by a unit change

        # Decisive: order(A, B) is not invariant under unit rescaling, so
        # the weighted raw sum is a scheduling statistic, not a numeraire.


# ─────────────────────────────────────────────────────────────────────
# 6. Task-count spam inflates observed_on_chain_task_share
# ─────────────────────────────────────────────────────────────────────

def _inference_completed_tx(domain_id: str) -> dict:
    """A cheap task_completed/inference_request event as counted by VUW."""
    return {
        "tx_type": "task_completed",
        "domain_id": domain_id,
        "payload": {"task_type": "inference_request"},
    }


class TestTaskCountSpamInflatesDemandProxy:
    """reproduced_current_behavior: demand_factor is
    inference_tasks_completed / total  (a.k.a. observed_on_chain_task_share)
    — a censored task COUNT with no cost, payment or identity weighting, so
    self-generated cheap requests inflate a domain's weight."""

    def test_spam_domain_weight_inflated_by_cheap_completions(self):
        vuw = VerifiedUtilityWeights(WeightConfig())
        vuw.register_domain("real", base_weight=1.0, has_synthetic_data=True)
        vuw.register_domain("spam", base_weight=1.0, has_synthetic_data=True)

        baseline = vuw.compute_weights()
        assert baseline["real"] == pytest.approx(baseline["spam"])

        # An attacker floods 990 near-zero-cost inference completions in its
        # own domain; the honest domain serves 10 genuine requests.
        vuw.update_from_block([_inference_completed_tx("spam")] * 990)
        vuw.update_from_block([_inference_completed_tx("real")] * 10)

        weights = vuw.compute_weights()
        spam_share = vuw.get_stats("spam").inference_tasks_completed / 1000
        assert spam_share == pytest.approx(0.99)  # observed_on_chain_task_share
        # demand_factor: spam 0.99 vs real max(0.1 floor, 0.01) = 0.1
        assert weights["spam"] / weights["real"] == pytest.approx(9.9)
        # Nothing in the accounting distinguishes paid demand from
        # self-generated spam: the proxy counts events, not willingness
        # to pay. It is not a price.


# ─────────────────────────────────────────────────────────────────────
# 7. Public artifact download vs paid hosted inference
# ─────────────────────────────────────────────────────────────────────

class TestServingIsCountedButNeverPaid:
    """reproduced_current_behavior: EVALUATION_SERVED events feed on-chain
    task accounting, and champion parameters ride the chain publicly, but
    NO coinbase output ever pays the peer that served the inference —
    hosting is an uncompensated cost while its count inflates the demand
    proxy (deliverable 6)."""

    def test_evaluation_served_recorded_on_chain(self):
        poo = ProofOfOptimization(initial_threshold=1.0)
        poo.register_domain(_domain("d1"))
        for i in range(5):
            poo.record_evaluation("d1", peer_id="server-1",
                                  request_id=f"req-{i}")
        served = [tx for tx in poo.state.pending_transactions
                  if tx.tx_type == TransactionType.EVALUATION_SERVED]
        assert len(served) == 5
        assert all(tx.peer_id == "server-1" for tx in served)

    def test_served_inference_feeds_the_task_count_proxy(self):
        # The node-side accounting of completed inference requests (as in
        # doin-node) flows into the same VUW count shown in deliverable 6:
        vuw = VerifiedUtilityWeights()
        vuw.register_domain("d1", has_synthetic_data=True)
        vuw.register_domain("d2", has_synthetic_data=True)
        vuw.update_from_block([_inference_completed_tx("d1")] * 8)
        weights = vuw.compute_weights()
        assert weights["d1"] > weights["d2"]  # serving raised d1's weight

    def test_no_coinbase_output_pays_the_inference_server(self):
        # The server peer contributed 5 served inferences (above), yet the
        # reward schema only knows optimizer/evaluator/generator roles:
        contributors = [
            _optimizer("opt-1", 1.0),
            _evaluator("ev-1", 2),
            # A "server" contribution cannot even be expressed: ContributorWork
            # with role "inference_server" matches no pool and earns nothing.
            ContributorWork(peer_id="server-1", role="inference_server",
                            domain_id="d1"),
        ]
        cb = distribute_block_reward(1, "gen", contributors, tx_fees=0.0)
        server_pay = sum(o.amount for o in cb.outputs
                         if o.recipient == "server-1")
        assert server_pay == 0.0
        assert {o.reason for o in cb.outputs} <= {
            "block_generator", "optimizer", "evaluator",
        }

    def test_champion_artifact_is_public_on_chain_data(self):
        # The artifact itself (parameters) is a plain public field of the
        # on-chain Optimae object — freely downloadable by any chain reader.
        # Payment for hosted inference is therefore a SEPARATE good that the
        # current coinbase does not implement (work plan 40, section 6).
        assert "parameters" in Optimae.model_fields
        opt = Optimae(domain_id="d1", optimizer_id="o", parameters={"w": [1]},
                      reported_performance=1.0)
        assert opt.parameters == {"w": [1]}  # no access control, no payment gate
