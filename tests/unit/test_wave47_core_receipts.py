"""Wave 47 — core L1 tx receipts and chain metrics."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)


def test_tx_receipt_persisted_on_block():
    from core.blockchain import Blockchain, Transaction
    from runtime.config import Config
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "c.db"))
    db.initialize()
    cfg = Config()
    cfg.miner_address = "0x" + "1" * 40
    cfg.burn_address = "0x" + "d" * 40
    db.update_balance(cfg.miner_address, 10_000.0)

    bc = Blockchain(cfg, db)
    tx = Transaction(
        from_addr=cfg.miner_address,
        to_addr="0x" + "2" * 40,
        value=1.0,
        nonce=0,
    )
    block = bc.create_block([tx], cfg.miner_address)
    assert bc.add_block(block) is True

    rcpt = db.get_tx_receipt(tx.hash)
    assert rcpt is not None
    assert rcpt["block_height"] == block.height
    assert rcpt["value"] == 1.0
    assert rcpt["status"] == 1


def test_receipts_by_block():
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "r.db"))
    db.initialize()
    db._persist_block_locked(
        {"height": 1, "hash": "0xabc", "parent_hash": "0", "timestamp": 100, "miner": "0xm",
         "tx_count": 1, "gas_used": 0, "total_burned": 0, "extra_data": ""},
        [{
            "hash": "0xtx1", "block_height": 1, "from_addr": "0xa", "to_addr": "0xb",
            "value": 5.0, "fee": 0.1, "burned": 0.02, "gas_used": 21000, "status": 1,
            "timestamp": 100,
        }],
    )
    db.conn.commit()
    rows = db.get_receipts_by_block(1)
    assert len(rows) == 1
    assert rows[0]["tx_hash"] == "0xtx1"


def test_sqlite_tx_money_display_follows_satoshi_not_ieee():
    import pytest
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "txm.db"))
    db.initialize()
    db._persist_block_locked(
        {"height": 1, "hash": "0xabc", "parent_hash": "0", "timestamp": 100, "miner": "0xm",
         "tx_count": 1, "gas_used": 0, "total_burned": 0, "extra_data": ""},
        [{
            "hash": "0xtx1", "block_height": 1, "from_addr": "0xa", "to_addr": "0xb",
            "value": 1.0, "fee": 0.1, "burned": 0.02, "gas_used": 21000, "status": 1,
            "timestamp": 100,
        }],
    )
    db.conn.commit()
    db.conn.execute("UPDATE transactions SET value=? WHERE hash=?", (1.0000003, "0xtx1"))
    db.conn.execute("UPDATE tx_receipts SET value=? WHERE tx_hash=?", (1.0000003, "0xtx1"))
    db.conn.commit()

    listed = db.get_transactions_by_address("0xa", direction="sent")
    assert listed[0]["value"] == 1.0
    rcpt = db.get_tx_receipt("0xtx1")
    assert rcpt is not None
    assert rcpt["value"] == 1.0
    assert rcpt["fee"] == 0.1
    with pytest.raises(TypeError):
        db._serialize_tx_row({"hash": "0xbad", "value": True, "fee": 0, "burned": 0})


def test_chain_metrics():
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "m.db"))
    db.initialize()
    for h in range(1, 4):
        db.save_block({
            "height": h,
            "hash": f"hash{h}",
            "parent_hash": f"hash{h-1}" if h > 1 else "0",
            "timestamp": 1000 + h * 15,
            "miner": "0xm",
            "tx_count": 0,
            "total_burned": 0.01 * h,
        })
    m = db.get_chain_metrics(window=10)
    assert m["height"] >= 3
    assert m["receipts_enabled"] is True
    assert m["avg_block_time_sec"] == 15.0
