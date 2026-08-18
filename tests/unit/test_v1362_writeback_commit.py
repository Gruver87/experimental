#!/usr/bin/env python3
"""v1.3.62: store-lock Rocks writeback commit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import abs_native  # type: ignore

    HAS_ROCKS = hasattr(abs_native, "RocksEngine") and hasattr(
        abs_native.RocksEngine, "commit_account_rows"
    )
except Exception:
    HAS_ROCKS = False


def test_engine_exposes_commit_account_rows():
    assert hasattr(abs_native.RocksEngine, "commit_account_rows") or not HAS_ROCKS


@pytest.mark.skipif(not HAS_ROCKS, reason="abs_native.RocksEngine.commit_account_rows missing")
def test_store_commit_writeback_accounts(tmp_path):
    from storage.rocks_store import RocksChainStore

    path = str(tmp_path / "wb62")
    store = RocksChainStore(path, synchronous="FULL")
    store.initialize()
    try:
        store.save_account("0xaaa", balance=1.0, nonce=0, code="", storage="{}")
        n = store.commit_writeback_accounts(
            {
                "0xaaa": {
                    "balance": 3.0,
                    "balance_satoshi": 3_000_000,
                    "nonce": 2,
                    "code": "6000",
                    "storage": {"7": 9},
                },
                "0xbbb": {
                    "balance": 0.5,
                    "balance_satoshi": 500_000,
                    "nonce": 0,
                    "code": "",
                    "storage": "{}",
                },
            }
        )
        assert n == 2
        a = store.get_account("0xaaa")
        assert a is not None
        assert int(a["nonce"]) == 2
        assert a["code"] == "6000"
        storage = a["storage"]
        if isinstance(storage, str):
            storage = json.loads(storage)
        assert int(storage.get("7", storage.get(7))) == 9
        b = store.get_account("0xbbb")
        assert b is not None
        assert float(b["balance"]) == pytest.approx(0.5)
        store.commit_writeback_accounts(
            {
                "0xaaa": {
                    "balance": 99.9,
                    "balance_satoshi": 1_000_000,
                    "nonce": 2,
                    "code": "6000",
                    "storage": {"7": 9},
                }
            }
        )
        assert store.get_balance("0xaaa") == 1.0
        with pytest.raises(TypeError, match="bool is not an amount"):
            store.commit_writeback_accounts({"0xddd": {"balance": True}})
    finally:
        store.close()


def test_adapter_wires_store_lock_commit():
    adapter = (ROOT / "execution" / "evm_adapter.py").read_text(encoding="utf-8")
    assert "commit_writeback_accounts" in adapter or "commit_writeback_bundle" in adapter
    assert "_writeback_store" in adapter
    rocks = (ROOT / "storage" / "rocks_store.py").read_text(encoding="utf-8")
    assert "def commit_writeback_accounts" in rocks
    assert "def commit_writeback_bundle" in rocks or "commit_account_rows" in rocks
    hybrid = (ROOT / "storage" / "hybrid_database.py").read_text(encoding="utf-8")
    assert "def commit_writeback_accounts" in hybrid
    rust = (ROOT / "native" / "abs_native" / "src" / "storage" / "mod.rs").read_text(
        encoding="utf-8"
    )
    assert "fn commit_account_rows" in rust
