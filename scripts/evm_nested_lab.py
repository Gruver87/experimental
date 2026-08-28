#!/usr/bin/env python3
"""EVM nested CALL/STATICCALL lab (Profile A wave-10).

Exercises native inline apply-path nested semantics without live mesh.

Usage:
  python scripts/evm_nested_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crypto import native
from evm_interpreter import EVM, EVMContext
from execution.evm_host_bridge import make_evm_runtime_bridge

CALLEE = "0x00000000000000000000000000000000000000bb"


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _hook_must_not_run(*_a, **_k):
    raise AssertionError("nested call must stay on native inline path")


def _sstore_stop() -> bytes:
    return bytes([0x60, 0x63, 0x60, 0x01, 0x55, 0x00])


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


def main() -> int:
    if not getattr(native, "native_available", lambda: False)():
        print("SKIP: evm_nested_lab requires abs_native (run build_native.ps1)")
        return 0

    # CALL child SSTORE persists
    parent_call = _call_op(CALLEE, 0xF1, bytes([0x00]))
    out_call, child_st = _run(parent_call, _sstore_stop())
    if out_call.get("reverted"):
        return _fail("CALL parent must not revert")
    stack = [int(x) for x in (out_call.get("stack") or [])]
    if not stack or stack[-1] != 1:
        return _fail("CALL must return success=1 on stack")
    if _slot1(child_st) != 99:
        return _fail("CALL child SSTORE must persist slot 1=99")

    # STATICCALL child SSTORE must not commit
    parent_static = _call_op(CALLEE, 0xFA, bytes([0x00]))
    out_static, child_st2 = _run(parent_static, _sstore_stop())
    if out_static.get("reverted"):
        return _fail("STATICCALL parent must not revert")
    stack2 = [int(x) for x in (out_static.get("stack") or [])]
    if not stack2 or stack2[-1] != 0:
        return _fail("STATICCALL write-refuse must return 0 on stack")
    if _slot1(child_st2) != 0:
        return _fail("STATICCALL child SSTORE must not persist")

    print("OK: evm_nested_lab PASS (CALL persist + STATICCALL write-refuse)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
