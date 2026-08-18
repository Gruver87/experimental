#!/usr/bin/env python3
"""Industrial P2P hardening: wire limits, topology scores, auto prod-mesh detect."""

import asyncio
import importlib.util
import json
import os
import sys
import time
import urllib.error

import pytest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from network.p2p_node import (
    DEFAULT_MAX_P2P_LINE_BYTES,
    PeerConnection,
    WireReject,
    _max_p2p_line_bytes,
    should_defer_tip_safety_skip_ahead,
)
from runtime.config import Config


class _FakeReader:
    def __init__(self, payload: bytes):
        self._buf = bytes(payload)
        self._pos = 0

    async def read(self, n: int = -1):
        if self._pos >= len(self._buf):
            return b""
        if n is None or n < 0:
            chunk = self._buf[self._pos :]
            self._pos = len(self._buf)
            return chunk
        chunk = self._buf[self._pos : self._pos + int(n)]
        self._pos += len(chunk)
        return chunk

    async def readline(self):
        if self._pos >= len(self._buf):
            return b""
        nl = self._buf.find(b"\n", self._pos)
        if nl < 0:
            chunk = self._buf[self._pos :]
            self._pos = len(self._buf)
            return chunk
        chunk = self._buf[self._pos : nl + 1]
        self._pos = nl + 1
        return chunk


class _SeqReader:
    def __init__(self, lines):
        self._buf = b"".join(lines)
        self._pos = 0

    async def read(self, n: int = -1):
        if self._pos >= len(self._buf):
            return b""
        if n is None or n < 0:
            chunk = self._buf[self._pos :]
            self._pos = len(self._buf)
            return chunk
        chunk = self._buf[self._pos : self._pos + int(n)]
        self._pos += len(chunk)
        return chunk

    async def readline(self):
        if self._pos >= len(self._buf):
            return b""
        nl = self._buf.find(b"\n", self._pos)
        if nl < 0:
            chunk = self._buf[self._pos :]
            self._pos = len(self._buf)
            return chunk
        chunk = self._buf[self._pos : nl + 1]
        self._pos = nl + 1
        return chunk


class _FakeWriter:
    def get_extra_info(self, key, default=None):
        if key == "peername":
            return ("127.0.0.1", 5001)
        return default

    def write(self, _data):
        pass

    async def drain(self):
        pass

    def close(self):
        pass


def test_peer_hook_failure_is_logged_not_raised(caplog):
    import logging

    peer = PeerConnection(_FakeReader(b""), _FakeWriter())
    peer.peer_id = "hook-peer"

    def boom():
        raise RuntimeError("hook boom")

    peer._on_send_fail = boom
    with caplog.at_level(logging.WARNING, logger="P2P"):
        peer._invoke_peer_hook(peer._on_send_fail, name="send_fail")
    assert "send_fail hook failed" in caplog.text
    assert "hook boom" in caplog.text


@pytest.mark.asyncio
async def test_recv_rejects_oversized_line():
    peer = PeerConnection(_FakeReader(b"x" * 5000), _FakeWriter())
    cfg = Config()
    cfg.p2p_max_message_bytes = 1024
    msg = await peer.recv(cfg)
    assert isinstance(msg, WireReject)
    assert msg.reason == "p2p_line_too_large"


@pytest.mark.asyncio
async def test_recv_rejects_bad_json_line():
    peer = PeerConnection(_FakeReader(b"not-json{{{{\n"), _FakeWriter())
    msg = await peer.recv(Config())
    assert isinstance(msg, WireReject)
    assert msg.reason == "bad_wire_line"


@pytest.mark.asyncio
async def test_message_loop_strikes_on_bad_wire_line():
    from network.p2p_node import P2PNode

    cfg = Config()
    cfg.p2p_rate_limit_strikes = 1
    cfg.p2p_ban_seconds = 60
    p2p = P2PNode(cfg, None, None)
    p2p._running = True
    peer = PeerConnection(_SeqReader([b"garbage\n", b""]), _FakeWriter())
    peer.peer_id = "wire-bad"
    peer.host = "127.0.0.1"
    peer.port = 9100
    p2p.peers[peer.peer_id] = peer
    await p2p._message_loop(peer)
    sec = p2p.get_p2p_security_status()
    shape = sec["shape_rejects"]
    assert (
        shape.get("bad_wire_line", 0) >= 1
        or shape.get("p2p_json_invalid", 0) >= 1
    )
    assert p2p._is_banned("wire-bad") is True


