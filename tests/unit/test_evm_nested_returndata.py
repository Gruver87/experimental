#!/usr/bin/env python3
"""Nested CALL return-data: RETURNDATASIZE / RETURNDATACOPY after inline CALL.

Proves the live return buffer is used after a child RETURN/REVERT — not the
segment's inbound snapshot. Apply-path: native host frame (existing runner).
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
    raise AssertionError("nested CALL must stay on the native inline path")


def _return_word_bytecode(word: int) -> bytes:
    """PUSH1 word; PUSH1 0; MSTORE; PUSH1 32; PUSH1 0; RETURN."""
    return bytes([0x60, word & 0xFF, 0x60, 0x00, 0x52, 0x60, 0x20, 0x60, 0x00, 0xF3])


def _revert_word_bytecode(word: int) -> bytes:
    """PUSH1 word; PUSH1 0; MSTORE; PUSH1 32; PUSH1 0; REVERT."""
    return bytes([0x60, word & 0xFF, 0x60, 0x00, 0x52, 0x60, 0x20, 0x60, 0x00, 0xFD])


def _call_then(callee: str, tail: bytes, *, ret_size: int = 0) -> bytes:
    addr_hex = callee.replace("0x", "").zfill(40)
    return bytes(
        [
            0x60,
            ret_size & 0xFF,
            0x60,
            0x00,
            0x60,
            0x00,
            0x60,
            0x00,
            0x60,
            0x00,
            0x73,
            *bytes.fromhex(addr_hex),
            0x5A,
            0xF1,
        ]
    ) + tail


def _run(parent: bytes, child: bytes) -> dict:
    storage: dict = {}
    ctx = EVMContext(contract_call=_hook_must_not_run)
    host_ctx = native.evm_host_context_from_evm(ctx)
    host_ctx["bridge_state"] = {"codes": {CALLEE: child}, "storages": {CALLEE: {}}}
    evm = EVM(gas_limit=1_000_000, context=ctx)
    evm.storage = storage
    bridge = make_evm_runtime_bridge(evm)
    return native.evm_run_nested_host_frame(
        parent, 1_000_000, b"", host_ctx, storage, bridge
    )


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_call_ret_offset_copies_child_return_word() -> None:
    """CALL retSize=32 writes child RETURN into parent memory (existing path)."""
    parent = _call_then(CALLEE, bytes([0x60, 0x00, 0x51, 0x00]), ret_size=32)
    out = _run(parent, _return_word_bytecode(0x2A))
    assert not out.get("reverted")
    stack = list(out.get("stack") or [])
    assert int(stack[-1]) == 0x2A


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_returndatacopy_after_call_uses_live_buffer() -> None:
    """CALL retSize=0 then RETURNDATACOPY must still see the child's RETURN."""
    # POP success; PUSH1 32; PUSH1 0; PUSH1 0; RETURNDATACOPY; PUSH1 0; MLOAD; STOP
    tail = bytes(
        [
            0x50,
            0x60,
            0x20,
            0x60,
            0x00,
            0x60,
            0x00,
            0x3E,
            0x60,
            0x00,
            0x51,
            0x00,
        ]
    )
    parent = _call_then(CALLEE, tail, ret_size=0)
    out = _run(parent, _return_word_bytecode(0x2A))
    assert not out.get("reverted")
    stack = list(out.get("stack") or [])
    assert int(stack[-1]) == 0x2A, (
        "RETURNDATACOPY after nested CALL must copy live return_data, "
        f"got stack={stack!r}"
    )


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_returndatasize_after_call() -> None:
    tail = bytes([0x50, 0x3D, 0x00])  # POP; RETURNDATASIZE; STOP
    parent = _call_then(CALLEE, tail, ret_size=0)
    out = _run(parent, _return_word_bytecode(0x2A))
    assert not out.get("reverted")
    stack = list(out.get("stack") or [])
    assert int(stack[-1]) == 32


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_revert_data_propagates_through_returndatacopy() -> None:
    """Failed CALL still publishes revert data; success bit is 0."""
    # DUP1 keeps CALL status; RETURNDATACOPY; MLOAD → (word, success)
    tail = bytes(
        [
            0x80,  # DUP1 success
            0x60,
            0x20,
            0x60,
            0x00,
            0x60,
            0x00,
            0x3E,
            0x60,
            0x00,
            0x51,
            0x00,
        ]
    )
    parent = _call_then(CALLEE, tail, ret_size=0)
    out = _run(parent, _revert_word_bytecode(0xEE))
    assert not out.get("reverted"), "parent frame must continue after child REVERT"
    stack = [int(x) for x in (out.get("stack") or [])]
    assert stack[-1] == 0xEE
    assert stack[-2] == 0
