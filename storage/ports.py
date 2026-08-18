"""Storage domain ports (ADR 0006 A–F).

Protocols only — no engine / SQLite / keycodec / CF imports.
Domain (`core/`, `consensus/`, `sync/`) must depend on these ports, not on
native engine types or column-family labels.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Iterator, Mapping, Optional, Protocol, Sequence, runtime_checkable

from storage.types import AccountRecord, BlockRecord, TipMeta

__all__ = [
    "BlockStorePort",
    "StateStorePort",
    "MetaStorePort",
    "BridgeStorePort",
    "StorageUnitOfWorkPort",
    "StorageHealthPort",
    "StoragePort",
]


@runtime_checkable
class BlockStorePort(Protocol):
    """Canonical block body / tip reads + chain surgery (no CF / raw keys)."""

    def tip_height(self) -> int:
        ...

    def tip_hash(self) -> str:
        ...

    def has_hash(self, block_hash: str) -> bool:
        ...

    def get_by_height(self, height: int) -> Optional[BlockRecord]:
        ...

    def get_by_hash(self, block_hash: str) -> Optional[BlockRecord]:
        ...

    def iterate_heights(self, from_height: int, to_height: int) -> Sequence[BlockRecord]:
        ...

    def reorg_truncate_above(self, height: int) -> None:
        """Drop bodies/indexes above ``height`` and rewind tip (domain passes height only)."""
        ...

    def save_block(self, block: Mapping[str, Any]) -> bool:
        ...

    def truncate_all_blocks(self) -> None:
        ...

    def truncate_blocks_above(self, height: int) -> Any:
        ...

    def get_transaction(self, tx_hash: str) -> Optional[Mapping[str, Any]]:
        ...

    def record_state_root_mismatch(self, *args: Any, **kwargs: Any) -> None:
        ...


@runtime_checkable
class StateStorePort(Protocol):
    """Account / state-root façade (adapter owns encoding policy)."""

    def get_account(self, address: str) -> Optional[Mapping[str, Any]]:
        ...

    def get_state_root(self) -> str:
        ...

    def get_state_root_baseline(self) -> int:
        ...

    def get_balance(self, address: str) -> float:
        ...

    def get_balance_satoshi(self, address: str) -> int:
        ...

    def get_nonce(self, address: str) -> int:
        ...

    def get_all_accounts(self) -> Sequence[Mapping[str, Any]]:
        ...

    def get_total_supply(self) -> float:
        ...

    def compute_state_root(self) -> str:
        ...

    def balance_delta(self, address: str, delta: int) -> None:
        ...

    def update_balance(self, address: str, delta: int) -> float:
        ...

    def set_balance(self, address: str, balance: int) -> None:
        ...

    def nonce_increment(self, address: str) -> int:
        ...

    def increment_nonce(self, address: str) -> int:
        ...

    def save_account(
        self,
        address: str,
        balance: int = 0,
        nonce: int = 0,
        code: Any = None,
        storage: Any = None,
    ) -> None:
        ...

    def reset_accounts_from_alloc(self, alloc: Mapping[str, Any], *, _in_atomic: bool = False) -> None:
        ...


@runtime_checkable
class MetaStorePort(Protocol):
    """Non-block meta the node already persists (validators, checkpoints, …)."""

    def get_validators(self, active_only: bool = True) -> Sequence[Mapping[str, Any]]:
        ...

    def get_checkpoint(self, epoch: int) -> Optional[Mapping[str, Any]]:
        ...

    def put_checkpoint(self, epoch: int, data: Mapping[str, Any]) -> None:
        ...

    def get_meta(self, key: str, default: Any = None) -> Any:
        ...

    def set_meta(self, key: str, value: Any) -> None:
        ...

    def get_stats(self) -> Mapping[str, Any]:
        ...

    def get_burn_stats(self) -> Mapping[str, Any]:
        ...

    def get_chain_metrics(self, window: int = 0) -> Mapping[str, Any]:
        ...


@runtime_checkable
class BridgeStorePort(Protocol):
    """L1 bridge debit / credit / refund (ADR 0010) — outside tip UoW."""

    def bridge_credit_key(
        self, from_chain: str, event_tx_hash: str, log_index: int = 0
    ) -> str:
        ...

    def has_bridge_credit(self, credit_key: str) -> bool:
        ...

    def debit_and_create_bridge_lock(
        self,
        from_addr: str,
        amount: float,
        burn_address: str,
        burn_amount: float,
        to_chain: str,
        to_addr: str,
        net_amount: float,
        tx_hash: str,
    ) -> Any:
        ...

    def claim_and_credit_bridge_event(
        self,
        from_chain: str,
        event_tx_hash: str,
        recipient: str,
        amount: float,
        log_index: int = 0,
        abs_tx_hash: str = "",
    ) -> Mapping[str, Any]:
        ...

    def refund_pending_bridge_lock(self, tx_hash: str) -> Mapping[str, Any]:
        ...

    def get_bridge_lock(self, lock_hash: str) -> Optional[Mapping[str, Any]]:
        ...


@runtime_checkable
class StorageUnitOfWorkPort(Protocol):
    """Single atomic block + state delta + tip commit (all-or-nothing)."""

    def write_block(self, block: BlockRecord | Mapping[str, Any]) -> None:
        ...

    def write_transactions(self, transactions: Sequence[Mapping[str, Any]]) -> None:
        ...

    def write_state_delta(
        self,
        accounts: Sequence[AccountRecord] | Mapping[str, Mapping[str, Any]],
    ) -> None:
        ...

    def set_tip(self, tip: TipMeta) -> None:
        ...

    def commit(self) -> None:
        ...

    def abort(self) -> None:
        ...


@runtime_checkable
class StorageHealthPort(Protocol):
    """Ops / status surface (no engine internals)."""

    def ping(self) -> bool:
        ...

    def approximate_size(self) -> int:
        ...

    def last_flush_ok(self) -> bool:
        ...


@runtime_checkable
class StoragePort(Protocol):
    """Composite storage boundary used by domain services (ADR 0006 F)."""

    @property
    def blocks(self) -> BlockStorePort:
        ...

    @property
    def state(self) -> StateStorePort:
        ...

    @property
    def meta(self) -> MetaStorePort:
        ...

    @property
    def health(self) -> StorageHealthPort:
        ...

    def begin_block_commit(
        self,
        *,
        expected_parent: str = "",
        expected_tip_height: int = -1,
    ) -> StorageUnitOfWorkPort:
        """Start a CAS-aware unit of work for one canonical tip advance."""
        ...

    def atomic(self) -> AbstractContextManager[Any]:
        """Engine transaction / WriteBatch scope (adapter-owned)."""
        ...

    def unwrap(self) -> Any:
        """Underlying legacy store (compat for API/P2P ``bc.db``)."""
        ...
