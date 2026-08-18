"""Wave 41 — Crypto Will SQLite persistence + L1 lock/transfer."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)


def test_will_create_locks_l1_and_persists():
    from features.crypto_will import CryptoWillManager
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "w.db"))
    db.initialize()
    owner = "0x" + "a" * 40
    heir = "0x" + "b" * 40
    db.set_balance(owner, 100.0)
    db.set_balance(heir, 0.0)

    cw1 = CryptoWillManager(db=db)
    wid = cw1.create_will(owner, heir, 25.0, {"note": "test"}, execution_delay=86400)
    assert wid
    assert db.get_balance(owner) == 75.0

    cw2 = CryptoWillManager(db=db)
    assert wid in cw2.wills
    assert cw2.get_stats()["persisted"] is True
    assert cw2.get_stats()["total_locked_amount"] == 25.0


def test_will_execute_transfers_to_heir():
    from features.crypto_will import CryptoWillManager
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "we.db"))
    db.initialize()
    owner = "0x" + "c" * 40
    heir = "0x" + "d" * 40
    db.set_balance(owner, 50.0)
    db.set_balance(heir, 0.0)

    cw = CryptoWillManager(db=db)
    wid = cw.create_will(owner, heir, 20.0, {}, execution_delay=86400)
    assert db.get_balance(owner) == 30.0
    assert cw.execute_will(wid, force=True)
    assert db.get_balance(heir) == 20.0
    assert wid not in cw.wills


def test_will_cancel_refunds_owner():
    from features.crypto_will import CryptoWillManager
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "wc.db"))
    db.initialize()
    owner = "0x" + "e" * 40
    heir = "0x" + "f" * 40
    db.set_balance(owner, 80.0)

    cw = CryptoWillManager(db=db)
    wid = cw.create_will(owner, heir, 15.0, {}, execution_delay=86400)
    assert db.get_balance(owner) == 65.0
    assert cw.cancel_will(wid, owner)
    assert db.get_balance(owner) == 80.0
    assert wid not in cw.wills


def test_will_insufficient_balance_rejected():
    from features.crypto_will import CryptoWillManager
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "wi.db"))
    db.initialize()
    owner = "0x" + "1" * 40
    db.set_balance(owner, 1.0)

    cw = CryptoWillManager(db=db)
    assert cw.create_will(owner, "0x" + "2" * 40, 10.0, {}, execution_delay=86400) is None


def test_will_cancel_requires_credit_backend():
    from features.crypto_will import CryptoWill, CryptoWillManager

    owner = "0x" + "3" * 40
    heir = "0x" + "4" * 40
    cw = CryptoWillManager(db=None)
    cw.wills["will1"] = CryptoWill("will1", owner, heir, 10.0, {}, 0)

    assert cw.cancel_will("will1", owner) is False
    assert cw.wills["will1"].status == "pending"


def test_will_execute_requires_credit_backend():
    from features.crypto_will import CryptoWill, CryptoWillManager

    owner = "0x" + "5" * 40
    heir = "0x" + "6" * 40
    cw = CryptoWillManager(db=None)
    cw.wills["will2"] = CryptoWill("will2", owner, heir, 10.0, {}, 0)

    assert cw.execute_will("will2", force=True) is False
    assert cw.wills["will2"].status == "pending"


def test_sqlite_will_amount_quantizes_and_refuses_bool():
    import pytest
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "will-money.db"))
    db.initialize()
    db.save_crypto_will(
        {
            "will_id": "w1",
            "owner": "0xa",
            "heir": "0xb",
            "amount": 25.0000003,
            "assets": {},
            "execution_time": 1,
            "created_at": 1,
            "status": "pending",
            "witnesses": [],
        }
    )
    assert db.get_crypto_wills()[0]["amount"] == 25.0
    with pytest.raises(TypeError, match="bool is not an amount"):
        db.save_crypto_will(
            {
                "will_id": "w2",
                "owner": "0xa",
                "heir": "0xb",
                "amount": True,
                "created_at": 1,
            }
        )
