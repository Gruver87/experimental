#!/usr/bin/env python3
"""Production bridge chain policy."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from bridge.abs_bridge import RustBridge
from runtime.config import Config
from storage.database import Database
import tempfile


def _prod_bridge():
    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "br.db"))
    db.initialize()
    cfg = Config(db_path=db.db_path)
    cfg.deployment_mode = "prod"
    cfg.bridge_enabled = False
    cfg.bridge_mode = "rust"
    # Chain-policy unit test: path must exist so RustBridge constructs; not a live CLI.
    cfg.rust_bridge_path = __file__
    return RustBridge(cfg, db)


def test_prod_rejects_solana_chain():
    bridge = _prod_bridge()
    out = bridge.lock_and_bridge(
        "0x" + "a" * 40,
        "solana",
        "So11111111111111111111111111111111111111112",
        1.0,
    )
    assert "error" in out
    assert "solana" in out["error"].lower()


def test_prod_accepts_ethereum_chain_label():
    bridge = _prod_bridge()
    out = bridge.lock_and_bridge(
        "0x" + "b" * 40,
        "ethereum",
        "0x" + "c" * 40,
        1.0,
    )
    # May fail on balance or rust binary — chain validation must pass first
    if "error" in out:
        assert "Unsupported chain" not in out["error"]
        assert "solana" not in out["error"].lower()
