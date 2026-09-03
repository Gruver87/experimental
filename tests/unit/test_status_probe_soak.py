#!/usr/bin/env python3
"""GET /status?probe=1 must stay fast for 48h health_watch (no full status HOL)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import api.http as http_module
from api.http import RESTHandler, ThreadedHTTPServer, configure_rate_limiter
from blockchain.mempool import Mempool
from core.blockchain import Blockchain
from runtime.config import Config
from storage.database import Database


def _free_port() -> int:
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class _ProbeP2P:
    _running = True
    _state_consistent = True

    def peer_count(self) -> int:
        return 2

    def get_peers_info(self):
        return [
            {"id": "peer-a", "height": 3, "head": "aa"},
            {"id": "peer-b", "height": 3, "head": "aa"},
        ]

    def get_p2p_security_status(self):
        return {
            "rate_limit_per_sec": 10,
            "handshake_rejects": 0,
            "shape_rejects_total": 0,
            "shape_rejects": {},
            "rate_limit_drops": 0,
            "active_bans": 0,
            "attestation_local_fail": 0,
            "ops_errors": {},
            "tls": {"enabled": False, "ready": False},
            "libp2p": {"feature_libp2p": True, "active": True},
            "max_message_bytes": 65536,
        }


def test_status_probe_is_fast_and_slim(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "unit-test-status-probe-secret-32bytes")
    fd, path = tempfile.mkstemp(suffix=".db", dir=tmp_path)
    os.close(fd)
    cfg = Config()
    cfg.db_path = path
    cfg.http_port = _free_port()
    cfg.deployment_mode = "prod"
    cfg.bridge_enabled = False
    cfg.jwt_enforce_admin = False
    cfg.rpc_api_key_required = False
    cfg.rate_limit_rpm = 100_000
    cfg.require_wallet_file = False
    db = Database(path)
    db.initialize()
    bc = Blockchain(cfg, db)
    mp = Mempool(cfg, db)
    RESTHandler.config = cfg
    RESTHandler.blockchain = bc
    RESTHandler.mempool = mp
    RESTHandler.db = db
    RESTHandler.wallet = None
    RESTHandler.bridge = None
    RESTHandler.cross_bridge = None
    RESTHandler.p2p = _ProbeP2P()
    RESTHandler.consensus_adapter = None
    RESTHandler.project_root = os.path.dirname(
        os.path.dirname(os.path.abspath(http_module.__file__))
    )
    configure_rate_limiter(cfg)
    server = ThreadedHTTPServer(("127.0.0.1", cfg.http_port), RESTHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.25)
    try:
        started = time.perf_counter()
        with urllib.request.urlopen(
            f"http://127.0.0.1:{cfg.http_port}/status?probe=1", timeout=2.5
        ) as resp:
            body = json.loads(resp.read().decode())
        elapsed = time.perf_counter() - started
        assert elapsed < 2.0, f"GET /status?probe=1 too slow ({elapsed:.2f}s)"
        assert body.get("probe") is True
        assert int(body.get("peers") or 0) == 2
        assert isinstance(body.get("p2p_sync_status"), str)
        assert "status_handler_ms" in body
        assert "validators_registered" not in body
        assert "rust_bridge" not in body
    finally:
        server.shutdown()
        db.close()
        os.remove(path)
