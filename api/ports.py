# api/ports.py — ADR 0011 RPC / query switching surfaces
"""Protocols and DTOs for the JSON-RPC API layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class BlockQuery:
    height: Optional[int] = None
    block_hash: str = ""
    tag: str = ""
    full_tx: bool = False


@dataclass(frozen=True)
class LogsQuery:
    from_block: int
    to_block: int
    addresses: tuple = ()
    topics: tuple = ()
    limit: int = 1000


@dataclass(frozen=True)
class RpcRequest:
    method: str
    params: tuple = ()
    id: Any = None
    jsonrpc: str = "2.0"


@dataclass(frozen=True)
class RpcResponse:
    ok: bool
    result: Any = None
    error: Optional[Dict[str, Any]] = None
    id: Any = None

    def as_jsonrpc(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"jsonrpc": "2.0", "id": self.id}
        if self.ok:
            out["result"] = self.result
        else:
            out["error"] = self.error or {
                "code": -32603,
                "message": "internal error",
            }
        return out


class QueryLimitError(Exception):
    """Raised when a query exceeds configured amplification caps."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class QueryTimeoutError(Exception):
    """Heavy query exceeded executor timeout."""

    def __init__(self, reason: str = "query_timeout"):
        super().__init__(reason)
        self.reason = reason


@runtime_checkable
class QueryFacadePort(Protocol):
    def tip_height(self) -> int:
        ...

    def get_block(self, q: BlockQuery) -> Optional[Dict[str, Any]]:
        ...

    def get_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        ...

    def get_balance(self, address: str, block_tag: str = "latest") -> float:
        ...

    def get_nonce(self, address: str) -> int:
        ...

    def get_account(self, address: str) -> Optional[Dict[str, Any]]:
        ...

    def query_logs(self, q: LogsQuery) -> List[Dict[str, Any]]:
        ...

    def list_latest_blocks(self, limit: int) -> List[Dict[str, Any]]:
        ...

    def get_evm_logs_by_tx(self, tx_hash: str) -> List[Dict[str, Any]]:
        ...

    def get_evm_logs_by_block(self, block_height: int) -> List[Dict[str, Any]]:
        ...


@runtime_checkable
class RpcPort(Protocol):
    def call(self, request: RpcRequest) -> RpcResponse:
        ...

    def call_batch(self, requests: Sequence[RpcRequest]) -> List[RpcResponse]:
        ...

    def get_stats(self) -> Dict[str, Any]:
        ...


class NullQueryFacade:
    """Disabled / unattached query surface."""

    def tip_height(self) -> int:
        return 0

    def get_block(self, q: BlockQuery) -> Optional[Dict[str, Any]]:
        return None

    def get_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        return None

    def get_balance(self, address: str, block_tag: str = "latest") -> float:
        return 0.0

    def get_nonce(self, address: str) -> int:
        return 0

    def get_account(self, address: str) -> Optional[Dict[str, Any]]:
        return None

    def query_logs(self, q: LogsQuery) -> List[Dict[str, Any]]:
        return []

    def list_latest_blocks(self, limit: int) -> List[Dict[str, Any]]:
        return []

    def get_evm_logs_by_tx(self, tx_hash: str) -> List[Dict[str, Any]]:
        return []

    def get_evm_logs_by_block(self, block_height: int) -> List[Dict[str, Any]]:
        return []


class NullRpcPort:
    """RPC disabled — all calls refuse."""

    def call(self, request: RpcRequest) -> RpcResponse:
        return RpcResponse(
            ok=False,
            id=request.id,
            error={"code": -32000, "message": "rpc_disabled"},
        )

    def call_batch(self, requests: Sequence[RpcRequest]) -> List[RpcResponse]:
        return [self.call(r) for r in requests]

    def get_stats(self) -> Dict[str, Any]:
        return {"enabled": False, "backend": "null"}
