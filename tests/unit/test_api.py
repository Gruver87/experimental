#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests: industrial API surface (health, config, metrics)."""

import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from runtime.config import Config
from observability.metrics import MetricsCollector
import api.http as http_api
from api.http import create_http_server, RESTHandler, ThreadedHTTPServer, configure_rate_limiter
from storage.database import Database
from kernel.event_bus import EventBus
from core.blockchain import Blockchain
from blockchain.mempool import Mempool


@pytest.fixture
def industrial_config(tmp_path):
    cfg = Config()
    cfg.db_path = str(tmp_path / "test.db")
    cfg.http_port = 18080
    cfg.rpc_port = 18545
    cfg.p2p_port = 15000
    cfg.deployment_mode = "dev"
    cfg.node_id = "test-node"
    cfg.metrics_enabled = True
    cfg.jwt_enforce_admin = False
    return cfg


@pytest.fixture
def api_server(industrial_config):
    db = Database(industrial_config.db_path, synchronous="NORMAL")
    db.initialize()
    bus = EventBus()
    bc = Blockchain(industrial_config, db, bus)
    mp = Mempool(max_size=1000, min_fee=0.001)
    server = create_http_server(bc, mp, db, industrial_config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{industrial_config.http_port}"
    yield base, industrial_config
    server.shutdown()


def _get(url: str) -> tuple:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, resp.read()


def _post(url: str, payload: dict) -> tuple:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, resp.read()


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_config_apply_env_prod_wallet_required(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "prod")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg = Config()
    cfg.apply_env()
    errors = cfg.validate()
    assert any("wallet" in e for e in errors)
    assert cfg.is_production
    assert cfg.sqlite_synchronous == "FULL"
    assert cfg.enable_cors_rpc_proxy is False


def test_metrics_prometheus_format():
    mc = MetricsCollector()
    text = mc.render_prometheus(
        height=42,
        peers=3,
        mempool=7,
        node_id="n1",
        native_crypto={
            "available": True,
            "required": True,
            "self_test": True,
            "kernels": ["sha256", "secp256k1_verify"],
        },
        bridge_health={
            "enabled": True,
            "mode": "rust",
            "required": True,
            "ok": True,
            "l1_rpc": {"configured": True, "required": True, "ok": True},
        },
        p2p_security={
            "handshake_rejects": 2,
            "shape_rejects_total": 5,
            "active_bans": 1,
            "rate_limit_drops": 7,
            "shape_rejects": {"bad_wire_tx": 3, "bad_block_announce": 2},
            "ops_errors": {
                "peer_send_fail": 4,
                "peer_status_send_fail": 1,
            },
            "attestation_local_fail": 3,
        },
        rocksdb_tuning={
            "column_families": False,
            "block_cache_mb": 256,
            "write_buffer_mb": 64,
            "source": "live",
            "engine": "rocksdb",
            "json_decode_failures": 3,
        },
        sync_status={
            "state_consistent": False,
            "wire_probe_ok": False,
            "wire_probe_probed": True,
        },
    )
    assert "abs_chain_height" in text
    assert 'abs_chain_height{node_id="n1"} 42' in text
    assert "abs_uptime_seconds" in text
    assert 'abs_native_crypto_available{node_id="n1"} 1' in text
    assert 'abs_native_crypto_kernel_enabled{node_id="n1",kernel="secp256k1_verify"} 1' in text
    assert 'abs_rust_bridge_enabled{node_id="n1"} 1' in text
    assert 'abs_rust_bridge_required{node_id="n1"} 1' in text
    assert 'abs_rust_bridge_ok{node_id="n1"} 1' in text
    assert 'abs_l1_rpc_configured{node_id="n1"} 1' in text
    assert 'abs_l1_rpc_required{node_id="n1"} 1' in text
    assert 'abs_l1_rpc_ok{node_id="n1"} 1' in text
    assert 'abs_p2p_shape_rejects_total{node_id="n1"} 5' in text
    assert 'abs_p2p_shape_rejects{node_id="n1",reason="bad_wire_tx"} 3' in text
    assert 'abs_p2p_handshake_rejects_total{node_id="n1"} 2' in text
    assert 'abs_p2p_attestation_local_fail_total{node_id="n1"} 3' in text
    assert 'abs_p2p_rate_limit_drops_total{node_id="n1"} 7' in text
    assert 'abs_p2p_peer_send_fail_total{node_id="n1"} 4' in text
    assert 'abs_p2p_ops_errors{node_id="n1",kind="peer_send_fail"} 4' in text
    assert 'abs_db_engine{node_id="n1",engine="rocksdb"} 1' in text
    assert 'abs_rocksdb_column_families{node_id="n1"} 0' in text
    assert 'abs_rocksdb_block_cache_mb{node_id="n1"} 256' in text
    assert 'abs_rocksdb_write_buffer_mb{node_id="n1"} 64' in text
    assert 'abs_rocksdb_json_decode_failures{node_id="n1"} 3' in text
    assert 'abs_rocksdb_running_compactions{node_id="n1"} 0' in text
    assert 'abs_state_consistent{node_id="n1"} 0' in text
    assert 'abs_sync_wire_probe_ok{node_id="n1"} 0' in text
    assert 'abs_sync_wire_probe_probed{node_id="n1"} 1' in text
    assert 'source="live"' in text


def test_metrics_status_duration_histogram():
    mc = MetricsCollector()
    text0 = mc.render_prometheus(node_id="n1")
    assert "abs_http_status_duration_ms" in text0
    assert 'abs_http_status_duration_ms_count{node_id="n1"} 0' in text0
    mc.observe_status_ms(12.0)
    mc.observe_status_ms(2500.0)
    mc.observe_status_ms(float("nan"))
    text = mc.render_prometheus(node_id="n1")
    assert 'abs_http_status_duration_ms_count{node_id="n1"} 2' in text
    assert 'abs_http_status_duration_ms_bucket{node_id="n1",le="50"} 1' in text
    assert 'abs_http_status_duration_ms_bucket{node_id="n1",le="2000"} 1' in text
    assert 'abs_http_status_duration_ms_bucket{node_id="n1",le="5000"} 2' in text
    assert 'abs_http_status_duration_ms_bucket{node_id="n1",le="+Inf"} 2' in text
    assert 'abs_http_status_last_ms{node_id="n1"} 2500.000' in text
    assert 'abs_http_status_max_ms{node_id="n1"} 2500.000' in text


def test_metrics_prometheus_never_probed_gauge():
    mc = MetricsCollector()
    text = mc.render_prometheus(
        node_id="n1",
        sync_status={
            "state_consistent": True,
            "wire_probe_ok": False,
            "wire_probe_probed": False,
        },
    )
    assert 'abs_sync_wire_probe_ok{node_id="n1"} -1' in text
    assert 'abs_sync_wire_probe_probed{node_id="n1"} 0' in text


def test_metrics_sqlite_skips_rocksdb_gauges():
    mc = MetricsCollector()
    text = mc.render_prometheus(
        node_id="n1",
        rocksdb_tuning={"engine": "sqlite", "source": "none"},
    )
    assert 'abs_db_engine{node_id="n1",engine="sqlite"} 1' in text
    assert "abs_rocksdb_column_families" not in text
    assert "abs_rocksdb_block_cache_mb" not in text
    assert "abs_rocksdb_write_buffer_mb" not in text


def test_health_live(api_server):
    base, _ = api_server
    status, body = _get(f"{base}/health/live")
    data = json.loads(body)
    assert status == 200
    assert data["status"] == "alive"
    assert data["node_id"] == "test-node"


def test_health_ready(api_server):
    base, _ = api_server
    status, body = _get(f"{base}/health/ready")
    data = json.loads(body)
    assert status == 200
    assert data["status"] == "ready"
    assert data["checks"]["blockchain"] is True
    assert data["checks"]["native_crypto"] is True
    assert data["checks"]["rust_bridge"] is True
    assert "native_crypto" in data
    assert "rust_bridge" in data


def test_metrics_endpoint(api_server):
    base, _ = api_server
    status, body = _get(f"{base}/metrics")
    text = body.decode()
    assert status == 200
    assert "abs_chain_height" in text
    assert "abs_native_crypto_available" in text
    assert 'kernel="state_root"' in text
    assert "abs_rust_bridge_ok" in text
    assert "abs_l1_rpc_ok" in text


def test_native_crypto_endpoint(api_server):
    base, _ = api_server
    status, body = _get(f"{base}/native/crypto")
    data = json.loads(body)
    assert status == 200
    assert data["ready"] is True
    assert "native_crypto" in data
    assert "sha256" in data["native_crypto"]["kernels"]
    assert "secp256k1_verify" in data["native_crypto"]["kernels"]


def test_status_has_health_links(api_server):
    base, _ = api_server
    status, body = _get(f"{base}/status")
    data = json.loads(body)
    assert status == 200
    assert "health" in data
    assert data["health"]["live"] == "/health/live"
    assert data.get("api_docs") == "/docs"
    assert data.get("openapi") == "/openapi.json"
    assert "bridge_pending" in data
    assert "bridge_locks_total" in data
    assert data["bridge_pending"] == 0
    assert "status_handler_ms" in data
    assert isinstance(data["status_handler_ms"], (int, float))
    assert data["status_handler_ms"] >= 0
    assert "native_crypto" in data
    assert "secp256k1_verify" in data["native_crypto"]["kernels"]
    assert "rust_bridge" in data
    assert "ok" in data["rust_bridge"]


def test_openapi_lists_native_crypto(api_server):
    base, _ = api_server
    status, body = _get(f"{base}/openapi.json")
    data = json.loads(body)
    assert status == 200
    assert "/native/crypto" in data["paths"]


def test_status_bridge_pending_counts(api_server, industrial_config):
    base, cfg = api_server
    cfg.bridge_enabled = True
    db = Database(cfg.db_path, synchronous="NORMAL")
    db.save_bridge_lock("0xfrom", "ethereum", "0xto", 5.0, "pending99")
    status, body = _get(f"{base}/status")
    data = json.loads(body)
    assert status == 200
    assert data["bridge_pending"] == 1
    assert data["bridge_locks_total"] == 1


def test_peers_alias(api_server):
    base, _ = api_server
    status, body = _get(f"{base}/peers")
    data = json.loads(body)
    assert status == 200
    assert "peers" in data
    assert "solo_mode" in data
    assert data["count"] == 0
    assert data["solo_mode"] is True


def test_bridge_overview(api_server):
    base, _ = api_server
    status, body = _get(f"{base}/bridge")
    data = json.loads(body)
    assert status == 200
    assert data["enabled"] is False
    assert data["mode"] in ("simulator", "rust")
    assert "locks" in data
    assert "supported_chains" in data
    assert "rust_bridge_health" in data


def test_prod_health_ready_fails_when_required_rust_bridge_is_bad(tmp_path, monkeypatch):
    cfg = Config()
    cfg.db_path = str(tmp_path / "ready-prod.db")
    cfg.http_port = _free_port()
    cfg.deployment_mode = "prod"
    cfg.bridge_enabled = True
    cfg.bridge_mode = "rust"
    cfg.rate_limit_rpm = 120
    cfg.require_native_crypto = False
    db = Database(cfg.db_path, synchronous="NORMAL")
    db.initialize()
    bc = Blockchain(cfg, db, EventBus())
    mp = Mempool(max_size=100, min_fee=0.001)
    monkeypatch.setattr(
        http_api,
        "_rust_bridge_health",
        lambda _cfg: {
            "enabled": True,
            "mode": "rust",
            "required": True,
            "ok": False,
            "error": "bad bridge",
        },
    )
    server = create_http_server(bc, mp, db, cfg)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"http://127.0.0.1:{cfg.http_port}/health/ready", timeout=5)
        body = json.loads(exc_info.value.read().decode())
        assert exc_info.value.code == 503
        assert body["status"] == "not_ready"
        assert body["checks"]["rust_bridge"] is False
        assert body["rust_bridge"]["error"] == "bad bridge"
    finally:
        server.shutdown()
        db.close()


