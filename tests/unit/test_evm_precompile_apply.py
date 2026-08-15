#!/usr/bin/env python3
"""Apply-path nested CALL/STATICCALL into precompiles 0x01–0x09.

eth_call already hit try_precompile. A contract CALL to 0x04 used to look like
empty code and revert. This is the apply-path gate, not a geth gas audit.
"""

from __future__ import annotations

import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from evm_interpreter import EVM, EVMContext
from execution.evm_adapter import EVMAdapter
from runtime.config import Config
from storage.database import Database


IDENTITY = "0x0000000000000000000000000000000000000004"
SHA256 = "0x0000000000000000000000000000000000000002"


@pytest.fixture
def evm_db(tmp_path):
    cfg = Config()
    cfg.db_path = str(tmp_path / "evm.db")
    db = Database(cfg.db_path, synchronous="NORMAL")
    db.initialize()
    yield EVMAdapter(db, cfg), db
    db.close()


def test_nested_call_hook_identity_precompile(evm_db) -> None:
    adapter, _db = evm_db
    payload = b"abs-apply"
    caller_ctx = EVMContext(address="0x" + "11" * 20)
    out = adapter._contract_call_hook(
        IDENTITY, payload, 0, 100_000, False, False, caller_ctx
    )
    assert out.get("success") is True
    assert out.get("reverted") is False
    assert out.get("return_data") == payload
    assert int(out.get("gas_used") or 0) == 15 + 3


def test_call_contract_identity_is_not_missing_code(evm_db) -> None:
    adapter, _db = evm_db
    payload = b"hello-apply"
    r = adapter.call_contract("0x" + "22" * 20, IDENTITY, payload.hex(), 0)
    assert r.success is True
    assert r.return_value == payload
    assert r.error == ""


def test_execute_bytecode_call_identity_via_adapter_hook(evm_db) -> None:
    """Native/Python CALL to 0x04 must copy identity bytes into returndata."""
    adapter, _db = evm_db
    caller_ctx = EVMContext(address="0x" + "33" * 20)
    caller_ctx.contract_call = (
        lambda t, d, v, g, delg, st=False, cc=False: adapter._contract_call_hook(
            t, d, v, g, delg, st, caller_ctx, callcode=cc
        )
    )
    # MSTORE8 'h','i' then CALL identity(args=2) then STOP. Return buffer = "hi".
    addr = bytes.fromhex(IDENTITY.replace("0x", ""))
    bytecode = bytes(
        [
            0x60, 0x68, 0x60, 0x00, 0x53,
            0x60, 0x69, 0x60, 0x01, 0x53,
            0x60, 0x20,
            0x60, 0x20,
            0x60, 0x02,
            0x60, 0x00,
            0x60, 0x00,
            0x73, *addr,
            0x5A,
            0xF1,
            0x00,
        ]
    )
    evm = EVM(gas_limit=200_000, context=caller_ctx)
    out = evm.execute_bytecode(bytecode)
    assert not out.get("reverted")
    stack = [int(x) for x in (out.get("stack") or [])]
    assert stack[-1] == 1
    assert bytes(out.get("return_data") or b"") == b"hi"


def test_staticcall_sha256_via_adapter_hook(evm_db) -> None:
    adapter, _db = evm_db
    payload = b"abc"
    caller_ctx = EVMContext(address="0x" + "44" * 20)
    out = adapter._contract_call_hook(
        SHA256, payload, 0, 100_000, False, True, caller_ctx
    )
    assert out.get("success") is True
    assert out.get("return_data") == hashlib.sha256(payload).digest()
