#!/usr/bin/env python3
"""Nested CALL into an empty account (EOA) succeeds on the apply-path.

Yellow paper: no code → success, empty returndata, value still transfers.
Absolute used to revert missing-code CALLs, which broke contract withdrawals.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from evm_interpreter import EVM, EVMContext
from execution.evm_adapter import EVMAdapter
from runtime.config import Config
from storage.database import Database


EOA = "0x" + "99" * 20
CALLER = "0x" + "11" * 20


def _adapter(tmp_path):
    cfg = Config()
    cfg.db_path = str(tmp_path / "evm.db")
    db = Database(cfg.db_path, synchronous="NORMAL")
    db.initialize()
    return EVMAdapter(db, cfg), db


def test_nested_call_to_eoa_succeeds_empty_return(tmp_path) -> None:
    adapter, db = _adapter(tmp_path)
    try:
        ctx = EVMContext(address=CALLER)
        out = adapter._contract_call_hook(
            EOA, b"ignored", 0, 100_000, False, False, ctx
        )
        assert out.get("success") is True
        assert out.get("reverted") is False
        assert out.get("return_data") == b""
    finally:
        db.close()


def test_nested_staticcall_to_eoa_succeeds(tmp_path) -> None:
    adapter, db = _adapter(tmp_path)
    try:
        ctx = EVMContext(address=CALLER)
        out = adapter._contract_call_hook(
            EOA, b"", 0, 100_000, False, True, ctx
        )
        assert out.get("success") is True
        assert out.get("return_data") == b""
        assert db.get_account(EOA) is None
    finally:
        db.close()


def test_nested_call_to_eoa_transfers_value(tmp_path) -> None:
    adapter, db = _adapter(tmp_path)
    try:
        db.save_account(CALLER, balance=5.0, nonce=0, code="6000", storage="{}")
        ctx = EVMContext(address=CALLER)
        out = adapter._contract_call_hook(
            EOA, b"", 10**18, 100_000, False, False, ctx
        )
        assert out.get("success") is True
        assert db.get_balance(CALLER) == 4.0
        assert db.get_balance(EOA) == 1.0
    finally:
        db.close()


def test_execute_bytecode_call_eoa_via_adapter_hook(tmp_path) -> None:
    adapter, db = _adapter(tmp_path)
    try:
        caller_ctx = EVMContext(address=CALLER)
        caller_ctx.contract_call = (
            lambda t, d, v, g, delg, st=False, cc=False: adapter._contract_call_hook(
                t, d, v, g, delg, st, caller_ctx, callcode=cc
            )
        )
        addr = bytes.fromhex(EOA.replace("0x", ""))
        bytecode = bytes(
            [
                0x60, 0x00,
                0x60, 0x00,
                0x60, 0x00,
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
        assert bytes(out.get("return_data") or b"") == b""
    finally:
        db.close()