def test_bridge2_transfer_requires_rust_bridge(api_server):
    base, _ = api_server
    payload = {
        "from_chain": "ethereum",
        "to_chain": "absolute",
        "from_address": "0x" + "a" * 40,
        "to_address": "0x" + "b" * 40,
        "amount": 1.0,
    }
    try:
        _post(f"{base}/bridge2/transfer", payload)
        assert False, "bridge2 transfer should not fallback to simulator"
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read().decode())
        assert exc.code == 503
        assert "RustBridge runtime required" in body["error"]


def test_pq_hybrid_sign_does_not_return_hash_fallback(tmp_path):
    cfg = Config()
    cfg.db_path = str(tmp_path / "pq.db")
    cfg.http_port = _free_port()
    cfg.rate_limit_rpm = 0
    db = Database(cfg.db_path, synchronous="NORMAL")
    db.initialize()
    RESTHandler.config = cfg
    RESTHandler.db = db
    RESTHandler.blockchain = None
    RESTHandler.mempool = None
    RESTHandler.pq_manager = object()
    configure_rate_limiter(cfg)
    server = ThreadedHTTPServer(("127.0.0.1", cfg.http_port), RESTHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    try:
        try:
            _post(
                f"http://127.0.0.1:{cfg.http_port}/pq/hybrid-sign",
                {"message": "hello", "private_key": "k"},
            )
            assert False, "PQ hybrid-sign should fail closed without real signer"
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode())
            assert exc.code == 501
            assert "hybrid_sign not available" in body["error"]
    finally:
        server.shutdown()
        db.close()


