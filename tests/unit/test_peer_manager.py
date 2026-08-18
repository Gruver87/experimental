# tests/unit/test_peer_manager.py
"""Isolated PeerManager: register, max_peers, strikes, auto-ban."""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace

import pytest

from network.peer_manager import PeerManager, PeerManagerSettings, peer_health_score


class FakePeer:
    def __init__(
        self,
        peer_id: str,
        host: str = "10.0.0.1",
        port: int = 5000,
        *,
        height: int = 0,
        last_seen: float | None = None,
    ):
        self.peer_id = peer_id
        self.host = host
        self.port = port
        self.listen_port = port
        self.height = height
        self.head = ""
        self.connected_at = time.time()
        self.last_seen = float(last_seen if last_seen is not None else time.time())
        self.quality_import_fails = 0
        self.closed = False
        self._inbound = False

    def close(self) -> None:
        self.closed = True


def _mgr(**kwargs) -> PeerManager:
    settings = PeerManagerSettings(
        max_peers=kwargs.pop("max_peers", 2),
        rate_limit_strikes=kwargs.pop("rate_limit_strikes", 3),
        ban_seconds=kwargs.pop("ban_seconds", 60),
        peer_timeout=kwargs.pop("peer_timeout", 30.0),
        evict_min_score=kwargs.pop("evict_min_score", 0),
        eclipse_warn_ratio=0.0,
        bootstrap_peers=kwargs.pop("bootstrap_peers", []),
    )
    return PeerManager(settings, **kwargs)


def test_register_and_count():
    pm = _mgr(max_peers=5)
    p = FakePeer("peer-a")
    assert pm.register(p).allowed is True
    assert pm.peer_count() == 1
    assert pm.get("peer-a") is p


def test_max_peers_blocks_inbound_admit():
    pm = _mgr(max_peers=1)
    assert pm.register(FakePeer("a")).allowed
    admit = pm.allow_inbound("10.0.0.2")
    assert admit.allowed is False
    assert admit.reason == "max_peers"
    assert pm.shape_reject_counts.get("max_peers", 0) >= 1


def test_outbound_blocked_at_capacity():
    pm = _mgr(max_peers=1)
    pm.register(FakePeer("a"))
    assert pm.allow_outbound().allowed is False


def test_duplicate_fresh_peer_refused():
    pm = _mgr(max_peers=5)
    a = FakePeer("dup")
    assert pm.register(a).allowed
    b = FakePeer("dup", host="10.0.0.9")
    b.last_seen = time.time()
    a.last_seen = time.time()  # still fresh
    decision = pm.register(b, replace_stale=True)
    assert decision.allowed is False
    assert decision.reason == "duplicate_peer"
    assert not b.closed  # caller closes on refuse; register does not close challenger


def test_strike_then_autoban():
    pm = _mgr(max_peers=5, rate_limit_strikes=3, ban_seconds=120)
    peer = FakePeer("bad")
    pm.register(peer)
    assert pm.strike(peer, "bad_wire") is False
    assert pm.strike_count(peer) == 1
    assert pm.strike(peer, "bad_wire") is False
    assert pm.strike_count(peer) == 2
    banned = pm.strike(peer, "bad_wire")
    assert banned is True
    assert pm.is_banned("bad") is True
    assert pm.strike_count(peer) == 0  # cleared on ban


def test_register_refused_when_banned():
    pm = _mgr(max_peers=5, rate_limit_strikes=1, ban_seconds=300)
    peer = FakePeer("x", host="192.168.1.9", port=9)
    assert pm.strike(peer, "flood") is True
    again = FakePeer("x", host="192.168.1.9", port=9)
    assert pm.register(again).allowed is False
    assert pm.register(again).reason == "banned"


def test_addr_ban_prefix_python_fallback():
    pm = _mgr(max_peers=5, rate_limit_strikes=1)
    # No peer_id → strike key is host:port (dial/addr ban surface).
    peer = FakePeer("", host="203.0.113.10", port=7777)
    assert pm.strike(peer, "abuse")
    assert pm.is_banned("203.0.113.10:7777")
    assert pm.is_addr_banned("203.0.113.10", 7777)
    assert pm.is_addr_banned("203.0.113.10", 1)


def test_score_penalizes_strikes_and_import_fails():
    base = peer_health_score(
        height_gap=0, last_seen_age=1.0, health_timeout=60.0, strikes=0, import_fails=0
    )
    hit = peer_health_score(
        height_gap=0, last_seen_age=1.0, health_timeout=60.0, strikes=2, import_fails=1
    )
    assert hit < base
    pm = _mgr(max_peers=5, rate_limit_strikes=10)
    peer = FakePeer("s", height=10)
    pm.register(peer)
    pm.strike(peer, "x")
    pm.note_import_fail(peer)
    score = pm.score(peer, local_height=10, health_timeout=60.0)
    assert 0 <= score < 100


