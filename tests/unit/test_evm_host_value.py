#!/usr/bin/env python3
"""Host apply-path value: one debit, one credit, no clamp mint.

deploy_contract used to save_account(balance=value) and then update_balance(+value).
call_contract used clamp update_balance when the caller could not cover.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from execution.evm_adapter import EVMAdapter
from runtime.config import Config
from storage.database import Database


DEPLOYER = "0x" + "11" * 20
CALLER = "0x" + "22" * 20
STOP = "00"


def _adapter(tmp_path):
    cfg = Config()
    cfg.db_path = str(tmp_path / "evm.db")
    db = Database(cfg.db_path, synchronous="NORMAL")
    db.initialize()
    return EVMAdapter(db, cfg), db


def test_deploy_with_value_endows_once(tmp_path) -> None:
    adapter, db = _adapter(tmp_path)
    try:
        db.save_account(DEPLOYER, balance=5.0, nonce=0, code="", storage="{}")
        r = adapter.deploy_contract(DEPLOYER, STOP, value=1.0, salt="v1")
        assert r.success is True
        addr = str(r.return_value)
        assert db.get_balance_satoshi(DEPLOYER) == 4_000_000
        assert db.get_balance_satoshi(addr) == 1_000_000
    finally:
        db.close()


def test_deploy_insufficient_value_does_not_mint(tmp_path) -> None:
    adapter, db = _adapter(tmp_path)
    try:
        db.save_account(DEPLOYER, balance=0.0, nonce=0, code="", storage="{}")
        r = adapter.deploy_contract(DEPLOYER, STOP, value=1.0, salt="v0")
        assert r.success is False
        assert r.error == "insufficient_deploy_value"
        assert db.get_balance_satoshi(DEPLOYER) == 0
    finally:
        db.close()


def test_call_contract_value_transfers_once(tmp_path) -> None:
    adapter, db = _adapter(tmp_path)
    try:
        db.save_account(DEPLOYER, balance=5.0, nonce=0, code="", storage="{}")
        deployed = adapter.deploy_contract(DEPLOYER, STOP, value=0.0, salt="c1")
        addr = str(deployed.return_value)
        db.save_account(CALLER, balance=3.0, nonce=0, code="", storage="{}")
        r = adapter.call_contract(CALLER, addr, "", 1.0)
        assert r.success is True
        assert db.get_balance_satoshi(CALLER) == 2_000_000
        assert db.get_balance_satoshi(addr) == 1_000_000
    finally:
        db.close()


def test_call_contract_insufficient_value_does_not_mint(tmp_path) -> None:
    adapter, db = _adapter(tmp_path)
    try:
        db.save_account(DEPLOYER, balance=1.0, nonce=0, code="", storage="{}")
        deployed = adapter.deploy_contract(DEPLOYER, STOP, value=0.0, salt="c2")
        addr = str(deployed.return_value)
        before = db.get_balance_satoshi(addr)
        r = adapter.call_contract(CALLER, addr, "", 1.0)
        assert r.success is False
        assert r.error == "insufficient_call_value"
        assert db.get_balance_satoshi(CALLER) == 0
        assert db.get_balance_satoshi(addr) == before
    finally:
        db.close()
