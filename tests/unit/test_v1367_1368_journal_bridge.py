#!/usr/bin/env python3
"""v1.3.67–68: EVM journal/arena + bridge fail-closed debit/events."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_writeback_journal_api():
    from execution.evm_adapter import EVMAdapter
    from runtime.config import Config

    class _DB:
        pass

    ad = EVMAdapter(_DB(), Config())
    ad.begin_writeback_journal()
    ad._apply_nested_writeback_ops([{"op": "append_logs", "address": "0x1", "logs": []}])
    assert len(ad._writeback_journal) == 1
    ad.discard_writeback_journal()
    assert ad._writeback_journaling is False
    assert ad._writeback_journal == []


def test_try_debit_satoshi_fail_closed():
    from runtime.amount import try_debit_satoshi

    assert try_debit_satoshi(2_000_000, 1.0) == 1_000_000
    with pytest.raises(ValueError):
        try_debit_satoshi(500_000, 1.0)


def test_needles_wave3_wave4():
    adapter = (ROOT / "execution" / "evm_adapter.py").read_text(encoding="utf-8")
    assert "begin_writeback_journal" in adapter
    assert "commit_writeback_journal" in adapter
    rust = (ROOT / "native" / "abs_native" / "src" / "evm_pure_runner.rs").read_text(
        encoding="utf-8"
    )
    assert "Rust-owned storage arena" in rust
    assert "fn storage_load(arena:" in rust
    bridge_rs = (ROOT / "bridge" / "rust_bridge" / "src" / "main.rs").read_text(
        encoding="utf-8"
    )
    assert "receipt_has_semantic_lock_log" in bridge_rs
    assert "BRIDGE_L1_LOCK_TOPIC0" in bridge_rs
    amount = (ROOT / "runtime" / "amount.py").read_text(encoding="utf-8")
    assert "def try_debit_satoshi" in amount
    rocks = (ROOT / "storage" / "rocks_store.py").read_text(encoding="utf-8")
    assert "try_debit_satoshi" in rocks


def test_sqlite_bridge_lock_amount_is_satoshi_quantized_bool_refused(tmp_path):
    from storage.database import Database

    db = Database(str(tmp_path / "bridge-money.db"))
    db.initialize()
    alice = "0x" + "a" * 40
    db.set_balance(alice, 10)
    db.debit_and_create_bridge_lock(
        from_addr=alice,
        amount=1.0000003,
        burn_address="",
        burn_amount=0,
        to_chain="ethereum",
        to_addr="0x" + "b" * 40,
        net_amount=1.0000003,
        tx_hash="0x" + "11" * 32,
    )
    assert db.get_balance(alice) == 9.0
    lock = db.get_bridge_locks()[0]
    assert lock["amount"] == 1.0
    refund = db.refund_pending_bridge_lock(lock["tx_hash"])
    assert refund["refunded"] is True
    assert refund["amount"] == 1.0
    assert db.get_balance(alice) == 10.0
    with pytest.raises(TypeError, match="bool is not an amount"):
        db.debit_and_create_bridge_lock(
            from_addr=alice,
            amount=True,
            burn_address="",
            burn_amount=0,
            to_chain="ethereum",
            to_addr="0x" + "b" * 40,
            net_amount=1.0,
            tx_hash="0x" + "22" * 32,
        )
    with pytest.raises(TypeError, match="bool is not an amount"):
        db.save_bridge_lock(alice, "ethereum", "0x" + "b" * 40, True, "0x" + "33" * 32)