@pytest.mark.asyncio
async def test_recv_accepts_valid_json_line():
    payload = json.dumps({"type": "ping", "data": {}}).encode() + b"\n"
    peer = PeerConnection(_FakeReader(payload), _FakeWriter())
    msg = await peer.recv(Config())
    assert msg is not None
    assert not isinstance(msg, WireReject)
    assert msg["type"] == "ping"


@pytest.mark.asyncio
async def test_line_framer_construct_failure_logs_and_falls_back(monkeypatch, caplog):
    import logging

    def _boom(*_a, **_k):
        raise RuntimeError("framer boom")

    monkeypatch.setattr("network.p2p_node.native.P2PLineFramer", _boom)
    payload = json.dumps({"type": "ping", "data": {}}).encode() + b"\n"
    peer = PeerConnection(_FakeReader(payload), _FakeWriter())
    with caplog.at_level(logging.WARNING, logger="P2P"):
        msg = await peer.recv(Config())
    assert "P2PLineFramer construct failed" in caplog.text
    assert "framer boom" in caplog.text
    assert msg is not None
    assert not isinstance(msg, WireReject)
    assert msg["type"] == "ping"


def test_max_p2p_line_bytes_clamps_config():
    cfg = Config()
    cfg.p2p_max_message_bytes = 100
    assert _max_p2p_line_bytes(cfg) == 4096
    cfg.p2p_max_message_bytes = 999999999
    assert _max_p2p_line_bytes(cfg) == 16 * 1024 * 1024
    assert _max_p2p_line_bytes(Config()) == DEFAULT_MAX_P2P_LINE_BYTES


