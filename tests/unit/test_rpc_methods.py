#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests: JSON-RPC eth_* / net_* methods."""

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
from api.http import create_rpc_server, JSONRPCHandler
from storage.database import Database
from kernel.event_bus import EventBus
from core.blockchain import Blockchain
from blockchain.mempool import Mempool


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def rpc_env(tmp_path):
    cfg = Config()
    cfg.db_path = str(tmp_path / "rpc.db")
    cfg.rpc_port = 28545
    cfg.http_port = 28080
    cfg.mining_enabled = True
    cfg.chain_id = 77777
    db = Database(cfg.db_path, synchronous="NORMAL")
    db.initialize()
    bus = EventBus()
    bc = Blockchain(cfg, db, bus)
    mp = Mempool(max_size=100, min_fee=0.001)
    server = create_rpc_server(bc, mp, cfg, p2p=None, wallet=None, sync_engine=None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.25)
    url = f"http://127.0.0.1:{cfg.rpc_port}"
    yield url, bc, mp, cfg
    server.shutdown()


def _rpc(url: str, method: str, params=None):
    payload = {"jsonrpc": "2.0", "method": method, "params": params or [], "id": 1}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read().decode())
    assert "error" not in body, body.get("error")
    return body["result"]


def test_rpc_mining_syncing_mempool(rpc_env):
    url, bc, mp, cfg = rpc_env
    assert _rpc(url, "eth_mining") is True
    assert _rpc(url, "eth_syncing") is False
    assert _rpc(url, "eth_getMempoolSize") == hex(0)
    assert _rpc(url, "net_peerCount") == hex(0)


def test_rpc_eth_syncing_honest_when_peers_inconsistent(tmp_path):
    """With peers + inconsistent tip, eth_syncing must not return False."""
    from types import SimpleNamespace

    cfg = Config()
    cfg.db_path = str(tmp_path / "rpc_sync.db")
    cfg.rpc_port = _free_port()
    cfg.http_port = _free_port()
    cfg.mining_enabled = False
    cfg.chain_id = 77777
    db = Database(cfg.db_path, synchronous="NORMAL")
    db.initialize()
    bus = EventBus()
    bc = Blockchain(cfg, db, bus)
    mp = Mempool(max_size=100, min_fee=0.001)
    p2p = SimpleNamespace(
        _state_consistent=False,
        peer_count=lambda: 2,
        get_peers_info=lambda: [{"height": 1}, {"height": 1}],
    )
    sync_engine = SimpleNamespace(
        get_status=lambda: {
            "syncing": False,
            "behind": 0,
            "local_height": bc.get_height(),
            "best_peer_height": bc.get_height(),
            "peers": 2,
            "state_consistent": False,
            "wire_probe_ok": False,
            "wire_probe_probed": True,
        }
    )
    server = create_rpc_server(bc, mp, cfg, p2p=p2p, wallet=None, sync_engine=sync_engine)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.25)
    try:
        url = f"http://127.0.0.1:{cfg.rpc_port}"
        result = _rpc(url, "eth_syncing")
        assert result is not False
        assert isinstance(result, dict)
        assert "currentBlock" in result
    finally:
        server.shutdown()


def test_rpc_eth_syncing_honest_when_peers_never_probed(tmp_path):
    """Peers present but wire probe never ran — eth_syncing must not return False."""
    from types import SimpleNamespace

    cfg = Config()
    cfg.db_path = str(tmp_path / "rpc_sync_never.db")
    cfg.rpc_port = _free_port()
    cfg.http_port = _free_port()
    cfg.mining_enabled = False
    cfg.chain_id = 77777
    db = Database(cfg.db_path, synchronous="NORMAL")
    db.initialize()
    bus = EventBus()
    bc = Blockchain(cfg, db, bus)
    mp = Mempool(max_size=100, min_fee=0.001)
    p2p = SimpleNamespace(
        _state_consistent=True,
        peer_count=lambda: 2,
        get_peers_info=lambda: [{"height": 1}, {"height": 1}],
    )
    sync_engine = SimpleNamespace(
        get_status=lambda: {
            "syncing": False,
            "behind": 0,
            "local_height": bc.get_height(),
            "best_peer_height": bc.get_height(),
            "peers": 2,
            "state_consistent": True,
            "wire_probe_ok": False,
            "wire_probe_probed": False,
        }
    )
    server = create_rpc_server(bc, mp, cfg, p2p=p2p, wallet=None, sync_engine=sync_engine)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.25)
    try:
        url = f"http://127.0.0.1:{cfg.rpc_port}"
        result = _rpc(url, "eth_syncing")
        assert result is not False
        assert isinstance(result, dict)
        assert "currentBlock" in result
    finally:
        server.shutdown()


