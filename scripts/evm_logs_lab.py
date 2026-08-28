#!/usr/bin/env python3
"""EVM log / bloom RPC honesty lab (Profile A wave-11).

Missing fields stay JSON null (not height 0 / empty address). No live mesh.

Usage:
  python scripts/evm_logs_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.eth_format import (
    EMPTY_LOGS_BLOOM,
    format_block_tx_count,
    format_eth_log,
    format_receipt,
)


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    sparse = format_eth_log(
        {
            "topics": ["0x" + "ab" * 32],
            "data": "0x01",
        }
    )
    if sparse.get("blockNumber") is not None:
        return _fail("missing inclusion height must be null")
    if sparse.get("logIndex") is not None:
        return _fail("missing logIndex must be null")
    if sparse.get("transactionIndex") is not None:
        return _fail("missing transactionIndex must be null")
    if sparse.get("address") not in (None,):
        return _fail("missing address must be null")
    if sparse.get("transactionHash") is not None:
        return _fail("missing transactionHash must be null")

    receipt = format_receipt(
        {
            "hash": "0xabc",
            "block_height": 7,
            "from_addr": "0x" + "1" * 40,
            "to_addr": "0x" + "2" * 40,
            "status": 1,
            "gas_used": 21000,
        }
    )
    if receipt is None:
        return _fail("format_receipt")
    if receipt.get("logsBloom") != EMPTY_LOGS_BLOOM:
        return _fail("empty logs bloom")
    if receipt.get("logs") not in ([], None) and receipt.get("logs") != []:
        # format_receipt without query has empty logs list
        if receipt.get("logs"):
            return _fail("receipt without query must not invent logs")

    if format_block_tx_count(None) is not None:
        return _fail("missing block tx count must be null (not 0x0)")

    print("OK: evm_logs_lab PASS (null-honesty logs + missing block count)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
