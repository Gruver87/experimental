#!/usr/bin/env python3
"""EVM RPC compat lab (Profile A wave-9).

Exercises null-honesty formatters and eth_call encoding without live mesh.

Usage:
  python scripts/evm_rpc_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.eth_format import (
    EMPTY_LOGS_BLOOM,
    ZERO_HASH,
    encode_eth_call_return,
    format_block,
    format_block_tx_count,
    format_receipt,
)
from api.fake_rpc import FakeQueryFacade


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    # eth_call encode
    out = encode_eth_call_return(1)
    if not (out.startswith("0x") and len(out) == 2 + 64 and out.endswith("1")):
        return _fail("encode_eth_call int word")
    if encode_eth_call_return(None) != "0x":
        return _fail("encode_eth_call None → 0x")

    # receipt null-honesty
    tx = {
        "hash": "0xabc",
        "block_height": 7,
        "from_addr": "0x1",
        "to_addr": "0x2",
        "status": 1,
        "gas_used": 42000,
        "gas_price": 100,
        "type": 2,
        "tx_index": 3,
    }
    r = format_receipt(tx)
    if r is None:
        return _fail("format_receipt returned None")
    if r["blockHash"] is None and r["blockHash"] != ZERO_HASH:
        pass
    elif r["blockHash"] == ZERO_HASH:
        return _fail("receipt must not invent zero blockHash")
    if r["logsBloom"] != EMPTY_LOGS_BLOOM:
        return _fail("empty logs bloom")
    if r["gasUsed"] != hex(42000):
        return _fail("gasUsed hex")

    # cumulative gas across block txs
    q = FakeQueryFacade(tip=3)
    txs = [
        {"hash": "0xa", "gas_used": 21000, "block_height": 3},
        {"hash": "0xb", "gas_used": 42000, "block_height": 3},
    ]
    q.blocks[3] = {"height": 3, "hash": "0x" + "bb" * 32, "transactions": txs}
    mid = format_receipt(txs[1], query=q)
    if mid is None or mid["cumulativeGasUsed"] != hex(63000):
        return _fail("cumulativeGasUsed sum")

    # missing block → null tx count (not 0x0)
    if format_block_tx_count(None) is not None:
        return _fail("missing block tx count must be null")

    # block with txs sums gasUsed
    blk = format_block(q.blocks[3], query=q)
    if blk is None or blk.get("gasUsed") != hex(63000):
        return _fail("block gasUsed sum from txs")

    # runtime snapshot reachable
    from execution.evm_runtime import evm_compat_honesty_snapshot
    from runtime.config import Config

    snap = evm_compat_honesty_snapshot(Config())
    if snap.get("partial_count", 0) < 1 or snap.get("not_claimed_count", 0) < 1:
        return _fail("compat snapshot must list partial + not_claimed rows")

    print("OK: evm_rpc_lab PASS (RPC null-honesty + compat snapshot)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