def test_prune_stale_by_age():
    pm = _mgr(max_peers=5, peer_timeout=10.0)
    stale = FakePeer("old")
    stale.last_seen = time.time() - 1000
    fresh = FakePeer("new", host="10.0.0.2")
    pm.register(stale)
    pm.register(fresh)
    removed = pm.prune_stale(local_height=0, max_age=30.0)
    assert removed >= 1
    assert pm.get("old") is None
    assert pm.get("new") is not None
    assert stale.closed is True


def test_prune_evict_min_score():
    pm = _mgr(max_peers=5, evict_min_score=90, rate_limit_strikes=20)
    a = FakePeer("good", height=100)
    b = FakePeer("bad", host="10.0.0.3", height=0)
    pm.register(a)
    pm.register(b)
    # pile strikes on bad peer to tank score
    for _ in range(5):
        pm.strike(b, "junk")
    removed = pm.prune_stale(local_height=100)
    assert removed >= 1
    assert pm.get("bad") is None
    assert pm.get("good") is not None


def test_remember_bootstrap_addrs():
    pm = _mgr(max_peers=5, bootstrap_peers=["127.0.0.1:5000", "bad", "10.1.1.1:9"])
    assert "127.0.0.1:5000" in pm.known_addrs
    assert "10.1.1.1:9" in pm.known_addrs
    pm.remember_addr("10.2.2.2:11")
    assert "10.2.2.2:11" in pm.known_addrs


def test_unregister_closes_and_removes():
    pm = _mgr(max_peers=5)
    p = FakePeer("z")
    pm.register(p, inbound=True)
    out = pm.unregister("z", p)
    assert out is p
    assert p.closed is True
    assert pm.peer_count() == 0


def test_active_bans_snapshot():
    pm = _mgr(max_peers=5, rate_limit_strikes=1, ban_seconds=90)
    peer = FakePeer("banme")
    pm.strike(peer, "x")
    snap = pm.active_bans_snapshot()
    assert snap["strikes_before_ban"] == 1
    assert snap["active_bans"]
    assert snap["peer_count"] == 0


def test_has_active_endpoint():
    pm = _mgr(max_peers=5)
    pm.register(FakePeer("e", host="1.2.3.4", port=55))
    assert pm.has_active_endpoint("1.2.3.4", 55)
    assert not pm.has_active_endpoint("1.2.3.4", 99)


def test_clear_logs_close_failure(caplog):
    class Boom(FakePeer):
        def close(self):
            raise RuntimeError("close boom")

    pm = _mgr(max_peers=5)
    pm.register(Boom("x"))
    with caplog.at_level(logging.DEBUG, logger="PeerManager"):
        pm.clear(close=True)
    assert "close failed" in caplog.text
    assert "close boom" in caplog.text
    assert pm.peer_count() == 0


def test_shape_reject_hook_failure_is_logged(caplog):
    def boom(_reason: str) -> None:
        raise RuntimeError("hook boom")

    pm = PeerManager(PeerManagerSettings(max_peers=1), on_shape_reject=boom)
    with caplog.at_level(logging.WARNING, logger="PeerManager"):
        pm.note_shape_reject("max_peers")
    assert "shape reject hook failed" in caplog.text
    assert pm.shape_reject_counts.get("max_peers", 0) == 1


def test_p2p_node_wires_peer_manager(tmp_path, monkeypatch):
    from runtime.config import Config
    from storage.database import Database
    from core.blockchain import Blockchain
    from blockchain.mempool import Mempool
    from network.p2p_node import P2PNode

    cfg = Config()
    cfg.db_path = str(tmp_path / "pm.db")
    cfg.max_peers = 3
    cfg.p2p_rate_limit_strikes = 2
    cfg.p2p_ban_seconds = 30
    cfg.bootstrap_peers = ["127.0.0.1:5999"]
    db = Database(cfg.db_path)
    db.initialize()
    bc = Blockchain(cfg, db)
    mp = Mempool()
    node = P2PNode(cfg, bc, mp)
    assert isinstance(node.peer_manager, PeerManager)
    assert node.peers is node.peer_manager.peers
    assert "127.0.0.1:5999" in node._known_addrs
    # thin strike delegate
    peer = FakePeer("n")
    node.peers["n"] = peer
    assert node.strike_peer(peer, "test") is False
    assert node._peer_strike_count(peer) == 1
    assert node.strike_peer(peer, "test") is True
    assert node._is_banned("n")
