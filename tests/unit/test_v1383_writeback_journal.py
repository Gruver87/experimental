#!/usr/bin/env python3
"""v1.3.83: inline value CALL/CREATE → pending_writeback_ops (satoshi journal)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crypto import native
from evm_interpreter import EVM, EVMContext
from execution.evm_adapter import EVMAdapter
from execution.evm_host_bridge import make_evm_runtime_bridge
from runtime.config import Config


CALLER = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CALLEE = "0x00000000000000000000000000000000000000bb"
DEPLOYER = CALLER

# 1 satoshi = 10**12 wei (evm_writeback.wei_to_satoshi)
ONE_SAT_WEI = 10**12


def _call_value_bytecode(to_addr: str, value: int) -> bytes:
    """PUSH value must fit in one byte for this helper (tests use small wei or 0)."""
    assert 0 <= value <= 255
    addr_hex = to_addr.replace("0x", "").zfill(40)
    return bytes(
        [
            0x60,
            0x00,
            0x60,
            0x00,
            0x60,
            0x00,
            0x60,
            0x00,
            0x60,
            value & 0xFF,
            0x73,
            *bytes.fromhex(addr_hex),
            0x5A,
            0xF1,
            0x50,
            0x00,
        ]
    )


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_value_call_enqueues_pending_writeback_ops():
    child_code = bytes([0x00])
    hook_calls = {"n": 0}

    def hook(*a, **k):
        hook_calls["n"] += 1
        return {"success": False, "reverted": True, "return_data": b"", "gas_used": 0}

    bytecode = _call_value_bytecode(CALLEE, 5)
    storage: dict = {}
    ctx = EVMContext(contract_call=hook, address=CALLER)
    host_ctx = native.evm_host_context_from_evm(ctx)
    host_ctx["bridge_state"] = {
        "codes": {CALLEE: child_code},
        "storages": {CALLEE: {}},
        "balances": {CALLER: 100, CALLEE: 1},
    }
    evm = EVM(gas_limit=1_000_000, context=ctx)
    evm.storage = storage
    bridge = make_evm_runtime_bridge(evm)
    out = native.evm_run_nested_host_frame(
        bytecode, 1_000_000, b"", host_ctx, storage, bridge
    )
    assert not out.get("reverted"), out
    assert hook_calls["n"] == 0
    bs = host_ctx["bridge_state"]
    assert bs.get("native_inline_writeback_value") is True
    assert int(bs.get("native_inline_writeback_ops") or 0) == 1
    ops = list(bs.get("pending_writeback_ops") or [])
    assert len(ops) == 1
    op = dict(ops[0])
    assert op["op"] == "transfer_value"
    assert op["from"].lower() == CALLER.lower()
    assert op["to"].lower() == CALLEE.lower()
    assert int(op["value_wei"]) == 5
    assert op.get("native_inline_writeback") is True


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_reverted_value_call_does_not_enqueue_ops():
    # Child REVERT (0xFD)
    child_code = bytes([0x60, 0x00, 0x60, 0x00, 0xFD])
    hook_calls = {"n": 0}

    def hook(*a, **k):
        hook_calls["n"] += 1
        return {"success": True, "reverted": False, "return_data": b"", "gas_used": 1}

    bytecode = _call_value_bytecode(CALLEE, 5)
    storage: dict = {}
    ctx = EVMContext(contract_call=hook, address=CALLER)
    host_ctx = native.evm_host_context_from_evm(ctx)
    host_ctx["bridge_state"] = {
        "codes": {CALLEE: child_code},
        "storages": {CALLEE: {}},
        "balances": {CALLER: 100, CALLEE: 0},
    }
    evm = EVM(gas_limit=1_000_000, context=ctx)
    evm.storage = storage
    bridge = make_evm_runtime_bridge(evm)
    out = native.evm_run_nested_host_frame(
        bytecode, 1_000_000, b"", host_ctx, storage, bridge
    )
    assert not out.get("reverted"), out  # outer succeeds; CALL pushes 0
    assert hook_calls["n"] == 0
    bs = host_ctx["bridge_state"]
    assert not bs.get("pending_writeback_ops")
    assert int(bs["balances"][CALLER]) == 100
    assert int(bs["balances"][CALLEE]) == 0


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_adapter_flushes_inline_ops_into_journal():
    class MemDB:
        def get_account(self, addr):
            return None

        def get_chain_tip(self):
            return 0

    ad = EVMAdapter(MemDB(), Config())
    ad.begin_writeback_journal()
    host_ctx = {
        "bridge_state": {
            "pending_writeback_ops": [
                {
                    "op": "transfer_value",
                    "from": CALLER,
                    "to": CALLEE,
                    "value_wei": ONE_SAT_WEI,
                    "native_inline_writeback": True,
                }
            ]
        }
    }
    ops = ad._take_bridge_pending_writeback(host_ctx)
    assert len(ops) == 1
    assert "pending_writeback_ops" not in host_ctx["bridge_state"]
    ad._apply_nested_writeback_ops(ops)
    assert len(ad._writeback_journal) == 1
    assert ad._writeback_journal[0]["op"] == "transfer_value"
    assert int(ad._writeback_journal[0]["value_wei"]) == ONE_SAT_WEI


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_create_value_enqueues_writeback_op():
    hook_calls = {"n": 0}

    def create_hook(*a, **k):
        hook_calls["n"] += 1
        return {"success": False, "reverted": True, "gas_used": 0}

    # empty init CREATE value=5
    bytecode = bytes([0x60, 0x05, 0x60, 0x00, 0x60, 0x00, 0xF0, 0x00])
    storage: dict = {}
    ctx = EVMContext(contract_create=create_hook, address=DEPLOYER, block_number=1)
    host_ctx = native.evm_host_context_from_evm(ctx)
    host_ctx["bridge_state"] = {
        "codes": {},
        "storages": {},
        "balances": {DEPLOYER: 50},
    }
    evm = EVM(gas_limit=1_000_000, context=ctx)
    evm.storage = storage
    bridge = make_evm_runtime_bridge(evm)
    out = native.evm_run_nested_host_frame(
        bytecode, 1_000_000, b"", host_ctx, storage, bridge
    )
    assert not out.get("reverted"), out
    assert hook_calls["n"] == 0
    bs = host_ctx["bridge_state"]
    assert bs.get("native_inline_writeback_value") is True
    assert bs.get("native_inline_writeback_create") is True
    ops = [dict(o) for o in (bs.get("pending_writeback_ops") or [])]
    assert [o["op"] for o in ops] == ["save_account", "transfer_value"]
    assert ops[0]["address"].lower() == bs["native_inline_create_address"].lower()
    assert ops[0]["code"] == ""
    assert int(ops[0]["balance"]) == 0
    assert int(ops[1]["value_wei"]) == 5
    assert ops[1]["from"].lower() == DEPLOYER.lower()
    assert ops[1]["to"].lower() == bs["native_inline_create_address"].lower()


def test_needles_v1383():
    rust = (ROOT / "native" / "abs_native" / "src" / "evm_pure_runner.rs").read_text(
        encoding="utf-8"
    )
    assert "push_pending_writeback_transfer" in rust
    assert "pending_writeback_ops" in rust
    assert "native_inline_writeback_value" in rust
    assert "v1.3.83" in rust
    adapter = (ROOT / "execution" / "evm_adapter.py").read_text(encoding="utf-8")
    assert "_take_bridge_pending_writeback" in adapter
    assert "native_inline_writeback" in adapter
    notes = (ROOT / "RELEASE_NOTES_v1.3.83.md").read_text(encoding="utf-8")
    assert "1.3.83-industrial" in notes


def test_take_bridge_pending_writeback_does_not_silent_drop():
    class MemDB:
        def get_account(self, addr):
            return None

        def get_chain_tip(self):
            return 0

    ad = EVMAdapter(MemDB(), Config())
    host_ctx = {"bridge_state": {"pending_writeback_ops": [object()]}}
    with pytest.raises(RuntimeError, match="bridge_pending_writeback_failed"):
        ad._take_bridge_pending_writeback(host_ctx)
