# api/fake_rpc.py — FakeRpcClient + FakeQueryFacade (ADR 0011)
"""Simulate malformed JSON-RPC, bad params, timeouts, and query caps."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Sequence

from api.ports import (
    BlockQuery,
    LogsQuery,
    NullRpcPort,
    QueryLimitError,
    QueryTimeoutError,
    RpcRequest,
    RpcResponse,
)
from api.query_executor import QueryExecutor
from api.rpc_schema import decode_rpc_payload, decode_single_request, rpc_error
from api.rpc_service import RpcService


class FakeQueryFacade:
    def __init__(self, *, tip: int = 10, max_range: int = 2000, max_results: int = 1000):
        self._tip = tip
        self.blocks: Dict[Any, Dict[str, Any]] = {
            tip: {"height": tip, "hash": "0x" + "ab" * 32, "transactions": [], "timestamp": 1}
        }
        self.txs: Dict[str, Dict[str, Any]] = {}
        self.balances: Dict[str, float] = {}
        self.nonces: Dict[str, int] = {}
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_range = max_range
        self.max_results = max_results
        self.force_timeout = False
        self.timeout_ms = 50
        self.executor = QueryExecutor(workers=1, default_timeout_ms=self.timeout_ms)

    def tip_height(self) -> int:
        return int(self._tip)

    def get_block(self, q: BlockQuery) -> Optional[Dict[str, Any]]:
        if q.block_hash:
            for blk in self.blocks.values():
                if blk.get("hash") == q.block_hash:
                    return dict(blk)
            return None
        if q.height is not None:
            return dict(self.blocks[q.height]) if q.height in self.blocks else None
        tag = (q.tag or "latest").lower()
        if tag in ("latest", "pending", ""):
            return dict(self.blocks.get(self._tip) or {})
        try:
            h = int(tag, 16) if tag.startswith("0x") else int(tag)
            return dict(self.blocks[h]) if h in self.blocks else None
        except (TypeError, ValueError):
            return None

    def get_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        return dict(self.txs[tx_hash]) if tx_hash in self.txs else None

    def get_balance(self, address: str, block_tag: str = "latest") -> float:
        return float(self.balances.get(address, 0.0))

    def get_nonce(self, address: str) -> int:
        return int(self.nonces.get(address, 0))

    def get_account(self, address: str) -> Optional[Dict[str, Any]]:
        row = self.accounts.get(address)
        return dict(row) if row else None

    def query_logs(self, q: LogsQuery) -> List[Dict[str, Any]]:
        span = int(q.to_block) - int(q.from_block)
        if span > self.max_range:
            raise QueryLimitError(f"get_logs_range_exceeded:{span}>{self.max_range}")
        if self.force_timeout:

            def _slow():
                time.sleep(1.0)
                return list(self.logs)

            return self.executor.submit(_slow, timeout_ms=self.timeout_ms)
        limit = min(int(q.limit or self.max_results), self.max_results)
        rows = [
            r
            for r in self.logs
            if int(q.from_block) <= int(r.get("block_height", 0)) <= int(q.to_block)
        ]
        return rows[:limit]

    def list_latest_blocks(self, limit: int) -> List[Dict[str, Any]]:
        return [dict(self.blocks[self._tip])][:limit]

    def get_evm_logs_by_tx(self, tx_hash: str) -> List[Dict[str, Any]]:
        return [r for r in self.logs if r.get("tx_hash") == tx_hash]

    def get_evm_logs_by_block(self, block_height: int) -> List[Dict[str, Any]]:
        try:
            height = int(block_height)
        except (TypeError, ValueError):
            return []
        return [r for r in self.logs if int(r.get("block_height", 0) or 0) == height]


class FakeRpcClient:
    """In-process JSON-RPC client over RpcService / NullRpcPort."""

    def __init__(self, rpc: Any = None, *, config: Any = None):
        self.config = config or type("C", (), {"jsonrpc_max_batch": 32, "chain_id": 77777, "node_version": "test", "gas_price_wei": 1e-9, "mining_enabled": False, "deployment_mode": "dev", "miner_address": ""})()
        self.query = FakeQueryFacade()
        if rpc is None:
            rpc = RpcService(
                query=self.query,
                blockchain=None,
                mempool=_FakeMempool(),
                config=self.config,
            )
        self.rpc = rpc
        self.last_raw: Any = None

    def handle_raw(self, raw: Any) -> Any:
        """Accept bytes/str/dict/list like a transport body."""
        self.last_raw = raw
        if raw is None or raw == "" or raw == b"":
            return rpc_error(-32600, "empty request").as_jsonrpc()
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = json.loads(raw.decode() or "")
            except json.JSONDecodeError:
                return {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None}
        elif isinstance(raw, str):
            try:
                raw = json.loads(raw or "")
            except json.JSONDecodeError:
                return {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None}

        max_batch = int(getattr(self.config, "jsonrpc_max_batch", 32) or 32)
        decoded = decode_rpc_payload(raw, max_batch=max_batch)
        if isinstance(decoded, RpcResponse):
            return decoded.as_jsonrpc()
        if isinstance(decoded, list):
            responses = []
            for item in decoded:
                if isinstance(item, RpcResponse):
                    responses.append(item.as_jsonrpc())
                else:
                    responses.append(self.rpc.call(item).as_jsonrpc())
            return responses
        return self.rpc.call(decoded).as_jsonrpc()

    def call(self, method: str, params: list | None = None, rid: Any = 1) -> Dict[str, Any]:
        return self.handle_raw(
            {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or []}
        )


class _FakeMempool:
    def __init__(self):
        self._size = 0
        self.added = []

    def get_size(self) -> int:
        return self._size
