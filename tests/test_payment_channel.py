"""Tests for L2 payment channels."""

import time
import pytest

from doin_core.models.payment_channel import (
    ChannelConfig,
    ChannelState,
    PaymentChannel,
    PaymentChannelManager,
    PaymentUpdate,
)


class TestChannelOpen:

    def test_open_channel(self):
        mgr = PaymentChannelManager()
        ch, err = mgr.open_channel("ch-1", "alice", "bob", 100.0)
        assert ch is not None
        assert err == ""
        assert ch.state == ChannelState.OPEN
        assert ch.sender_balance == 100.0
        assert ch.receiver_balance == 0.0

    def test_open_below_min_deposit(self):
        mgr = PaymentChannelManager(ChannelConfig(min_deposit=10.0))
        ch, err = mgr.open_channel("ch-1", "alice", "bob", 5.0)
        assert ch is None
        assert "below minimum" in err

    def test_open_above_max_deposit(self):
        mgr = PaymentChannelManager(ChannelConfig(max_deposit=100.0))
        ch, err = mgr.open_channel("ch-1", "alice", "bob", 500.0)
        assert ch is None
        assert "above maximum" in err

    def test_open_duplicate_id(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        ch, err = mgr.open_channel("ch-1", "alice", "carol", 50.0)
        assert ch is None
        assert "already exists" in err

    def test_open_self_channel(self):
        mgr = PaymentChannelManager()
        ch, err = mgr.open_channel("ch-1", "alice", "alice", 100.0)
        assert ch is None
        assert "yourself" in err

    def test_per_peer_limit(self):
        mgr = PaymentChannelManager(ChannelConfig(max_channels_per_peer=2))
        mgr.open_channel("ch-1", "alice", "bob", 10.0)
        mgr.open_channel("ch-2", "alice", "carol", 10.0)
        ch, err = mgr.open_channel("ch-3", "alice", "dave", 10.0)
        assert ch is None
        assert "too many" in err

    def test_total_locked(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        mgr.open_channel("ch-2", "carol", "dave", 50.0)
        assert mgr.total_locked == 150.0


class TestPayments:

    def test_basic_payment(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        update, err = mgr.pay("ch-1", 10.0, "alice")
        assert update is not None
        assert err == ""
        assert update.sender_balance == 90.0
        assert update.receiver_balance == 10.0
        assert update.nonce == 1

    def test_multiple_payments(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        mgr.pay("ch-1", 10.0, "alice")
        mgr.pay("ch-1", 20.0, "alice")
        update, _ = mgr.pay("ch-1", 5.0, "alice")
        assert update.sender_balance == 65.0
        assert update.receiver_balance == 35.0
        assert update.nonce == 3

    def test_insufficient_balance(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        update, err = mgr.pay("ch-1", 150.0, "alice")
        assert update is None
        assert "Insufficient" in err

    def test_zero_payment(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        update, err = mgr.pay("ch-1", 0, "alice")
        assert update is None
        assert "positive" in err

    def test_wrong_sender(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        update, err = mgr.pay("ch-1", 10.0, "bob")
        assert update is None
        assert "sender" in err.lower()

    def test_pay_closed_channel(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        mgr.close_channel("ch-1", "alice")
        update, err = mgr.pay("ch-1", 10.0, "alice")
        assert update is None
        assert "not active" in err.lower()

    def test_channel_not_found(self):
        mgr = PaymentChannelManager()
        update, err = mgr.pay("nope", 10.0, "alice")
        assert update is None
        assert "not found" in err


class TestClose:

    def test_cooperative_close(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        mgr.pay("ch-1", 30.0, "alice")

        result, err = mgr.close_channel("ch-1", "alice")
        assert result is not None
        assert result["sender_refund"] == 70.0
        assert result["receiver_payout"] == 30.0 * (1 - 0.001)  # 0.1% fee
        assert result["fee"] > 0
        assert mgr.get_channel("ch-1").state == ChannelState.CLOSED

    def test_close_no_payments(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        result, _ = mgr.close_channel("ch-1", "bob")
        assert result["sender_refund"] == 100.0
        assert result["receiver_payout"] == 0.0

    def test_close_already_closed(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        mgr.close_channel("ch-1", "alice")
        result, err = mgr.close_channel("ch-1", "alice")
        assert result is None
        assert "already closed" in err

    def test_close_unlocks_funds(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        assert mgr.total_locked == 100.0
        mgr.close_channel("ch-1", "alice")
        assert mgr.total_locked == 0.0

    def test_non_participant_cannot_close(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        result, err = mgr.close_channel("ch-1", "eve")
        assert result is None
        assert "participants" in err


class TestDispute:

    def test_dispute_with_newer_state(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        mgr.pay("ch-1", 10.0, "alice")  # nonce=1

        # Bob disputes with a state showing nonce=5
        update = PaymentUpdate(
            channel_id="ch-1", nonce=5,
            sender_balance=50.0, receiver_balance=50.0,
        )
        ok, err = mgr.dispute("ch-1", "bob", update)
        assert ok
        ch = mgr.get_channel("ch-1")
        assert ch.state == ChannelState.DISPUTED
        assert ch.nonce == 5

    def test_dispute_with_older_state(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        mgr.pay("ch-1", 10.0, "alice")
        mgr.pay("ch-1", 10.0, "alice")  # nonce=2

        update = PaymentUpdate(
            channel_id="ch-1", nonce=1,
            sender_balance=90.0, receiver_balance=10.0,
        )
        ok, err = mgr.dispute("ch-1", "bob", update)
        assert not ok
        assert "not newer" in err

    def test_dispute_wrong_totals(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)

        update = PaymentUpdate(
            channel_id="ch-1", nonce=5,
            sender_balance=80.0, receiver_balance=80.0,  # 160 != 100
        )
        ok, err = mgr.dispute("ch-1", "bob", update)
        assert not ok
        assert "totals" in err.lower()

    def test_resolve_dispute(self):
        mgr = PaymentChannelManager(ChannelConfig(dispute_period=0.01))
        mgr.open_channel("ch-1", "alice", "bob", 100.0)

        update = PaymentUpdate(
            channel_id="ch-1", nonce=5,
            sender_balance=40.0, receiver_balance=60.0,
        )
        mgr.dispute("ch-1", "bob", update)
        time.sleep(0.02)

        settled = mgr.resolve_disputes()
        assert len(settled) == 1
        assert settled[0]["receiver_payout"] > 0
        assert mgr.get_channel("ch-1").state == ChannelState.CLOSED


class TestQueries:

    def test_get_peer_channels(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        mgr.open_channel("ch-2", "alice", "carol", 50.0)
        channels = mgr.get_peer_channels("alice")
        assert len(channels) == 2

    def test_get_channel_between(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        ch = mgr.get_channel_between("alice", "bob")
        assert ch is not None
        assert ch.channel_id == "ch-1"

    def test_active_channels_count(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        mgr.open_channel("ch-2", "carol", "dave", 50.0)
        assert mgr.active_channels == 2
        mgr.close_channel("ch-1", "alice")
        assert mgr.active_channels == 1

    def test_stats(self):
        mgr = PaymentChannelManager()
        mgr.open_channel("ch-1", "alice", "bob", 100.0)
        mgr.pay("ch-1", 30.0, "alice")
        mgr.close_channel("ch-1", "alice")
        stats = mgr.get_stats()
        assert stats["total_channels"] == 1
        assert stats["active_channels"] == 0
        assert stats["total_settled"] == 30.0
        assert stats["total_fees"] > 0


class TestPaymentUpdate:

    def test_state_hash_deterministic(self):
        u1 = PaymentUpdate("ch-1", 1, 90.0, 10.0)
        u2 = PaymentUpdate("ch-1", 1, 90.0, 10.0)
        assert u1.state_hash == u2.state_hash

    def test_state_hash_changes_with_nonce(self):
        u1 = PaymentUpdate("ch-1", 1, 90.0, 10.0)
        u2 = PaymentUpdate("ch-1", 2, 90.0, 10.0)
        assert u1.state_hash != u2.state_hash