def test_rpc_block_tx_count(rpc_env):
    url, bc, mp, cfg = rpc_env
    height = bc.get_height()
    count = _rpc(url, "eth_getBlockTransactionCountByNumber", [hex(height)])
    blk = bc.get_block(height)
    expected = len(blk.get("transactions", [])) if blk else 0
    assert int(count, 16) == expected


def test_rpc_rejects_fake_raw_tx(rpc_env):
    url, _, __, ___ = rpc_env
    payload = {"jsonrpc": "2.0", "method": "eth_sendRawTransaction", "params": ["0xdeadbeef"], "id": 1}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read().decode())
    assert "error" in body


def test_rpc_eth_get_logs_with_filter(rpc_env):
    url, bc, mp, cfg = rpc_env
    contract = "0x" + "de" * 20
    bc.db.save_evm_logs(
        contract,
        [{"topics": ["0xabc"], "data": "c0ffee"}],
        block_height=bc.get_height(),
        tx_hash="0xfeed",
    )
    logs = _rpc(url, "eth_getLogs", [{"fromBlock": "0x0", "toBlock": "latest", "address": contract}])
    assert len(logs) == 1
    assert logs[0]["address"].lower() == contract.lower()
    assert logs[0]["data"] in ("0xc0ffee", "c0ffee")
    assert logs[0]["topics"] == ["0xabc"]


def test_rpc_wallet_compat_methods(rpc_env):
    url, bc, mp, cfg = rpc_env
    assert _rpc(url, "eth_chainId") == hex(cfg.chain_id)
    assert _rpc(url, "eth_protocolVersion") == hex(65)
    assert _rpc(url, "eth_hashrate") == "0x0"
    assert _rpc(url, "eth_getUncleCountByBlockNumber", ["latest"]) == "0x0"
    assert _rpc(url, "eth_getLogs", [{}]) == []
    gas = int(_rpc(url, "eth_estimateGas", [{"to": "0x" + "ab" * 20}]), 16)
    assert gas >= 21_000
    fee_hist = _rpc(url, "eth_feeHistory", [hex(2), "latest", []])
    assert "baseFeePerGas" in fee_hist
    assert "gasUsedRatio" in fee_hist
    n = len(fee_hist["baseFeePerGas"])
    assert n == len(fee_hist["gasUsedRatio"]) == len(fee_hist["reward"])
    assert 1 <= n <= 2
    assert all(
        isinstance(x, (int, float)) and 0.0 <= float(x) <= 1.0
        for x in fee_hist["gasUsedRatio"]
    )
    blk = _rpc(url, "eth_getBlockByNumber", ["latest", False])
    assert blk is not None
    for field in ("stateRoot", "gasLimit", "transactionsRoot", "miner"):
        assert field in blk
    assert _rpc(url, "eth_getStorageAt", ["0x" + "00" * 20, "0x0"]) == "0x0"


def test_prod_rpc_requires_key_and_restricts_cors(tmp_path):
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.db_path = str(tmp_path / "rpc-prod.db")
    cfg.rpc_port = _free_port()
    cfg.http_port = _free_port()
    cfg.rpc_api_key_required = True
    cfg.rpc_api_keys = ["rpc-prod-key"]
    cfg.cors_origins = ["https://explorer.example.com"]

    db = Database(cfg.db_path, synchronous="NORMAL")
    db.initialize()
    bc = Blockchain(cfg, db, EventBus())
    mp = Mempool(max_size=100, min_fee=0.001)
    server = create_rpc_server(bc, mp, cfg, p2p=None, wallet=None, sync_engine=None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)
    url = f"http://127.0.0.1:{cfg.rpc_port}"

    def _urlopen_retry(request, timeout=5):
        last_exc = None
        for _ in range(4):
            try:
                return urllib.request.urlopen(request, timeout=timeout)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, TimeoutError) as exc:
                last_exc = exc
                time.sleep(0.15)
        raise last_exc

    try:
        payload = {"jsonrpc": "2.0", "method": "eth_chainId", "params": [], "id": 1}
        data = json.dumps(payload).encode()

        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Origin": "https://explorer.example.com",
            },
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _urlopen_retry(req)
        assert exc_info.value.code == 401
        assert exc_info.value.headers["Access-Control-Allow-Origin"] == "https://explorer.example.com"

        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Origin": "https://explorer.example.com",
                "X-API-Key": "rpc-prod-key",
            },
            method="POST",
        )
        with _urlopen_retry(req) as resp:
            body = json.loads(resp.read().decode())
            assert resp.headers["Access-Control-Allow-Origin"] == "https://explorer.example.com"
        assert body["result"] == hex(cfg.chain_id)

        get_req = urllib.request.Request(
            url,
            headers={"Origin": "https://explorer.example.com"},
            method="GET",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _urlopen_retry(get_req)
        assert exc_info.value.code == 405
    finally:
        server.shutdown()
        db.close()
