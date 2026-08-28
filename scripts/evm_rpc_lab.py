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

    # eth_chainId / net_version / web3_clientVersion / eth_syncing / net_peerCount
    chain = client.call("eth_chainId", [])
    if chain.get("result") != hex(77777):
        return _fail("chainId must match config (hex 77777 in lab)")
    net_ver = client.call("net_version", [])
    if net_ver.get("result") != "77777":
        return _fail("net_version must be decimal chain_id string")
    client_ver = client.call("web3_clientVersion", [])
    cv = client_ver.get("result") or ""
    if not str(cv).startswith("Absolute/") or not str(cv).endswith("/python"):
        return _fail("web3_clientVersion must be Absolute/{version}/python")
    syncing = client.call("eth_syncing", [])
    if syncing.get("result") is not False:
        return _fail("eth_syncing without P2P must be false (not object)")
    peers = client.call("net_peerCount", [])
    if peers.get("result") != "0x0":
        return _fail("net_peerCount without P2P must be 0x0")

    # eth_gasPrice / getTransactionCount / getTransactionByHash / block tx count
    from runtime.amount import abs_to_wei

    gp = client.call("eth_gasPrice", [])
    want_gp = hex(abs_to_wei(getattr(client.config, "gas_price_wei", 0) or 0))
    if gp.get("result") != want_gp:
        return _fail("gasPrice must match config gas_price_wei via abs_to_wei")
    unknown = "0x" + "33" * 20
    nonce = client.call("eth_getTransactionCount", [unknown, "latest"])
    if nonce.get("result") != "0x0":
        return _fail("getTransactionCount missing account must be 0x0")
    missing_tx = client.call("eth_getTransactionByHash", ["0x" + "44" * 32])
    if missing_tx.get("result") is not None:
        return _fail("getTransactionByHash missing must be null")
    miss_count = client.call("eth_getBlockTransactionCountByNumber", ["0x9999"])
    if miss_count.get("result") is not None:
        return _fail("getBlockTransactionCount missing block must be null")

    # eth_blockNumber / eth_accounts / eth_getMempoolSize / tx by block index
    tip = client.call("eth_blockNumber", [])
    if tip.get("result") != hex(client.query.tip_height()):
        return _fail("blockNumber must match query tip height")
    accts = client.call("eth_accounts", [])
    if accts.get("result") != []:
        return _fail("accounts empty when no wallet/miner must be []")
    mps = client.call("eth_getMempoolSize", [])
    if mps.get("result") != "0x0":
        return _fail("getMempoolSize empty pool must be 0x0")
    miss_idx = client.call("eth_getTransactionByBlockNumberAndIndex", ["0x9999", "0x0"])
    if miss_idx.get("result") is not None:
        return _fail("getTransactionByBlockNumberAndIndex missing block must be null")

    # eth_getTransactionReceipt / eth_getLogs RPC honesty
    miss_rcpt = client.call("eth_getTransactionReceipt", ["0x" + "55" * 32])
    if miss_rcpt.get("result") is not None:
        return _fail("getTransactionReceipt missing tx must be null")
    logs_empty = client.call("eth_getLogs", [{"fromBlock": "0x0", "toBlock": "latest"}])
    if not isinstance(logs_empty.get("result"), list):
        return _fail("getLogs must return list (empty when no rows)")
    client.query.logs.append(
        {
            "block_height": client.query.tip_height(),
            "log_index": 0,
            "tx_hash": "0xabc",
            "contract_address": "0x" + "aa" * 20,
            "topics": [],
            "data": "0x",
        }
    )
    logs_one = client.call(
        "eth_getLogs",
        [{"fromBlock": hex(client.query.tip_height()), "toBlock": "latest"}],
    )
    rows = logs_one.get("result") or []
    if len(rows) != 1:
        return _fail("getLogs must return indexed row when facade has logs")
    if rows[0].get("address") != "0x" + "aa" * 20:
        return _fail("getLogs address from observed contract_address")

    # eth_getBlockByNumber / ByHash — missing block null; sparse header honesty
    miss_blk_num = client.call("eth_getBlockByNumber", ["0x9999", False])
    if miss_blk_num.get("result") is not None:
        return _fail("getBlockByNumber missing block must be null")
    miss_blk_hash = client.call("eth_getBlockByHash", ["0x" + "77" * 32, False])
    if miss_blk_hash.get("result") is not None:
        return _fail("getBlockByHash missing block must be null")
    sparse_h = 42
    client.query.blocks[sparse_h] = {"height": sparse_h, "transactions": []}
    sparse = client.call("eth_getBlockByNumber", [hex(sparse_h), False])
    sb = sparse.get("result")
    if not isinstance(sb, dict):
        return _fail("sparse block must return object when height exists")
    if sb.get("hash") is not None or sb.get("stateRoot") is not None:
        return _fail("sparse block must not invent hash/stateRoot")
    if sb.get("gasUsed") != "0x0":
        return _fail("empty tx list gasUsed must be 0x0")

    # fullTx=false → hashes; fullTx=true → stored tx dicts; inverted getLogs → []
    tx_obj = {
        "hash": "0xabc123",
        "block_height": client.query.tip_height(),
        "from_addr": "0x" + "11" * 20,
        "to_addr": "0x" + "22" * 20,
        "value": 0,
    }
    h = client.query.tip_height()
    bh = client.query.blocks[h]["hash"]
    client.query.blocks[h] = {
        "height": h,
        "hash": bh,
        "transactions": [tx_obj],
    }
    hashes_only = client.call("eth_getBlockByNumber", ["latest", False])
    txs_h = (hashes_only.get("result") or {}).get("transactions") or []
    if not txs_h or not isinstance(txs_h[0], str):
        return _fail("fullTx=false must return transaction hash strings")
    full = client.call("eth_getBlockByNumber", ["latest", True])
    txs_f = (full.get("result") or {}).get("transactions") or []
    if not txs_f or not isinstance(txs_f[0], dict):
        return _fail("fullTx=true must return transaction objects")
    inv_logs = client.call("eth_getLogs", [{"fromBlock": "0x10", "toBlock": "0x1"}])
    if inv_logs.get("result") != []:
        return _fail("getLogs inverted range must return empty list")

    # runtime snapshot reachable
    from execution.evm_runtime import evm_compat_honesty_snapshot
    from runtime.config import Config

    snap = evm_compat_honesty_snapshot(Config())
    if snap.get("partial_count", 0) < 1 or snap.get("not_claimed_count", 0) < 1:
        return _fail("compat snapshot must list partial + not_claimed rows")

    print(
        "OK: evm_rpc_lab PASS "
        "(null-honesty + fees + coinbase/mining + getCode/balance/storage + protocolVersion + chain/net/sync + gasPrice/tx lookup + blockNumber/accounts/mempool + receipt/logs/block RPC)"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
