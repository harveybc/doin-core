"""Tests for dynamic quorum sizing."""

import math
import pytest
from doin_core.consensus.dynamic_quorum import DynamicQuorum, DynamicQuorumConfig


@pytest.fixture
def dq():
    return DynamicQuorum()


# --- Minimum floor ---

def test_min_floor_zero_evaluators(dq):
    assert dq.compute_quorum_size("d1", 0.5, 0, 0.5) == 3

def test_min_floor_one_evaluator(dq):
    assert dq.compute_quorum_size("d1", 0.5, 1, 0.0) == 3

def test_min_floor_high_reputation(dq):
    """Even max discount can't go below 3."""
    assert dq.compute_quorum_size("d1", 1.0, 4, 0.0) == 3

def test_min_floor_negative_evaluators(dq):
    assert dq.compute_quorum_size("d1", 0.5, -5, 0.5) == 3


# --- Maximum cap ---

def test_max_cap_large_network(dq):
    result = dq.compute_quorum_size("d1", 0.0, 1000, 1.0)
    assert result <= 15

def test_max_cap_is_half_evaluators():
    """With 20 evaluators, max = min(15, 10) = 10."""
    dq = DynamicQuorum()
    result = dq.compute_quorum_size("d1", 0.0, 20, 1.0)
    assert result <= 10

def test_max_cap_small_network(dq):
    """With 8 evaluators, max = min(15, 4) = 4, but floor is 3."""
    result = dq.compute_quorum_size("d1", 0.0, 8, 1.0)
    assert 3 <= result <= max(3, 8 // 2)


# --- Scaling with evaluator count ---

def test_scaling_increases_with_evaluators(dq):
    r1 = dq.compute_quorum_size("d1", 0.5, 10, 0.5)
    r2 = dq.compute_quorum_size("d1", 0.5, 100, 0.5)
    assert r2 >= r1

def test_scaling_log2_component(dq):
    # 64 evaluators: log2(64)=6, base=3, activity(0.5)=2, rep(0.5)=0 => raw=11
    # max = min(15, 32) = 15; clamp(11, 3, 15) = 11
    assert dq.compute_quorum_size("d1", 0.5, 64, 0.5) == 11


# --- Reputation discount ---

def test_reputation_discount_zero(dq):
    """Rep < 0.7 gives no discount."""
    r = dq.compute_quorum_size("d1", 0.3, 64, 0.0)
    assert r == 3 + int(math.log2(64))  # 9

def test_reputation_discount_one(dq):
    """Rep 0.7-0.89 gives discount 1."""
    r = dq.compute_quorum_size("d1", 0.8, 64, 0.0)
    assert r == 3 + int(math.log2(64)) - 1  # 8

def test_reputation_discount_two(dq):
    """Rep >= 0.9 gives discount 2."""
    r = dq.compute_quorum_size("d1", 0.95, 64, 0.0)
    assert r == 3 + int(math.log2(64)) - 2  # 7


# --- Activity bonus ---

def test_activity_bonus_zero(dq):
    r = dq.compute_quorum_size("d1", 0.0, 64, 0.1)
    assert r == 3 + 6  # 9, no bonus

def test_activity_bonus_low(dq):
    r = dq.compute_quorum_size("d1", 0.0, 64, 0.3)
    assert r == 3 + 6 + 1  # 10

def test_activity_bonus_medium(dq):
    r = dq.compute_quorum_size("d1", 0.0, 64, 0.6)
    assert r == 3 + 6 + 2  # 11

def test_activity_bonus_high(dq):
    r = dq.compute_quorum_size("d1", 0.0, 64, 0.8)
    assert r == 3 + 6 + 3  # 12


# --- Edge cases ---

def test_very_high_activity_capped(dq):
    result = dq.compute_quorum_size("d1", 0.0, 20, 1.0)
    assert result <= 10  # min(15, 20//2)

def test_get_quorum_params(dq):
    params = dq.get_quorum_params()
    assert params["base"] == 3
    assert params["min_quorum"] == 3
    assert params["max_quorum_cap"] == 15

def test_custom_config():
    cfg = DynamicQuorumConfig(base=5, min_quorum=5, max_quorum_cap=20)
    dq = DynamicQuorum(cfg)
    assert dq.compute_quorum_size("d1", 0.5, 0, 0.5) == 5
