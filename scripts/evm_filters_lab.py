#!/usr/bin/env python3
"""EVM JSON-RPC filter lab (Profile A — polling filters, no live mesh).

Exercises eth_newFilter / eth_getFilterChanges / eth_uninstallFilter honesty
via in-process RpcService + EthFilterStore.

Usage:
  python scripts/evm_filters_lab.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.eth_filters import EthFilterStore
from api.fake_rpc import FakeQueryFacade, FakeRpcClient, _FakeMempool
from api.ports import BlockQuery
from api.rpc_service import RpcService


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


class _FakeBC:
    """Minimal blockchain surface for EthFilterStore block filters."""

    def __init__(self, query: FakeQueryFacade) -> None:
        self.query_facade = query

    def get_height(self) -> int:
        return int(self.query_facade.tip_height())

    def get_block(self, height: int):
        return self.query_facade.get_block(BlockQuery(height=int(height)))


def _client_with_filters(query: FakeQueryFacade | None = None) -> FakeRpcClient:
    q = query or FakeQueryFacade(tip=5)
    bc = _FakeBC(q)
    mp = _FakeMempool()
    store = EthFilterStore()
    cfg = type("C", (), {"jsonrpc_max_batch": 32, "chain_id": 77777, "node_version": "test"})()
    rpc = RpcService(
        query=q,
        blockchain=bc,
        mempool=mp,
        config=cfg,
        eth_filters=store,
    )
    client = FakeRpcClient(rpc=rpc, config=cfg)
    client.query = q
    return client


def main() -> int:
    # Without EthFilterStore → fail-closed error (not silent success)
    bare = FakeRpcClient()
    denied = bare.call("eth_newFilter", [{"fromBlock": "0x0", "toBlock": "latest"}])
    if denied.get("error") is None:
        return _fail("eth_newFilter without store must error (filters unavailable)")

    client = _client_with_filters()
    q = client.query

    filt = client.call("eth_newFilter", [{"fromBlock": "0x0", "toBlock": "latest"}])
    if filt.get("error") is not None:
        return _fail(f"newFilter error: {filt}")
    filt_id = filt.get("result")
    if not isinstance(filt_id, str) or not filt_id.startswith("0x"):
        return _fail("newFilter must return hex filter id")

    empty = client.call("eth_getFilterChanges", [filt_id])
    if empty.get("result") != []:
        return _fail("getFilterChanges before new logs must be []")

    # Advance tip + index a log row
    q._tip = 6
    q.blocks[6] = {"height": 6, "hash": "0x" + "cc" * 32, "transactions": []}
    q.logs.append(
        {
            "block_height": 6,
            "log_index": 0,
            "contract_address": "0x" + "aa" * 20,
            "topics": ["0x" + "bb" * 32],
            "data": "0x01",
        }
    )
    changes = client.call("eth_getFilterChanges", [filt_id])
    rows = changes.get("result") or []
    if len(rows) != 1:
        return _fail("getFilterChanges must return new log after tip advance")
    if rows[0].get("address") != "0x" + "aa" * 20:
        return _fail("filter log address from observed contract_address")

    # Unknown filter id → [] (not invented logs)
    ghost = client.call("eth_getFilterChanges", ["0xdead"])
    if ghost.get("result") != []:
        return _fail("unknown filter id must return empty list")

    un = client.call("eth_uninstallFilter", [filt_id])
    if un.get("result") is not True:
        return _fail("uninstallFilter must return true")
    after = client.call("eth_getFilterChanges", [filt_id])
    if after.get("result") != []:
        return _fail("getFilterChanges after uninstall must be []")

    bad_un = client.call("eth_uninstallFilter", ["0xdead"])
    if bad_un.get("result") is not False:
        return _fail("uninstall unknown filter must return false")

    block_id = client.call("eth_newBlockFilter", [])
    if block_id.get("error") is not None:
        return _fail(f"newBlockFilter: {block_id}")
    q._tip = 7
    q.blocks[7] = {"height": 7, "hash": "0x" + "dd" * 32, "transactions": []}
    bh = client.call("eth_getFilterChanges", [block_id.get("result")])
    hashes = bh.get("result") or []
    if len(hashes) != 1 or hashes[0] != "0x" + "dd" * 32:
        return _fail("block filter must emit observed block hash")

    print("OK: evm_filters_lab PASS (newFilter/changes/uninstall honesty; not WS subs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
