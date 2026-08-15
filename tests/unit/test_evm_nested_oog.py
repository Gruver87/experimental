#!/usr/bin/env python3
"""Nested CALL out-of-gas: forwarded gas is consumed; child writes are not.

Yellow Paper exceptional halt of a call burns the gas stipend forwarded to
the child. REVERT refunds unused gas; OOG does not. Parent must continue.
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
FORWARDED = 100


def _hook_must_not_run(_target, _calldata, _value, _gas, _delegate, static=False, callcode=False):
    raise AssertionError("nested CALL must stay on the native inline path")


def _sstore_stop() -> bytes:
    return bytes([0x60, 0x63, 0x60, 0x01, 0x55, 0x00])


def _stop_only() -> bytes:
    return bytes([0x00])


def _revert_word() -> bytes:
    return bytes([0x60, 0xEE, 0x60, 0x00, 0x52, 0x60, 0x20, 0x60, 0x00, 0xFD])


def _parent_call(gas: int) -> bytes:
    addr_hex = CALLEE.replace("0x", "").zfill(40)
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
            0x00,
            0x73,
            *bytes.fromhex(addr_hex),
            0x60,
            gas & 0xFF,
            0xF1,
            0x00,
        ]
    )


def _run(child: bytes, *, gas: int = FORWARDED) -> tuple[dict, dict]:
    storage: dict = {}
    ctx = EVMContext(contract_call=_hook_must_not_run)
    host_ctx = native.evm_host_context_from_evm(ctx)
    storages = {CALLEE: {}}
    host_ctx["bridge_state"] = {"codes": {CALLEE: child}, "storages": storages}
    evm = EVM(gas_limit=1_000_000, context=ctx)
    evm.storage = storage
    bridge = make_evm_runtime_bridge(evm)
    out = native.evm_run_nested_host_frame(
        _parent_call(gas), 1_000_000, b"", host_ctx, storage, bridge
    )
    return out, storages[CALLEE]


def _slot1(st: dict) -> int:
    return int(st.get(1, st.get("1", 0)) or 0)


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_child_oog_does_not_commit_sstore() -> None:
    out, child_st = _run(_sstore_stop())
    assert not out.get("reverted"), "parent must continue after child OOG"
    stack = [int(x) for x in (out.get("stack") or [])]
    assert stack[-1] == 0
    assert _slot1(child_st) == 0


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_child_oog_consumes_all_forwarded_gas() -> None:
    cheap, _ = _run(_stop_only())
    oog, _ = _run(_sstore_stop())
    assert not cheap.get("reverted")
    assert not oog.get("reverted")
    cheap_used = int(cheap.get("gas_used") or 0)
    oog_used = int(oog.get("gas_used") or 0)
    assert cheap["stack"][-1] == 1
    assert oog["stack"][-1] == 0
    # STOP child uses ~0 of the 100 forwarded; OOG must still burn all 100.
    assert oog_used - cheap_used == FORWARDED, (
        f"OOG must charge forwarded gas {FORWARDED}, "
        f"got cheap={cheap_used} oog={oog_used} delta={oog_used - cheap_used}"
    )


@pytest.mark.skipif(
    not getattr(native, "native_available", lambda: False)(),
    reason="abs_native required",
)
def test_child_revert_does_not_burn_all_forwarded_gas() -> None:
    cheap, _ = _run(_stop_only())
    reverted, _ = _run(_revert_word())
    assert not cheap.get("reverted")
    assert not reverted.get("reverted")
    cheap_used = int(cheap.get("gas_used") or 0)
    rev_used = int(reverted.get("gas_used") or 0)
    assert reverted["stack"][-1] == 0
    # REVERT refunds unused forwarded gas; must not look like OOG (full 100).
    assert 0 < rev_used - cheap_used < FORWARDED
