#!/usr/bin/env python3
"""v1.3.61: native in-memory writeback apply."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crypto import native


def test_apply_set_storage_and_transfer():
    accounts = {
        "0xfrom": {
            "address": "0xfrom",
            "balance_satoshi": 5_000_000,
            "balance": 5.0,
            "nonce": 0,
            "code": "",
            "storage": "{}",
        },
        "0xto": {
            "address": "0xto",
            "balance_satoshi": 0,
            "balance": 0.0,
            "nonce": 0,
            "code": "00",
            "storage": "{}",
        },
    }
    ops = [
        {"op": "set_storage", "address": "0xto", "storage": {"1": 2}},
        {"op": "transfer_value", "from": "0xfrom", "to": "0xto", "value_wei": 10**18},
    ]
    out = native.evm_apply_writeback_ops(accounts, ops)
    assert out["native_apply"] is True or out.get("applied", 0) >= 2
    assert int(out["accounts"]["0xto"]["balance_satoshi"]) == 1_000_000
    assert int(out["accounts"]["0xfrom"]["balance_satoshi"]) == 4_000_000
    storage = out["accounts"]["0xto"]["storage"]
    if isinstance(storage, str):
        import json
        storage = json.loads(storage)
    assert int(storage.get("1", storage.get(1))) == 2


def test_apply_save_account_and_logs():
    out = native.evm_apply_writeback_ops(
        {},
        [
            {
                "op": "save_account",
                "address": "0xchild",
                "balance": 0,
                "nonce": 0,
                "code": "6001",
                "storage": "{}",
            },
            {
                "op": "append_logs",
                "address": "0xchild",
                "logs": [{"topics": [], "data": "aa"}],
            },
        ],
    )
    assert "0xchild" in out["accounts"]
    assert out["accounts"]["0xchild"]["code"] == "6001"
    assert len(out["log_batches"]) == 1


def test_python_fallback_apply():
    py = native._evm_apply_writeback_ops_py(
        {"0xa": {"balance_satoshi": 2_000_000, "storage": "{}"}},
        [{"op": "transfer_value", "from": "0xa", "to": "0xb", "value_wei": 10**18}],
    )
    assert py["native_apply"] is False
    assert int(py["accounts"]["0xa"]["balance_satoshi"]) == 1_000_000
    assert int(py["accounts"]["0xb"]["balance_satoshi"]) == 1_000_000


def test_apply_transfer_insufficient_does_not_mint():
    accounts = {
        "0xfrom": {"address": "0xfrom", "balance_satoshi": 0, "balance": 0.0},
        "0xto": {"address": "0xto", "balance_satoshi": 0, "balance": 0.0},
    }
    ops = [{"op": "transfer_value", "from": "0xfrom", "to": "0xto", "value_wei": 10**18}]
    try:
        native.evm_apply_writeback_ops(accounts, ops)
        raise AssertionError("expected insufficient_writeback_value")
    except ValueError as exc:
        assert "insufficient_writeback_value" in str(exc)
    assert int(accounts["0xfrom"]["balance_satoshi"]) == 0
    assert int(accounts["0xto"]["balance_satoshi"]) == 0


def test_python_fallback_transfer_insufficient_does_not_mint():
    accounts = {"0xa": {"balance_satoshi": 0, "storage": "{}"}}
    ops = [{"op": "transfer_value", "from": "0xa", "to": "0xb", "value_wei": 10**18}]
    try:
        native._evm_apply_writeback_ops_py(accounts, ops)
        raise AssertionError("expected insufficient_writeback_value")
    except ValueError as exc:
        assert "insufficient_writeback_value" in str(exc)
    assert int(accounts["0xa"]["balance_satoshi"]) == 0


def test_adapter_writeback_insufficient_does_not_mint(tmp_path):
    from execution.evm_adapter import EVMAdapter
    from runtime.config import Config
    from storage.database import Database

    cfg = Config()
    cfg.db_path = str(tmp_path / "wb.db")
    db = Database(cfg.db_path, synchronous="NORMAL")
    db.initialize()
    try:
        sender = "0x" + "11" * 20
        dest = "0x" + "22" * 20
        db.save_account(sender, balance=0.0, nonce=0, code="6000", storage="{}")
        adapter = EVMAdapter(db, cfg)
        try:
            adapter._apply_nested_writeback_ops_now(
                [
                    {
                        "op": "transfer_value",
                        "from": sender,
                        "to": dest,
                        "value_wei": 10**18,
                    }
                ]
            )
            raise AssertionError("expected insufficient_writeback_value")
        except (ValueError, RuntimeError) as exc:
            assert "insufficient_writeback_value" in str(exc)
        assert db.get_balance_satoshi(sender) == 0
        assert db.get_balance_satoshi(dest) == 0
    finally:
        db.close()
    py = native._evm_apply_writeback_ops_py(
        {"0xa": {"balance_satoshi": 2_000_000, "storage": "{}"}},
        [{"op": "transfer_value", "from": "0xa", "to": "0xb", "value_wei": 10**18}],
    )
    assert py["native_apply"] is False
    assert int(py["accounts"]["0xa"]["balance_satoshi"]) == 1_000_000
    assert int(py["accounts"]["0xb"]["balance_satoshi"]) == 1_000_000


def test_adapter_wires_native_apply():
    adapter = (ROOT / "execution" / "evm_adapter.py").read_text(encoding="utf-8")
    assert "evm_apply_writeback_ops" in adapter
    rust = (ROOT / "native" / "abs_native" / "src" / "evm_writeback.rs").read_text(
        encoding="utf-8"
    )
    assert "evm_apply_writeback_ops" in rust
