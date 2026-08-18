#!/usr/bin/env python3
"""Close satoshi dual-write bypasses (reset_accounts, nonce_increment, adapter)."""

import os
import tempfile

from blockchain.state_adapter import DatabaseStateAdapter
from runtime.amount import to_satoshi
from storage.database import Database
from storage.persistent_storage import PersistentStorage


def test_sqlite_reset_accounts_writes_satoshi():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "reset.db")
    db = Database(path)
    db.initialize()
    db.reset_accounts_from_alloc({"alice": 7.5, "bob": 0})
    assert db.get_balance_satoshi("alice") == to_satoshi(7.5)
    row = db.get_account("alice")
    assert row is not None
    assert int(row["balance_satoshi"]) == to_satoshi(7.5)


def test_sqlite_account_display_follows_satoshi_not_stale_float():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "stale.db")
    db = Database(path)
    db.initialize()
    db.set_balance("alice", 1.0)
    db.conn.execute(
        "UPDATE accounts SET balance=? WHERE address=?",
        (1.0000003, "alice"),
    )
    db.conn.commit()
    assert db.get_balance_satoshi("alice") == to_satoshi(1.0)
    assert db.get_balance("alice") == 1.0
    row = db.get_account("alice")
    assert row is not None
    assert row["balance"] == 1.0
    assert int(row["balance_satoshi"]) == to_satoshi(1.0)


def test_sqlite_legacy_float_only_row_quantizes_via_satoshi():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "legacy.db")
    db = Database(path)
    db.initialize()
    db.set_balance("bob", 7.5)
    db.conn.execute(
        "UPDATE accounts SET balance_satoshi=NULL, balance=? WHERE address=?",
        (7.5, "bob"),
    )
    db.conn.commit()
    assert db.get_balance_satoshi("bob") == to_satoshi(7.5)
    assert db.get_balance("bob") == 7.5


def test_sqlite_set_balance_fractional_and_refuses_bool():
    import pytest

    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "set.db")
    db = Database(path)
    db.initialize()
    db.set_balance("alice", 7.5)
    assert db.get_balance("alice") == 7.5
    assert db.get_balance_satoshi("alice") == to_satoshi(7.5)
    with pytest.raises(TypeError, match="bool is not an amount"):
        db.set_balance("alice", True)


def test_sqlite_nonce_increment_sets_balance_satoshi_zero():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "nonce.db")
    db = Database(path)
    db.initialize()
    with db.atomic():
        n = db.nonce_increment("0x" + "ef" * 20)
    assert n == 1
    row = db.get_account("0x" + "ef" * 20)
    assert row is not None
    assert int(row["balance_satoshi"] or 0) == 0
    assert float(row["balance"] or 0) == 0.0


def test_state_adapter_prefers_satoshi():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "adapter.db")
    db = Database(path)
    db.initialize()
    db.set_balance("0x" + "aa" * 20, 3.25)
    adapter = DatabaseStateAdapter(db)
    assert adapter.get_balance_satoshi("0x" + "aa" * 20) == to_satoshi(3.25)
    acc = adapter.get_account("0x" + "aa" * 20)
    assert abs(acc.balance - 3.25) < 1e-12


def test_persistent_storage_update_balance_dual_write():
    tmp = tempfile.mkdtemp()
    ps = PersistentStorage(tmp)
    addr = "0x" + "bb" * 20
    ps.db.set_balance(addr, 10.0)
    nonce_before = ps.db.get_nonce(addr)
    new_bal = ps.update_balance(addr, -1.5)
    assert abs(new_bal - 8.5) < 1e-12
    assert ps.db.get_balance_satoshi(addr) == to_satoshi(8.5)
    assert ps.db.get_nonce(addr) == nonce_before
