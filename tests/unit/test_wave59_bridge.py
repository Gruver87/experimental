"""Wave 59 — bridge L1 queue, bridge2 rust path."""
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)


def test_l1_queue_payload_shape():
    from api.http import _build_l1_queue_payload
    from runtime.config import Config
    from bridge.abs_bridge import RustBridge
    from bridge.l1_rpc import load_l1_queue
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    queue_path = os.path.join(tmp, "q.json")
    cfg = Config()
    cfg.db_path = os.path.join(tmp, "b.db")
    cfg.bridge_l1_queue_path = queue_path
    db = Database(cfg.db_path)
    db.initialize()
    br = RustBridge(cfg, db, None)
    br.enqueue_l1_incoming("0x" + "11" * 32, "0xrecv", 4.0, "ethereum")

    out = _build_l1_queue_payload(cfg)
    assert out.get("incoming") or out.get("queue", {}).get("incoming")
    q = load_l1_queue(queue_path)
    assert len(q.get("incoming", [])) == 1
    db.close()


def test_bridge_lock_queues_outbound(monkeypatch):
    from bridge.abs_bridge import RustBridge
    from bridge.l1_rpc import load_l1_queue
    from runtime.config import Config
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    queue_path = os.path.join(tmp, "q.json")
    cfg = Config()
    cfg.db_path = os.path.join(tmp, "b.db")
    cfg.bridge_l1_queue_path = queue_path
    cfg.rust_bridge_path = __file__
    db = Database(cfg.db_path)
    db.initialize()
    sender = "0x" + "aa" * 20
    db.set_balance(sender, 50.0)
    br = RustBridge(cfg, db, None)
    # Unit scope: L1 lock verify is covered elsewhere; here we assert queue write.
    monkeypatch.setattr(br, "_call_rust_ok", lambda *_a, **_k: True)
    res = br.lock_and_bridge(
        sender, "ethereum", "0x" + "bb" * 20, 10.0, l1_tx_hash="0x" + "cc" * 32
    )
    assert res.get("l1_queued") is True
    q = load_l1_queue(queue_path)
    assert len(q.get("outbound", [])) == 1
    db.close()
