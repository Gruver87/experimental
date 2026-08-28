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

    # eth_estimateGas: missing adapter → JSON null (never invent 21000)
    from api.fake_rpc import FakeRpcClient

    client = FakeRpcClient()
    resp = client.call("eth_estimateGas", [{"to": "0x" + "ab" * 20, "data": "0x"}])
    if "error" in resp and resp.get("error"):
        return _fail(f"estimateGas RPC error: {resp}")
    if resp.get("result") is not None:
        return _fail("estimateGas without adapter must be null (not 0x5208)")

    class _NoneGas:
        def estimate_gas(self, _to, _data):
            return None

    client2 = FakeRpcClient(
        rpc=__import__("api.rpc_service", fromlist=["RpcService"]).RpcService(
            query=client.query,
            blockchain=None,
            mempool=None,
            config=client.config,
            evm=_NoneGas(),
        )
    )
    resp2 = client2.call("eth_estimateGas", [{"to": "0x" + "cd" * 20}])
    if resp2.get("result") is not None:
        return _fail("estimateGas adapter None must stay null")

    # eth_feeHistory: baseFeePerGas / reward stay null (not EIP-1559)
    from api.eth_format import DEFAULT_EVM_GAS_LIMIT, format_fee_history

    q_fee = FakeQueryFacade(tip=5)
    q_fee.blocks[4] = {
        "height": 4,
        "hash": "0x" + "44" * 32,
        "gas_used": DEFAULT_EVM_GAS_LIMIT // 2,
        "transactions": [],
    }
    q_fee.blocks[5] = {
        "height": 5,
        "hash": "0x" + "55" * 32,
        "gas_used": DEFAULT_EVM_GAS_LIMIT,
        "transactions": [],
    }
    cfg_fee = type("C", (), {"gas_price_wei": 0, "evm_gas_limit": DEFAULT_EVM_GAS_LIMIT})()
    fee = format_fee_history(query=q_fee, cfg=cfg_fee, block_count=2, newest_tag="latest")
    if fee.get("baseFeePerGas") != [None, None]:
        return _fail("feeHistory baseFeePerGas must be null (not EIP-1559)")
    if fee.get("reward") != [None, None]:
        return _fail("feeHistory reward must be null")
    if fee.get("gasUsedRatio") != [0.5, 1.0]:
        return _fail("feeHistory ratios from observed gas")

    # eth_maxPriorityFeePerGas: unset → null (not EIP-1559 0x0)
    tip_resp = client.call("eth_maxPriorityFeePerGas", [])
    if tip_resp.get("result") is not None:
        return _fail("maxPriorityFeePerGas unset must be null (not 0x0)")

    # eth_coinbase / eth_mining / eth_hashrate honesty (not ethash)
    cb = client.call("eth_coinbase", [])
    if cb.get("result") is not None:
        return _fail("coinbase empty miner_address must be null")
    mining = client.call("eth_mining", [])
    if mining.get("result") is not False:
        return _fail("mining_enabled=false must report eth_mining false")
    hr = client.call("eth_hashrate", [])
    if hr.get("result") != "0x0":
        return _fail("hashrate must be 0x0 (Absolute is not ethash)")

    # eth_getCode / getBalance / getStorageAt / protocolVersion honesty
    code = client.call("eth_getCode", ["0x" + "11" * 20])
    if code.get("result") != "0x":
        return _fail("missing account getCode must be 0x (EOA empty)")
    bal = client.call("eth_getBalance", ["0x" + "11" * 20])
    if bal.get("result") != "0x0":
        return _fail("missing account getBalance must be 0x0 wei")
    slot = client.call("eth_getStorageAt", ["0x" + "11" * 20, "0x0"])
    if slot.get("result") != "0x0":
        return _fail("missing account getStorageAt must be 0x0")
    proto = client.call("eth_protocolVersion", [])
    if proto.get("result") != hex(65):
        return _fail("protocolVersion is Absolute JSON-RPC compat constant (hex 65)")

    # runtime snapshot reachable
    from execution.evm_runtime import evm_compat_honesty_snapshot
    from runtime.config import Config

    snap = evm_compat_honesty_snapshot(Config())
    if snap.get("partial_count", 0) < 1 or snap.get("not_claimed_count", 0) < 1:
        return _fail("compat snapshot must list partial + not_claimed rows")

    print(
        "OK: evm_rpc_lab PASS "
        "(null-honesty + fees + coinbase/mining + getCode/balance/storage + protocolVersion)"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
