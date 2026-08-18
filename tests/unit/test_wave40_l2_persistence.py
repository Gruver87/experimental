"""Wave 40 — Lightning/Plasma SQLite persistence + L1 balance effects."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)


def test_lightning_open_debits_l1_and_persists():
    from features.lightning import LightningNetwork
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "ln.db"))
    db.initialize()
    node = "0x" + "a" * 40
    peer = "0x" + "b" * 40
    db.set_balance(node, 100.0)

    ln1 = LightningNetwork(node_address=node, db=db)
    cid = ln1.open_channel(peer, 10.0)
    assert cid
    assert db.get_balance(node) == 90.0

    ln2 = LightningNetwork(node_address=node, db=db)
    assert cid in ln2.channels
    assert ln2.get_stats()["persisted"] is True


def test_lightning_close_credits_l1():
    from features.lightning import LightningNetwork
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "lc.db"))
    db.initialize()
    node = "0x" + "c" * 40
    peer = "0x" + "d" * 40
    db.set_balance(node, 50.0)

    ln = LightningNetwork(node_address=node, db=db)
    cid = ln.open_channel(peer, 20.0)
    assert db.get_balance(node) == 30.0
    assert ln.close_channel(cid)
    assert db.get_balance(node) == 50.0
    assert db.get_balance(peer) == 0.0


def test_lightning_open_requires_balance_backend():
    from features.lightning import LightningNetwork

    node = "0x" + "a" * 40
    peer = "0x" + "b" * 40
    ln = LightningNetwork(node_address=node, db=None)

    assert ln.open_channel(peer, 10.0, node_balance=100.0) is None


def test_lightning_close_requires_refund_backend():
    from features.lightning import LightningChannel, LightningNetwork

    node = "0x" + "c" * 40
    peer = "0x" + "d" * 40
    ln = LightningNetwork(node_address=node, db=None)
    ln.channels["chan1"] = LightningChannel("chan1", node, peer, 10.0)

    assert ln.close_channel("chan1") is False
    assert ln.channels["chan1"].status == "open"


def test_lightning_payment_rejects_non_positive_amount():
    from features.lightning import LightningNetwork
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "ln-pay.db"))
    db.initialize()
    node = "0x" + "9" * 40
    peer = "0x" + "8" * 40
    db.set_balance(node, 100.0)

    ln = LightningNetwork(node_address=node, db=db)
    cid = ln.open_channel(peer, 10.0)

    assert ln.send_payment(cid, peer, 0) is None
    assert ln.send_payment(cid, peer, -1.0) is None


def test_lightning_payment_requires_channel_counterparty_and_fee_balance():
    from features.lightning import LightningNetwork
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "ln-real-pay.db"))
    db.initialize()
    node = "0x" + "1" * 40
    peer = "0x" + "2" * 40
    stranger = "0x" + "3" * 40
    db.set_balance(node, 100.0)

    ln = LightningNetwork(node_address=node, db=db)
    cid = ln.open_channel(peer, 10.0)
    assert cid
    ch = ln.channels[cid]
    assert ch.balance1 == 10.0
    assert ch.balance2 == 0.0

    assert ln.send_payment(cid, stranger, 1.0) is None
    before_sender = ch.balance1
    before_receiver = ch.balance2
    payment_id = ln.send_payment(cid, peer, 1.0)

    assert payment_id
    assert ch.balance1 == before_sender - 1.0 - (1.0 * ch.fee_rate)
    assert ch.balance2 == before_receiver + 1.0
    assert ln.send_payment(cid, peer, ch.balance1) is None


def test_plasma_deposit_debits_and_persists():
    from features.plasma import PlasmaChain
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "pl.db"))
    db.initialize()
    user = "0x" + "e" * 40
    db.set_balance(user, 200.0)

    pl1 = PlasmaChain(chain_id="test", db=db)
    did = pl1.deposit(user, 25.0)
    assert did
    assert db.get_balance(user) == 175.0

    pl2 = PlasmaChain(chain_id="test", db=db)
    assert did in pl2.deposits
    assert pl2.get_stats()["persisted"] is True
    assert pl2.get_stats()["total_deposited"] == 25.0


def test_plasma_finalize_exit_credits_l1():
    from features.plasma import PlasmaChain
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "pe.db"))
    db.initialize()
    user = "0x" + "f" * 40
    db.set_balance(user, 100.0)

    pl = PlasmaChain(chain_id="test", db=db)
    did = pl.deposit(user, 40.0)
    assert db.get_balance(user) == 60.0
    eid = pl.request_exit(did, user)
    assert eid
    assert pl.finalize_exit(eid, force=True)
    assert db.get_balance(user) == 100.0


def test_plasma_finalize_exit_requires_credit_backend():
    from features.plasma import PlasmaChain

    user = "0x" + "7" * 40
    pl = PlasmaChain(chain_id="test", db=None)
    pl.deposits["dep1"] = {
        "id": "dep1",
        "from": user,
        "amount": 12.0,
        "status": "exiting",
    }
    pl.exit_requests["exit1"] = {
        "id": "exit1",
        "deposit_id": "dep1",
        "user": user,
        "amount": 12.0,
        "created_at": 0,
        "status": "pending",
    }

    assert pl.finalize_exit("exit1", force=True) is False
    assert pl.exit_requests["exit1"]["status"] == "pending"
    assert pl.deposits["dep1"]["status"] == "exiting"


def test_plasma_block_persisted():
    from features.plasma import PlasmaChain
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "pb.db"))
    db.initialize()
    user = "0x" + "1" * 40
    recipient = "0x" + "2" * 40
    db.set_balance(user, 100.0)

    pl = PlasmaChain(chain_id="test", db=db)
    assert pl.deposit(user, 10.0)
    assert pl.submit_transaction(user, recipient, 5.0)
    blk = pl.submit_block()
    assert blk is not None

    pl2 = PlasmaChain(chain_id="test", db=db)
    assert len(pl2.blocks) >= 2  # genesis + submitted


def test_plasma_transfer_requires_l2_balance():
    from features.plasma import PlasmaChain
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "pbalance.db"))
    db.initialize()
    user = "0x" + "3" * 40
    recipient = "0x" + "4" * 40
    db.set_balance(user, 100.0)

    pl = PlasmaChain(chain_id="test", db=db)
    assert pl.submit_transaction(user, recipient, 1.0) is None
    assert pl.deposit(user, 10.0)
    assert pl.submit_transaction(user, recipient, 11.0) is None
    assert pl.submit_transaction(user, recipient, 4.0)
    assert pl.submit_transaction(user, recipient, 7.0) is None


def test_plasma_exit_requires_unspent_l2_balance():
    from features.plasma import PlasmaChain
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "pexit-balance.db"))
    db.initialize()
    user = "0x" + "5" * 40
    recipient = "0x" + "6" * 40
    db.set_balance(user, 100.0)

    pl = PlasmaChain(chain_id="test", db=db)
    did = pl.deposit(user, 10.0)
    assert did
    assert pl.submit_transaction(user, recipient, 6.0)

    assert pl.request_exit(did, user) is None


def test_sqlite_feature_money_quantizes_and_refuses_bool():
    import pytest
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "feat-money.db"))
    db.initialize()
    db.save_lightning_channel(
        {
            "channel_id": "c1",
            "node1": "0xa",
            "node2": "0xb",
            "capacity": 7.5000003,
            "balance1": 7.5000003,
            "balance2": 0,
            "status": "open",
            "fee_rate": 0.00001,
            "created_at": 1,
        }
    )
    ch = db.get_lightning_channels()[0]
    assert ch["capacity"] == 7.5
    assert ch["balance1"] == 7.5
    db.save_plasma_deposit(
        {
            "id": "d1",
            "from": "0xa",
            "amount": 1.0000003,
            "main_tx_hash": "0x1",
            "created_at": 1,
            "status": "confirmed",
        }
    )
    assert db.get_plasma_deposits()[0]["amount"] == 1.0
    with pytest.raises(TypeError, match="bool is not an amount"):
        db.save_lightning_channel(
            {
                "channel_id": "c2",
                "node1": "0xa",
                "node2": "0xb",
                "capacity": True,
                "balance1": 0,
                "balance2": 0,
                "created_at": 1,
            }
        )