def test_smart_account_authenticate_does_not_auth_by_existence(tmp_path):
    class _LookupOnlySmartAccounts:
        def get_account(self, _identifier):
            return object()

    cfg = Config()
    cfg.db_path = str(tmp_path / "smart.db")
    cfg.http_port = _free_port()
    cfg.rate_limit_rpm = 0
    db = Database(cfg.db_path, synchronous="NORMAL")
    db.initialize()
    RESTHandler.config = cfg
    RESTHandler.db = db
    RESTHandler.blockchain = None
    RESTHandler.mempool = None
    RESTHandler.smart_accounts = _LookupOnlySmartAccounts()
    configure_rate_limiter(cfg)
    server = ThreadedHTTPServer(("127.0.0.1", cfg.http_port), RESTHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    try:
        status, raw = _post(
            f"http://127.0.0.1:{cfg.http_port}/smart-account/authenticate",
            {
                "account_address": "0x" + "1" * 40,
                "credential": "anything",
                "auth_method": "private_key",
            },
        )
        body = json.loads(raw)
        assert status == 200
        assert body["authenticated"] is False
        assert body["error"] == "not supported"
    finally:
        server.shutdown()
        db.close()


def test_sync_status_real(api_server):
    base, _ = api_server
    status, body = _get(f"{base}/sync/status")
    data = json.loads(body)
    assert status == 200
    assert data["enabled"] is True
    assert "local_height" in data
    assert data["solo_mode"] is True


def test_wallet_status(api_server):
    base, _ = api_server
    status, body = _get(f"{base}/wallet/status")
    data = json.loads(body)
    assert status == 200
    assert "signing_enabled" in data
    assert "miner_address" in data


def test_openapi_spec(api_server):
    base, _ = api_server
    status, body = _get(f"{base}/openapi.json")
    data = json.loads(body)
    assert status == 200
    assert data["openapi"] == "3.0.3"
    assert "/peers" in data["paths"]
    assert "/bridge" in data["paths"]


def test_tx_send_alias(api_server, industrial_config):
    base, cfg = api_server
    db = Database(cfg.db_path, synchronous="NORMAL")
    sender = "0x" + "a" * 40
    recipient = "0x" + "b" * 40
    db.set_balance(sender, 100.0)
    body = {"from": sender, "to": recipient, "value": 1.0, "nonce": 0}
    status, raw = _post(f"{base}/tx/send", body)
    data = json.loads(raw)
    assert status == 200
    assert data["status"] == "pending"
    assert len(data["tx_hash"]) == 64
