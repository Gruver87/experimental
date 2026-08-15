# api/query_facade.py — ADR 0011 QueryFacadePort adapter
"""Single unwrap site for API reads; enforces getLogs amplification caps."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from api.ports import (
    BlockQuery,
    LogsQuery,
    QueryLimitError,
    QueryTimeoutError,
)
from api.query_executor import QueryExecutor


class QueryFacade:
    def __init__(
        self,
        blockchain: Any,
        config: Any = None,
        *,
        executor: Optional[QueryExecutor] = None,
    ):
        self.blockchain = blockchain
        self.config = config
        self.executor = executor or QueryExecutor(
            workers=int(getattr(config, "rpc_heavy_workers", 2) or 2),
            default_timeout_ms=int(
                getattr(config, "rpc_heavy_query_timeout_ms", 5000) or 5000
            ),
        )

    def _store(self) -> Any:
        bc = self.blockchain
        if bc is None:
            return None
        storage = getattr(bc, "storage", None)
        if storage is not None:
            unwrap = getattr(storage, "unwrap", None)
            if callable(unwrap):
                return unwrap()
            return storage
        return getattr(bc, "db", None)

    def tip_height(self) -> int:
        bc = self.blockchain
        if bc is None:
            return 0
        return int(bc.get_height())

    def get_block(self, q: BlockQuery) -> Optional[Dict[str, Any]]:
        bc = self.blockchain
        if bc is None:
            return None
        blk: Optional[Dict[str, Any]] = None
        if q.block_hash:
            store = self._store()
            if store is not None and hasattr(store, "get_block_by_hash"):
                blk = store.get_block_by_hash(q.block_hash)
        elif q.height is not None:
            blk = bc.get_block(int(q.height))
        else:
            tag = (q.tag or "latest").strip().lower()
            if tag in ("latest", "pending", ""):
                blk = bc.get_last_block()
            elif tag in ("earliest",):
                blk = bc.get_block(0)
            else:
                try:
                    height = int(tag, 16) if tag.startswith("0x") else int(tag)
                    blk = bc.get_block(height)
                except (TypeError, ValueError):
                    return None

        if not blk:
            return None
        if q.full_tx:
            max_txs = int(getattr(self.config, "rpc_full_tx_block_max_txs", 500) or 500)
            txs = blk.get("transactions")
            if isinstance(txs, list) and len(txs) > max_txs:
                # Soft policy: return hashes-only when over cap (amplification gate)
                capped = dict(blk)
                capped["transactions"] = [
                    (t.get("hash") if isinstance(t, dict) else str(t)) for t in txs
                ]
                capped["_full_tx_truncated"] = True
                return capped
            # Heavy path via executor
            def _load():
                return dict(blk)

            try:
                return self.executor.submit(_load)
            except QueryTimeoutError:
                raise
        return blk

    def get_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        bc = self.blockchain
        if bc is None or not tx_hash:
            return None
        return bc.get_transaction(tx_hash)

    def get_balance(self, address: str, block_tag: str = "latest") -> float:
        _ = block_tag
        bc = self.blockchain
        if bc is None:
            return 0.0
        return float(bc.get_balance(address))

    def get_nonce(self, address: str) -> int:
        store = self._store()
        if store is not None and hasattr(store, "get_nonce"):
            return int(store.get_nonce(address))
        bc = self.blockchain
        if bc is not None and hasattr(bc, "get_nonce"):
            return int(bc.get_nonce(address))
        return 0

    def get_account(self, address: str) -> Optional[Dict[str, Any]]:
        store = self._store()
        if store is not None and hasattr(store, "get_account"):
            row = store.get_account(address)
            return dict(row) if row else None
        return None

    def query_logs(self, q: LogsQuery) -> List[Dict[str, Any]]:
        max_range = int(getattr(self.config, "rpc_get_logs_max_range", 2000) or 2000)
        max_results = int(getattr(self.config, "rpc_get_logs_max_results", 1000) or 1000)
        if q.to_block < q.from_block:
            return []
        span = int(q.to_block) - int(q.from_block)
        if span > max_range:
            raise QueryLimitError(f"get_logs_range_exceeded:{span}>{max_range}")
        limit = min(int(q.limit or max_results), max_results)
        store = self._store()
        if store is None or not hasattr(store, "query_evm_logs"):
            return []

        def _run():
            rows = store.query_evm_logs(
                from_block=int(q.from_block),
                to_block=int(q.to_block),
                addresses=list(q.addresses) if q.addresses else None,
                topics=list(q.topics) if q.topics else None,
            )
            if not isinstance(rows, list):
                return []
            return list(rows)[:limit]

        return self.executor.submit(_run)

    def list_latest_blocks(self, limit: int) -> List[Dict[str, Any]]:
        store = self._store()
        lim = max(1, min(int(limit or 10), 100))
        if store is not None and hasattr(store, "get_latest_blocks"):
            rows = store.get_latest_blocks(lim)
            return list(rows) if rows else []
        bc = self.blockchain
        if bc is None:
            return []
        tip = int(bc.get_height())
        out: List[Dict[str, Any]] = []
        for h in range(tip, max(-1, tip - lim), -1):
            blk = bc.get_block(h)
            if blk:
                out.append(blk)
        return out

    def get_evm_logs_by_tx(self, tx_hash: str) -> List[Dict[str, Any]]:
        store = self._store()
        if store is None or not hasattr(store, "get_evm_logs_by_tx"):
            return []
        rows = store.get_evm_logs_by_tx(tx_hash)
        return list(rows) if rows else []

    def get_evm_logs_by_block(self, block_height: int) -> List[Dict[str, Any]]:
        """All logs at one height — not getLogs amplification caps (block bloom)."""
        store = self._store()
        if store is None or not hasattr(store, "query_evm_logs"):
            return []
        try:
            height = int(block_height)
        except (TypeError, ValueError):
            return []
        if height < 0:
            return []
        rows = store.query_evm_logs(from_block=height, to_block=height, limit=10_000)
        return list(rows) if rows else []
