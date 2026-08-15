#!/usr/bin/env python3
"""STATICCALL write-refuse on the native inline apply-path.

Child SSTORE/LOG must not commit; STATICCALL returns 0; parent continues.
Read-only STATICCALL (SLOAD/RETURN) still succeeds.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crypto import native
from evm_interpreter import EVM, EVMContext
from execution.evm_host_bridge import make_evm_runtime_bridge

CALLEE = "0x00000000000000000000000000000000000000bb"


def _hook_must_not_run(_target, _calldata, _value, _gas, _delegate, static=False, callcode=False):
    raise AssertionError("nested call must stay on the native inline path")


def _sstore_stop() -> bytes:
    """PUSH1 99; PUSH1 1; SSTORE; STOP."""
    return bytes([0x60, 0x63, 0x60, 0x01, 0x55, 0x00])


def _return_word(word: int) -> bytes:
    return bytes([0x60, word & 0xFF, 0x60, 0x00, 0x52, 0x60, 0x20, 0x60, 0x00, 0xF3])


def _log0_stop() -> bytes:
    """PUSH1 0; PUSH1 0; LOG0; STOP."""
    return bytes([0x60, 0x00, 0x60, 0x00, 0xA0, 0x00])


def _call_op(callee: str, op: int, tail: bytes) -> bytes:
    addr_hex = callee.replace("0x", "").zfill(40)
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
            *(() if op == 0xFA else (0x60, 0x00)),
            0x73,
            *bytes.fromhex(addr_hex),
            0x5A,
            op,
        ]
    ) + tail


def _run(parent: bytes, child: bytes) -> tuple[dict, dict]:
    storage: dict = {}
    ctx = EVMContext(contract_call=_hook_must_not_run)
    host_ctx = native.evm_host_context_from_evm(ctx)
    storages = {CALLEE: {}}
    host_ctx["bridge_state"] = {"codes": {CALLEE: child}, "storages": storages}
    evm = EVM(gas_limit=1_000_000, context=ctx)
    evm.storage = storage
    bridge = make_evm_runtime_bridge(evm)
    out = native.evm_run_nested_host_frame(
        parent, 1_000_000, b"", host_ctx, storage, bridge
    )
    return out, storages[CALLEE]


def _slot1(st: dict) -> int:
    return int(st.get(1, st.get("1", 0)) or 0)


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_call_sstore_persists_child_storage() -> None:
    parent = _call_op(CALLEE, 0xF1, bytes([0x00]))
    out, child_st = _run(parent, _sstore_stop())
    assert not out.get("reverted")
    stack = [int(x) for x in (out.get("stack") or [])]
    assert stack[-1] == 1
    assert _slot1(child_st) == 99


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_staticcall_sstore_refuses_and_parent_continues() -> None:
    parent = _call_op(CALLEE, 0xFA, bytes([0x00]))
    out, child_st = _run(parent, _sstore_stop())
    assert not out.get("reverted"), "parent must continue after STATICCALL write-refuse"
    stack = [int(x) for x in (out.get("stack") or [])]
    assert stack[-1] == 0
    assert _slot1(child_st) == 0


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_staticcall_return_still_succeeds() -> None:
    parent = _call_op(
        CALLEE,
        0xFA,
        bytes([0x50, 0x60, 0x20, 0x60, 0x00, 0x60, 0x00, 0x3E, 0x60, 0x00, 0x51, 0x00]),
    )
    out, _child_st = _run(parent, _return_word(0x2A))
    assert not out.get("reverted")
    stack = [int(x) for x in (out.get("stack") or [])]
    assert stack[-1] == 0x2A


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_staticcall_log_refuses() -> None:
    parent = _call_op(CALLEE, 0xFA, bytes([0x00]))
    out, _child_st = _run(parent, _log0_stop())
    assert not out.get("reverted")
    stack = [int(x) for x in (out.get("stack") or [])]
    assert stack[-1] == 0
    logs = list(out.get("logs") or [])
    assert logs == []
