#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EVM interpreter and adapter integration tests."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from evm_interpreter import EVM, EVMContext
from execution.evm_adapter import EVMAdapter
from runtime.config import Config
from storage.database import Database


@pytest.fixture
def evm_db(tmp_path):
    cfg = Config()
    cfg.db_path = str(tmp_path / "evm.db")
    db = Database(cfg.db_path, synchronous="NORMAL")
    db.initialize()
    return EVMAdapter(db, cfg), db


def test_evm_caller_opcode():
    ctx = EVMContext(caller="0x00000000000000000000000000000000000000ab")
    evm = EVM(context=ctx)
    result = evm.execute_bytecode(bytes([0x33, 0x00]))
    assert result["stack"][-1] == ctx.addr_int(ctx.caller)


def test_evm_calldata_load():
    ctx = EVMContext(calldata=bytes.fromhex("000000000000000000000000000000000000000000000000000000000000002a"))
    evm = EVM(context=ctx)
    # PUSH0 CALLDATALOAD (approx: PUSH1 0, CALLDATALOAD)
    result = evm.execute_bytecode(bytes([0x60, 0x00, 0x35, 0x00]))
    assert result["stack"][-1] == 42


def test_adapter_deploy_and_storage(evm_db):
    adapter, db = evm_db
    deployer = "0xdeployer000000000000000000000000000001"
    db.save_account(deployer, balance=100.0, nonce=0)
    # PUSH1 7, PUSH1 0, SSTORE, STOP
    bytecode = "600760005500"
    res = adapter.deploy_contract(deployer, bytecode, salt="test")
    assert res.success, res.error
    addr = res.return_value
    info = adapter.get_contract_info(addr)
    assert info["is_contract"]
    acct = db.get_account(addr)
    storage = __import__("json").loads(acct.get("storage") or "{}")
    assert storage.get("0") == 7 or storage.get(0) == 7


def test_pq_sign_verify_roundtrip():
    """PQ Dilithium has no NIST backend — fail-closed, not a demo roundtrip."""
    from features.postquantum import PostQuantumManager, PQAlgorithm
    import pytest

    pqm = PostQuantumManager()
    with pytest.raises(NotImplementedError):
        pqm.generate_keypair(PQAlgorithm.DILITHIUM)
