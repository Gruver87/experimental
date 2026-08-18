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


def test_host_apply_identity_tx_does_not_deploy(evm_db) -> None:
    """Tx to=0x04 with calldata must call the precompile, not CREATE."""
    from core.blockchain import Transaction
    from core.components.state_service import StateService

    adapter, _db = evm_db

    def _must_not_deploy(*_a, **_k):
        raise AssertionError("precompile tx must not deploy")

    adapter.deploy_contract = _must_not_deploy  # type: ignore[method-assign]

    class _Storage:
        def get_account(self, _addr):
            return None

    class _Host:
        def __init__(self) -> None:
            self.evm = adapter
            self.storage = _Storage()
            self.config = adapter.config
            self.bus = None
            self.pool_locks = None

        def _native_apply_fail_closed(self) -> bool:
            return False

    tx = Transaction(
        from_addr="0x" + "11" * 20,
        to_addr=IDENTITY,
        value=0,
        nonce=0,
        gas=100_000,
        data=b"hi".hex(),
    )
    out = StateService(_Host())._run_evm_host_only(tx, 1)
    assert out.get("success") is True
    assert out.get("contract_address") is None


def test_mempool_does_not_treat_precompile_tx_as_deploy() -> None:
    from core.blockchain import Transaction
    from core.components.tx_pipeline import TxPipeline
    from runtime.config import Config

    class _Storage:
        def get_account(self, _addr):
            return None

    pipe = TxPipeline(
        config=Config(),
        storage=_Storage(),
        get_evm=lambda: object(),
    )
    tx = Transaction(
        from_addr="0x" + "11" * 20,
        to_addr=IDENTITY,
        value=0,
        nonce=0,
        gas=100_000,
        data=b"hi".hex(),
    )
    assert pipe._is_evm_deploy_tx(tx) is False


def test_delegatecall_precompile_does_not_wipe_caller_storage(evm_db) -> None:
    """Precompile has no storage; empty writeback must not clobber the caller."""
    import json

    adapter, db = evm_db
    caller = "0x" + "aa" * 20
    db.save_account(
        caller, balance=1.0, nonce=1, code="6000", storage=json.dumps({"1": 99})
    )
    ctx = EVMContext(address=caller)
    out = adapter._contract_call_hook(
        IDENTITY, b"hi", 0, 100_000, True, False, ctx
    )
    assert out.get("success") is True
    assert out.get("return_data") == b"hi"
    row = db.get_account(caller)
    raw = row["storage"] if row else "{}"
    storage = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    assert int(storage.get("1", storage.get(1))) == 99


def test_nested_call_precompile_insufficient_value_does_not_run(evm_db) -> None:
    adapter, db = evm_db
    caller = "0x" + "aa" * 20
    db.save_account(caller, balance=0.0, nonce=0, code="6000", storage="{}")
    ctx = EVMContext(address=caller)
    out = adapter._contract_call_hook(
        IDENTITY, b"hi", 10**18, 100_000, False, False, ctx
    )
    assert out.get("success") is False
    assert out.get("error") == "insufficient_call_value"
    assert out.get("return_data") == b""
    assert db.get_balance_satoshi(IDENTITY) == 0


def test_nested_blake2f_bad_length_burns_forwarded_gas(evm_db) -> None:
    """geth CALL: precompile Run error consumes remaining forwarded gas."""
    adapter, _db = evm_db
    blake = "0x0000000000000000000000000000000000000009"
    ctx = EVMContext(address="0x" + "55" * 20)
    out = adapter._contract_call_hook(blake, b"\x00", 0, 77_000, False, False, ctx)
    assert out.get("success") is False
    assert int(out.get("gas_used") or 0) == 77_000
    assert out.get("error") == "blake2f_bad_length"


def test_call_contract_blake2f_bad_length_burns_gas_limit(evm_db) -> None:
    adapter, _db = evm_db
    blake = "0x0000000000000000000000000000000000000009"
    r = adapter.call_contract("0x" + "22" * 20, blake, "00", 0, gas_limit=50_000)
    assert r.success is False
    assert r.gas_used == 50_000
    assert r.error == "blake2f_bad_length"