def _load_verify_p2p():
    path = os.path.join(ROOT, "scripts", "verify_p2p_ci.py")
    spec = importlib.util.spec_from_file_location("verify_p2p_ci", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_verify_p2p_auto_prefers_devnet_over_prod_mesh(monkeypatch):
    mod = _load_verify_p2p()

    def fake_probe(url):
        return url in (
            mod.PROD_MESH_URL1,
            mod.PROD_MESH_URL2,
            mod.PROD_MESH_URL3,
            mod.DEVNET_URL1,
            mod.DEVNET_URL2,
        )

    monkeypatch.setattr(mod, "_probe_health", fake_probe)
    monkeypatch.setattr(mod, "verify_pair", lambda *a, **k: 0)
    monkeypatch.setattr(sys, "argv", ["verify_p2p_ci.py", "--mode", "auto", "--prefer-devnet"])
    assert mod.main() == 0


def test_verify_p2p_auto_detects_prod_mesh_with_prefer_flag(monkeypatch):
    mod = _load_verify_p2p()

    def fake_probe(url):
        return url in (
            mod.PROD_MESH_URL1,
            mod.PROD_MESH_URL2,
            mod.PROD_MESH_URL3,
        )

    monkeypatch.setattr(mod, "_probe_health", fake_probe)
    monkeypatch.setattr(mod, "verify_triple", lambda *a, **k: 0)
    monkeypatch.setattr(mod, "verify_prod_consensus_mesh3", lambda *a, **k: 0)
    monkeypatch.setattr(mod, "verify_prod_post_checks", lambda *a, **k: 0)
    monkeypatch.setattr(
        sys,
        "argv",
        ["verify_p2p_ci.py", "--mode", "auto", "--prefer-prod-mesh"],
    )
    assert mod.main() == 0


def test_consistency_harness_uses_long_timeout_on_prod_ports(monkeypatch):
    mod = _load_verify_p2p()
    calls = []

    def fake_api(url, timeout=10):
        calls.append((url, timeout))
        return {"harness_healthy": True, "live_state_root": "0xabc", "failed_checks": []}

    monkeypatch.setattr(mod, "_api", fake_api)
    mod._consistency_harness("http://127.0.0.1:18180")
    assert calls
    assert calls[0][1] >= 45.0
    assert "quick=1" in calls[0][0]


@pytest.mark.asyncio
async def test_recv_rejects_on_unexpected_io_error():
    class _BoomReader:
        async def readline(self):
            raise RuntimeError("boom")

    peer = PeerConnection(_BoomReader(), _FakeWriter())
    msg = await peer.recv(Config())
    assert isinstance(msg, WireReject)
    assert msg.reason == "recv_error"


@pytest.mark.asyncio
async def test_message_loop_strikes_on_rate_limit():
    from network.p2p_node import MSG_ATTESTATION, P2PNode

    cfg = Config()
    cfg.p2p_max_messages_per_sec = 1
    cfg.p2p_rate_limit_strikes = 1
    cfg.p2p_ban_seconds = 60
    p2p = P2PNode(cfg, None, None)
    p2p._running = True
    peer_id = "rl-peer"
    assert p2p._rate_limit_ok(peer_id, MSG_ATTESTATION) is True
    line = (
        json.dumps({"type": MSG_ATTESTATION, "data": {"validator": "x"}}).encode()
        + b"\n"
    )
    peer = PeerConnection(_SeqReader([line, b""]), _FakeWriter())
    peer.peer_id = peer_id
    peer.host = "127.0.0.1"
    peer.port = 9200
    p2p.peers[peer.peer_id] = peer
    await p2p._message_loop(peer)
    sec = p2p.get_p2p_security_status()
    assert sec["rate_limit_drops"] >= 1
    assert sec["shape_rejects"].get("rate_limit_exceeded", 0) >= 1
    # Wave D: ingress rate_limit soft-refuses (drop + count) without PeerManager ban
    # — ban storms tore down docker mesh under sync bursts.
    assert p2p._is_banned(peer_id) is False
    assert int(getattr(p2p, "_soft_refuse_total", 0) or 0) >= 1


def test_p2p_rate_limit_drops_excess_messages():
    from network.p2p_node import P2PNode, MSG_PING
    from runtime.config import Config

    cfg = Config()
    cfg.p2p_max_messages_per_sec = 3
    p2p = P2PNode(cfg, None, None)
    assert p2p._rate_limit_ok("peer-a", MSG_PING) is True
    assert p2p._rate_limit_ok("peer-a") is True
    assert p2p._rate_limit_ok("peer-a") is True
    assert p2p._rate_limit_ok("peer-a") is True
    assert p2p._rate_limit_ok("peer-a") is False


def test_p2p_rate_limit_exempts_sync_types():
    from network.p2p_node import (
        MSG_BLOCK,
        MSG_BLOCKS,
        MSG_GET_BLOCK,
        MSG_GET_BLOCKS,
        MSG_NEW_BLOCK,
        MSG_NEW_TX,
        MSG_STATUS,
        P2PNode,
        RATE_LIMIT_EXEMPT_TYPES,
    )
    from runtime.config import Config

    cfg = Config()
    cfg.p2p_max_messages_per_sec = 2
    p2p = P2PNode(cfg, None, None)
    # v1.3.143: MSG_NEW_TX is on the primary rate budget (not exempt).
    assert MSG_NEW_TX not in RATE_LIMIT_EXEMPT_TYPES
    sync_types = (
        MSG_NEW_BLOCK,
        MSG_GET_BLOCK,
        MSG_GET_BLOCKS,
        MSG_BLOCK,
        MSG_BLOCKS,
        MSG_STATUS,
    )
    for _ in range(20):
        for msg_type in sync_types:
            assert p2p._rate_limit_ok("peer-sync", msg_type) is True
    # Primary budget still applies to new_tx gossip.
    assert p2p._rate_limit_ok("peer-tx", MSG_NEW_TX) is True
    assert p2p._rate_limit_ok("peer-tx", MSG_NEW_TX) is True
    assert p2p._rate_limit_ok("peer-tx", MSG_NEW_TX) is False


def test_verify_spawn_mesh3_recovery_wires_callbacks(monkeypatch):
    mod = _load_verify_p2p()
    captured = {}

    def fake_recovery(*_args, **kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mod, "verify_mesh3_recovery", fake_recovery)
    rc = mod.verify_spawn_mesh3_recovery(
        "http://127.0.0.1:15280",
        "http://127.0.0.1:15281",
        "http://127.0.0.1:15282",
        procs=[None, None, None],
        node2_cfg=os.path.join(ROOT, "node.example.json"),
        node2_log=os.path.join(ROOT, "data", "n2.log"),
        env={"PYTHONUNBUFFERED": "1"},
        label="test-spawn",
    )
    assert rc == 0
    assert captured.get("label") == "test-spawn"
    assert callable(captured.get("stop_node2"))
    assert callable(captured.get("start_node2"))


def test_industrial_gate_p2p_hardening_check():
    ig_path = os.path.join(ROOT, "scripts", "industrial_gate.py")
    spec = importlib.util.spec_from_file_location("industrial_gate", ig_path)
    ig = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(ig)
    errors, warnings = ig._check_p2p_hardening()
    assert not errors, errors


def test_p2p_strike_bans_after_threshold(caplog):
    from network.p2p_node import P2PNode
    from runtime.config import Config
    import logging

    cfg = Config()
    cfg.p2p_rate_limit_strikes = 2
    cfg.p2p_ban_seconds = 60
    p2p = P2PNode(cfg, None, None)
    peer = PeerConnection(_FakeReader(b""), _FakeWriter())
    peer.peer_id = "bad-peer"
    peer.host = "127.0.0.1"
    peer.port = 9001

    with caplog.at_level(logging.WARNING, logger="P2P"):
        assert p2p._strike_peer_sync(peer, "test") is False
        assert p2p._strike_peer_sync(peer, "test") is True
    assert p2p._is_banned("bad-peer") is True
    sec = p2p.get_p2p_security_status()
    assert sec["active_bans"] == 1
    assert sec["strikes_before_ban"] == 2
    assert sec["shape_rejects_total"] >= 2
    assert sec["shape_rejects"].get("test", 0) >= 2
    assert any("strike 1/2" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_handle_message_rejects_mid_session_handshake():
    from network.p2p_node import MSG_HANDSHAKE, MSG_HANDSHAKE_ACK, P2PNode

    cfg = Config()
    cfg.p2p_rate_limit_strikes = 1
    p2p = P2PNode(cfg, None, None)
    peer = PeerConnection(_FakeReader(b""), _FakeWriter())
    peer.peer_id = "hs-mid"
    p2p.peers[peer.peer_id] = peer
    removed = []
    p2p._remove_peer = lambda pid, p: removed.append(pid)

    await p2p._handle_message(peer, {"type": MSG_HANDSHAKE, "data": {"node_id": "x"}})
    assert removed == ["hs-mid"]
    sec = p2p.get_p2p_security_status()
    assert sec["handshake_rejects"] >= 1
    assert sec["shape_rejects"].get("mid_session_handshake", 0) >= 1

    # ACK mid-session also rejected (fresh peer)
    peer2 = PeerConnection(_FakeReader(b""), _FakeWriter())
    peer2.peer_id = "hs-ack"
    p2p.peers[peer2.peer_id] = peer2
    removed.clear()
    await p2p._handle_message(peer2, {"type": MSG_HANDSHAKE_ACK, "data": {"accepted": True}})
    assert removed == ["hs-ack"]
    assert p2p.get_p2p_security_status()["shape_rejects"].get("mid_session_handshake", 0) >= 2


@pytest.mark.asyncio
async def test_status_refresh_counts_peer_status_send_fail():
    from network.p2p_node import P2PNode

    class _BoomWriter(_FakeWriter):
        def write(self, _data):
            raise OSError("broken pipe")

    cfg = Config()
    blockchain = MagicMock()
    blockchain.get_height.return_value = 1
    blockchain.get_last_block.return_value = {"hash": "ab" * 32, "height": 1}
    p2p = P2PNode(cfg, blockchain, None)
    peer = PeerConnection(_FakeReader(b""), _BoomWriter())
    p2p._attach_peer_hooks(peer)
    peer.peer_id = "already"
    peer.host = "127.0.0.1"
    peer.port = 5000
    p2p.peers[peer.peer_id] = peer
    p2p._known_addrs = ["127.0.0.1:5000"]
    result = await p2p.reconnect_known_peers()
    assert any(a.get("ok") is False for a in result.get("attempts", []))
    sec = p2p.get_p2p_security_status()
    assert sec["ops_errors"]["peer_status_send_fail"] >= 1
    assert sec["ops_errors"]["peer_send_fail"] >= 1


@pytest.mark.asyncio
async def test_catch_up_status_send_fail_increments_counter():
    from network.p2p_node import P2PNode

    class _BoomWriter(_FakeWriter):
        def write(self, _data):
            raise OSError("broken pipe")

    cfg = Config()
    blockchain = MagicMock()
    blockchain.get_height.return_value = 1
    blockchain.get_last_block.return_value = {"hash": "cd" * 32, "height": 1}
    p2p = P2PNode(cfg, blockchain, None)
    p2p._running = True
    peer = PeerConnection(_FakeReader(b""), _BoomWriter())
    p2p._attach_peer_hooks(peer)
    peer.peer_id = "catch-peer"
    peer.height = 0
    p2p.peers[peer.peer_id] = peer

    # Enqueue succeeds; broken pipe is reported by the send worker via _on_send_fail.
    our_status = {"height": 1, "head_hash": "aa" * 32}
    ok_send = await peer.send("status", our_status)
    assert ok_send is True
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        if p2p.get_p2p_security_status()["ops_errors"]["peer_send_fail"] >= 1:
            break
        await asyncio.sleep(0.05)
    sec = p2p.get_p2p_security_status()
    assert sec["ops_errors"]["peer_send_fail"] >= 1
    assert "maintenance_loop_fail" in sec["ops_errors"]
    assert "catch_up_loop_fail" in sec["ops_errors"]


@pytest.mark.asyncio
async def test_handle_message_rejects_noisy_ping_payload():
    from network.p2p_node import MSG_PING, P2PNode

    cfg = Config()
    cfg.p2p_rate_limit_strikes = 1
    p2p = P2PNode(cfg, None, None)
    peer = PeerConnection(_FakeReader(b""), _FakeWriter())
    peer.peer_id = "hk-peer"
    p2p.peers[peer.peer_id] = peer
    removed = []
    p2p._remove_peer = lambda pid, p: removed.append(pid)

    await p2p._handle_message(peer, {"type": MSG_PING, "data": {"noise": [1, 2, 3]}})
    assert removed == ["hk-peer"]
    assert p2p.get_p2p_security_status()["shape_rejects"].get("bad_ping_payload", 0) >= 1


@pytest.mark.asyncio
async def test_handle_message_rejects_noisy_get_peers_payload():
    from network.p2p_node import MSG_GET_PEERS, P2PNode

    cfg = Config()
    cfg.p2p_rate_limit_strikes = 1
    p2p = P2PNode(cfg, None, None)
    peer = PeerConnection(_FakeReader(b""), _FakeWriter())
    peer.peer_id = "hk-peers"
    p2p.peers[peer.peer_id] = peer
    removed = []
    p2p._remove_peer = lambda pid, p: removed.append(pid)

    await p2p._handle_message(peer, {"type": MSG_GET_PEERS, "data": {"x": 1}})
    assert removed == ["hk-peers"]
    assert p2p.get_p2p_security_status()["shape_rejects"].get("bad_get_peers_payload", 0) >= 1


@pytest.mark.asyncio
async def test_peer_send_fail_increments_ops_counter():
    from network.p2p_node import P2PNode

    class _BoomWriter(_FakeWriter):
        def write(self, _data):
            raise OSError("broken pipe")

    cfg = Config()
    p2p = P2PNode(cfg, None, None)
    peer = PeerConnection(_FakeReader(b""), _BoomWriter())
    p2p._attach_peer_hooks(peer)
    peer.peer_id = "send-fail"
    ok = await peer.send("ping", {"ts": 1.0})
    assert ok is True
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        if p2p.get_p2p_security_status()["ops_errors"]["peer_send_fail"] >= 1:
            break
        await asyncio.sleep(0.05)
    assert p2p.get_p2p_security_status()["ops_errors"]["peer_send_fail"] >= 1


@pytest.mark.asyncio
async def test_handle_message_rejects_unknown_wire_type():
    from network.p2p_node import P2PNode
    from runtime.config import Config

    cfg = Config()
    cfg.p2p_rate_limit_strikes = 1
    p2p = P2PNode(cfg, None, None)
    peer = PeerConnection(_FakeReader(b""), _FakeWriter())
    peer.peer_id = "peer-x"
    p2p.peers[peer.peer_id] = peer

    removed = []
    p2p._remove_peer = lambda pid, p: removed.append(pid)

    await p2p._handle_message(peer, {"type": "totally_unknown", "data": {}})
    assert removed == ["peer-x"]
    assert p2p._is_banned("peer-x") is True


def test_p2p_evicts_low_score_peer_when_alternative_exists():
    from network.p2p_node import P2PNode, _peer_health_score
    from runtime.config import Config

    class _Chain:
        def get_height(self):
            return 100

    cfg = Config()
    cfg.p2p_evict_min_score = 50
    p2p = P2PNode(cfg, _Chain(), None)

    good = PeerConnection(_FakeReader(b""), _FakeWriter())
    good.peer_id = "good"
    good.height = 100
    good.last_seen = time.time()

    bad = PeerConnection(_FakeReader(b""), _FakeWriter())
    bad.peer_id = "bad"
    bad.height = 0
    bad.last_seen = time.time() - 999

    p2p.peers = {"good": good, "bad": bad}
    removed = p2p._prune_stale_peers()
    assert removed == 1
    assert "bad" not in p2p.peers
    assert "good" in p2p.peers


def test_peer_health_score_helper():
    from network.p2p_node import _peer_health_score

    assert _peer_health_score(height_gap=0, last_seen_age=0, health_timeout=60) == 100
    assert _peer_health_score(height_gap=3, last_seen_age=0, health_timeout=60) == 55
    assert _peer_health_score(height_gap=0, last_seen_age=70, health_timeout=60) == 50
    # v1.3.145: strikes / import fails penalize soft score
    assert (
        _peer_health_score(
            height_gap=0, last_seen_age=0, health_timeout=60, strikes=2, import_fails=1
        )
        == 100 - 24 - 10
    )


def test_p2p_maintenance_loop_prunes_stale_peers():
    from network.p2p_node import P2PNode

    class _Chain:
        def get_height(self):
            return 10

    cfg = Config()
    cfg.peer_timeout = 5
    p2p = P2PNode(cfg, _Chain(), None)
    stale = PeerConnection(_FakeReader(b""), _FakeWriter())
    stale.peer_id = "stale"
    stale.last_seen = time.time() - 999
    p2p.peers = {"stale": stale}
    removed = p2p._prune_stale_peers(max_age=30)
    assert removed == 1
    assert "stale" not in p2p.peers


@pytest.mark.asyncio
async def test_handshake_chain_id_mismatch_strikes_and_bans():
    from network.p2p_node import MSG_HANDSHAKE_ACK, P2PNode

    class _Chain:
        def get_height(self):
            return 10

        def get_last_block(self):
            return {"hash": "0xdeadbeef"}

    cfg = Config()
    cfg.chain_id = 77777
    cfg.p2p_rate_limit_strikes = 2
    cfg.p2p_ban_seconds = 60
    p2p = P2PNode(cfg, _Chain(), None)
    peer = PeerConnection(_FakeReader(b""), _FakeWriter())
    peer.host = "10.0.0.9"
    peer.port = 5009

    async def _wrong_chain_handshake(_peer, initiator=False):
        wrong = json.dumps(
            {
                "type": MSG_HANDSHAKE_ACK,
                "data": {
                    "chain_id": 99999,
                    "node_id": "bad-peer",
                    "height": 1,
                    "head_hash": "0xabc",
                    "p2p_port": 5009,
                },
            }
        ).encode() + b"\n"
        peer._fake_payload = wrong  # type: ignore[attr-defined]

        async def _recv(_config=None):
            return json.loads(wrong.decode().strip())

        peer.recv = _recv  # type: ignore[method-assign]
        return await p2p._do_handshake(peer, initiator=True)

    assert await _wrong_chain_handshake(peer) is False
    assert p2p._handshake_rejects == 1
    assert await _wrong_chain_handshake(peer) is False
    assert p2p._is_addr_banned("10.0.0.9", 5009) is True
    sec = p2p.get_p2p_security_status()
    assert sec["handshake_rejects"] == 2
    assert sec["active_bans"] == 1


def test_verify_p2p_security_mesh_ok(monkeypatch):
    mod = _load_verify_p2p()

    def fake_api(url, timeout=10):
        if url.endswith("/p2p/security"):
            return {
                "max_message_bytes": 2_097_152,
                "rate_limit_per_sec": 500,
                "strikes_before_ban": 5,
                "active_bans": 0,
            }
        if url.endswith("/status"):
            return {
                "p2p_summary": {
                    "enabled": True,
                    "security": {
                        "max_message_bytes": 2_097_152,
                        "rate_limit_per_sec": 500,
                    },
                }
            }
        raise AssertionError(url)

    monkeypatch.setattr(mod, "_api", fake_api)
    assert mod.verify_p2p_security_mesh(["http://127.0.0.1:8080"]) == 0


def test_verify_p2p_security_mesh_topology_fallback(monkeypatch):
    mod = _load_verify_p2p()

    def fake_api(url, timeout=10):
        if url.endswith("/p2p/security"):
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        if url.endswith("/p2p/topology"):
            return {
                "security": {
                    "max_message_bytes": 2_097_152,
                    "rate_limit_per_sec": 500,
                    "strikes_before_ban": 5,
                }
            }
        if url.endswith("/status"):
            return {"p2p_summary": {"enabled": False}}
        raise AssertionError(url)

    monkeypatch.setattr(mod, "_api", fake_api)
    assert mod.verify_p2p_security_mesh(["http://127.0.0.1:18180"]) == 0


def test_verify_p2p_security_mesh_detects_mismatch(monkeypatch):
    mod = _load_verify_p2p()

    def fake_api(url, timeout=10):
        if url.endswith("/p2p/security"):
            return {
                "max_message_bytes": 2_097_152,
                "rate_limit_per_sec": 500,
                "strikes_before_ban": 5,
            }
        if url.endswith("/status"):
            return {
                "p2p_summary": {
                    "enabled": True,
                    "security": {"max_message_bytes": 1024, "rate_limit_per_sec": 500},
                }
            }
        raise AssertionError(url)

    monkeypatch.setattr(mod, "_api", fake_api)
    assert mod.verify_p2p_security_mesh(["http://127.0.0.1:8080"]) == 15


def test_defer_tip_safety_skip_ahead_only_busy_tip_plus_two():
    assert should_defer_tip_safety_skip_ahead(
        apply_busy=True, candidate_height=9548, tip_height=9546
    )
    assert not should_defer_tip_safety_skip_ahead(
        apply_busy=False, candidate_height=9548, tip_height=9546
    )
    assert not should_defer_tip_safety_skip_ahead(
        apply_busy=True, candidate_height=9547, tip_height=9546
    )
    assert not should_defer_tip_safety_skip_ahead(
        apply_busy=True, candidate_height=9550, tip_height=9546
    )


def test_note_local_forge_records_height_monotonic():
    from network.p2p_node import P2PNode

    node = P2PNode.__new__(P2PNode)
    node._wire_probe_hold_until = 0.0
    node._last_local_forge_height = 0
    node.note_local_forge(0.5, height=9566)
    assert node._last_local_forge_height == 9566
    node.note_local_forge(0.5, height=9567)
    assert node._last_local_forge_height == 9567
    node.note_local_forge(0.5, height=9560)
    assert node._last_local_forge_height == 9567


def test_tip_safety_precheck_defers_own_forge_echo_not_history():
    from network.p2p_node import P2PNode

    class _Chain:
        def get_height(self):
            return 9565

    node = P2PNode.__new__(P2PNode)
    node.blockchain = _Chain()
    node.apply_queue = None
    node.tip_safety_shadow = object()
    node._last_local_forge_height = 9567
    assert node._tip_safety_precheck({"height": 9567}) is True
    assert node._tip_safety_precheck({"height": 9568}) is True
    # Deep history must still go through observe/enforce (shadow is a dummy
    # so observe will fail closed via exception → precheck True only after
    # observe path). Use a refusing shadow.
    class _Refuse:
        enforce = True

        def observe_before_import(self, *_a, **_k):
            return MagicMock(accepted=False, reason_code="tip_unknown_parent")

        def allows_import(self, _d):
            return False

        def record_enforce_refuse(self, _d):
            return "tip_unknown_parent"

    node.tip_safety_shadow = _Refuse()
    node._import_block_fail = 0
    assert node._tip_safety_precheck({"height": 9000}) is False

