#!/usr/bin/env python3
"""Devnet pool spend and live allocation API."""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from runtime.config import Config
from runtime.pool_locks import PoolLockManager
from runtime.tokenomics import build_allocations
from storage.database import Database
from core.blockchain import Blockchain
from blockchain.mempool import Mempool
from api.http import RESTHandler, ThreadedHTTPServer, configure_rate_limiter
from consensus.validator_registry import ValidatorRegistry


def _post(url: str, data: dict, timeout: float = 5):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


def _get(url: str, timeout: float = 5):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())


def _start_server(bc, mp, db, cfg, pool_locks=None, validator_registry=None):
    RESTHandler.blockchain = bc
    RESTHandler.mempool = mp
    RESTHandler.db = db
    RESTHandler.config = cfg
    RESTHandler.wallet = None
    RESTHandler.pool_locks = pool_locks
    RESTHandler.validator_registry = validator_registry
    configure_rate_limiter(cfg)
    port = 18083
    server = ThreadedHTTPServer(("127.0.0.1", port), RESTHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.2)
    return f"http://127.0.0.1:{port}", server


def test_pool_spend_from_unlocked_ecosystem():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    miner = "0xminer000000000000000000000000000001"
    recipient = "0xrecipient000000000000000000000001"
    cfg = Config()
    cfg.db_path = path
    cfg.rate_limit_rpm = 0
    cfg.deployment_mode = "dev"
    cfg.miner_address = miner
    cfg.founder_address = miner
    db = Database(path)
    db.initialize()
    bc = Blockchain(cfg, db)
    pl = PoolLockManager(db, miner)
    vr = ValidatorRegistry()
    vr.register_validator(miner, 1000)
    pl.dao_vote("ecosystem", miner, validator_registry=vr)
    mp = Mempool(cfg, db)
    base, server = _start_server(bc, mp, db, cfg, pool_locks=pl, validator_registry=vr)
    eco_addr = next(p.address_key for p in build_allocations(miner) if p.id == "ecosystem")
    try:
        st, body = _post(
            f"{base}/devnet/pool-spend",
            {"pool_id": "ecosystem", "to": recipient, "amount": 500.0},
        )
        assert st == 200
        assert body["success"] is True
        assert body["amount"] == 500.0
        assert db.get_balance(recipient) == 500.0
        assert db.get_balance(eco_addr) == 22_100_000.0 - 500.0
    finally:
        server.shutdown()
        db.close()
        os.remove(path)


def test_allocation_includes_live_pool_status():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    miner = "0xminer000000000000000000000000000001"
    cfg = Config()
    cfg.db_path = path
    cfg.rate_limit_rpm = 0
    cfg.miner_address = miner
    db = Database(path)
    db.initialize()
    bc = Blockchain(cfg, db)
    pl = PoolLockManager(db, miner)
    vr = ValidatorRegistry()
    vr.register_validator(miner, 1000)
    pl.dao_vote("treasury", miner, validator_registry=vr)
    mp = Mempool(cfg, db)
    base, server = _start_server(bc, mp, db, cfg, pool_locks=pl, validator_registry=vr)
    try:
        st, body = _get(f"{base}/allocation")
        assert st == 200
        treasury = next(a for a in body["allocations"] if a["id"] == "treasury")
        assert treasury["dao_unlocked"] is True
        assert treasury["live_spendable"] == 22_100_000.0
    finally:
        server.shutdown()
        db.close()
        os.remove(path)
