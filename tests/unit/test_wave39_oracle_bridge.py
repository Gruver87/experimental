"""Wave 39 — oracle feed registry, signed submit, bridge L1 queue."""
import json
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)


def test_oracle_feed_persist_and_list():
    from features.oracle_registry import OracleFeedRegistry
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "o.db"))
    db.initialize()
    reg = OracleFeedRegistry(db, secret="test-secret")

    feed_id = reg.ingest_internal("bitcoin", 65000.5, "coingecko")
    assert feed_id

    rows = reg.list_feeds(symbol="bitcoin", limit=5)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "bitcoin"
    assert rows[0]["value"] == 65000.5


def test_oracle_submit_requires_valid_hmac():
    from features.oracle_registry import OracleFeedRegistry
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "s.db"))
    db.initialize()
    reg = OracleFeedRegistry(db, secret="wave39-secret")

    out = reg.submit_feed("ethereum", 3200.0, signature="bad")
    assert out["ok"] is False
    assert "invalid" in out.get("error", "").lower()


def test_oracle_submit_signed_payload():
    from features.oracle_registry import OracleFeedRegistry
    from bridge.oracle_auth import sign_payload
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "sig.db"))
    db.initialize()
    secret = "wave39-hmac"
    reg = OracleFeedRegistry(db, secret=secret)

    payload = {
        "symbol": "solana",
        "value": 145.25,
        "source": "reporter",
        "reporter": "0x" + "a" * 40,
        "ts": 1718123456,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = sign_payload(secret, raw)

    out = reg.submit_feed(
        symbol="solana",
        value=145.25,
        source="reporter",
        reporter=payload["reporter"],
        signature=sig,
        payload=payload,
    )
    assert out["ok"] is True
    latest = reg.latest_by_symbol("solana")
    assert latest is not None
    assert latest["value"] == 145.25


def test_bridge_lock_enqueues_l1_outbound():
    from bridge.abs_bridge import RustBridge
    from bridge.l1_rpc import load_l1_queue
    from runtime.config import Config
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "b.db"))
    db.initialize()
    queue_path = os.path.join(tmp, "l1_queue.json")
    cfg = Config(
        db_path=db.db_path,
        bridge_mode="simulator",
        bridge_l1_queue_path=queue_path,
    )
    sender = "0x" + "e" * 40
    db.set_balance(sender, 100.0)

    br = RustBridge(cfg, db)
    br._mode = "simulator"
    l1_hash = "0x" + "f" * 64
    result = br.lock_and_bridge(sender, "ethereum", "0x" + "1" * 40, 10.0, l1_tx_hash=l1_hash)

    assert result.get("l1_queued") is True
    assert result.get("tx_hash")

    queue = load_l1_queue(queue_path)
    assert len(queue.get("outbound", [])) == 1
    assert queue["outbound"][0]["l1_tx_hash"] == l1_hash
    assert queue["outbound"][0]["abs_tx_hash"] == result["tx_hash"]


def test_oracles_feeds_http_route():
    """REST GET /oracles/feeds is registered (Wave 39)."""
    import inspect
    src = inspect.getsource(__import__("api.http", fromlist=["RESTHandler"]).RESTHandler.do_GET)
    assert "/oracles/feeds" in src
    assert "/oracles/l1-queue" in src


def test_sync_from_manager_ingests_prices():
    from features.oracle_registry import OracleFeedRegistry
    from storage.database import Database

    class _Price:
        def __init__(self, price, source="test-feed", change_24h=0, volume=0):
            self.price = price
            self.source = source
            self.change_24h = change_24h
            self.volume = volume

    class _FakeOracle:
        def get_crypto_price(self, sym):
            return _Price(100.0 if sym == "bitcoin" else 50.0)

        def get_abs_reference_price(self):
            return _Price(1.5, source="internal")

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "m.db"))
    db.initialize()
    reg = OracleFeedRegistry(db, secret="")
    n = reg.sync_from_manager(_FakeOracle())
    assert n >= 3
    assert reg.latest_by_symbol("bitcoin") is not None


def test_oracle_feed_refuses_bool_and_nan():
    from features.oracle_registry import OracleFeedRegistry
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "bool.db"))
    db.initialize()
    reg = OracleFeedRegistry(db, secret="")
    out = reg.submit_feed("btc", True, require_signature=False)
    assert out.get("ok") is False
    assert "bool" in str(out.get("error") or "").lower()
    out2 = reg.submit_report("btc", float("nan"), "rep1")
    assert out2.get("ok") is False
