"""In-memory StoragePort façade with controlled fault injection (ADR 0006 C).

Used by unit DoD / stress tests. Domain-facing tests never touch RocksEngine.
Faults are explicit and consumed once (unless sticky flags are set).
"""

from __future__ import annotations

import copy
import threading
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

from storage.types import (
    AccountRecord,
    BlockRecord,
    StorageConflictError,
    StorageCorruptionError,
    StorageFullError,
    StorageUnavailableError,
    TipMeta,
)

__all__ = ["FakeStorage", "FakeStorageUnitOfWork"]

# Commit fault tokens accepted by ``fail_next_commit`` / ``inject_commit_fault``.
COMMIT_FAULT_DISK_FULL = "disk_full"
COMMIT_FAULT_ENOSPC_MID = "enospc_mid_write"
COMMIT_FAULT_IO = "io"
COMMIT_FAULT_CORRUPTION = "corruption"


class FakeStorageUnitOfWork:
    """Staged UoW — durable only after successful atomic ``commit()``."""

    def __init__(
        self,
        store: "FakeStorage",
        *,
        expected_parent: str,
        expected_tip_height: int,
    ) -> None:
        self._store = store
        self._expected_parent = str(expected_parent or "")
        self._expected_tip_height = int(expected_tip_height)
        self._block: Optional[BlockRecord] = None
        self._txs: List[Dict[str, Any]] = []
        self._accounts: Dict[str, AccountRecord] = {}
        self._tip: Optional[TipMeta] = None
        self._aborted = False
        self._committed = False

    def write_block(self, block: BlockRecord | Mapping[str, Any]) -> None:
        self._ensure_open()
        self._store._maybe_stage_fault("write_block")
        self._block = (
            block if isinstance(block, BlockRecord) else BlockRecord.from_mapping(block)
        )

    def write_transactions(self, transactions: Sequence[Mapping[str, Any]]) -> None:
        self._ensure_open()
        self._store._maybe_stage_fault("write_transactions")
        self._txs = [dict(t) for t in (transactions or ()) if isinstance(t, Mapping)]

    def write_state_delta(
        self,
        accounts: Sequence[AccountRecord] | Mapping[str, Mapping[str, Any]],
    ) -> None:
        self._ensure_open()
        self._store._maybe_stage_fault("write_state_delta")
        if isinstance(accounts, Mapping):
            for addr, row in accounts.items():
                rec = (
                    row
                    if isinstance(row, AccountRecord)
                    else AccountRecord.from_mapping(str(addr), row)
                )
                if rec.address:
                    self._accounts[rec.address] = rec
            return
        for row in accounts or ():
            if isinstance(row, AccountRecord):
                rec = row
            elif isinstance(row, Mapping):
                rec = AccountRecord.from_mapping(str(row.get("address") or ""), row)
            else:
                continue
            if rec.address:
                self._accounts[rec.address] = rec

    def set_tip(self, tip: TipMeta) -> None:
        self._ensure_open()
        self._store._maybe_stage_fault("set_tip")
        if not isinstance(tip, TipMeta):
            raise StorageUnavailableError(
                "set_tip requires TipMeta", reason_code="invalid_tip"
            )
        self._tip = tip

    def commit(self) -> None:
        self._ensure_open()
        store = self._store
        with store._lock:
            store._raise_commit_fault_if_armed()

            tip_h = int(store._tip.height)
            tip_hash = str(store._tip.head_hash or "")
            if self._expected_tip_height >= 0 and tip_h != self._expected_tip_height:
                raise StorageConflictError(
                    f"stale tip height want={self._expected_tip_height} got={tip_h}",
                    reason_code="stale_tip_height",
                )
            if self._expected_parent and tip_h > 0:
                if tip_hash.lower() != self._expected_parent.lower():
                    raise StorageConflictError(
                        "expected_parent mismatch",
                        reason_code="expected_parent_mismatch",
                    )

            if self._block is None:
                raise StorageUnavailableError("no block staged", reason_code="empty_uow")

            # Idempotent same-hash skip (import retry culture).
            if store.has_hash(self._block.block_hash):
                self._committed = True
                store._flush_ok = True
                return

            # Crash mid-batch: tip/body never swapped into durable maps.
            if store.interrupt_next_commit:
                store.interrupt_next_commit = False
                store._crash_pending = True
                store._flush_ok = False
                # Caller sees "success" only if they treat interrupt as opaque crash;
                # industrial tests assert tip unchanged after reopen.
                self._committed = True
                return

            # Build next durable snapshot (copy-on-write), then swap atomically.
            next_by_height = dict(store._by_height)
            next_by_hash = dict(store._by_hash)
            next_txs = {k: list(v) for k, v in store._txs.items()}
            next_accounts = dict(store._accounts)
            next_state_root = store._state_root

            blk = self._block
            next_by_height[blk.height] = blk
            next_by_hash[blk.block_hash] = blk
            next_txs[blk.block_hash] = list(self._txs)
            for addr, acc in self._accounts.items():
                next_accounts[addr] = acc
            tip = self._tip or TipMeta(
                height=blk.height,
                head_hash=blk.block_hash,
                state_root=next_state_root,
            )
            if tip.state_root:
                next_state_root = tip.state_root

            # ENOSPC mid-write: staging succeeded in ephemeral maps, durable swap aborted.
            if store._consume_mid_write_enospc():
                store._flush_ok = False
                store._enospc_aborts += 1
                raise StorageFullError(
                    "ENOSPC during WriteBatch (No space left on device)",
                    reason_code="disk_full",
                )

            # Atomic publish
            store._by_height = next_by_height
            store._by_hash = next_by_hash
            store._txs = next_txs
            store._accounts = next_accounts
            store._tip = tip
            store._state_root = next_state_root
            store._flush_ok = True
            store._commit_count += 1
            self._committed = True

    def abort(self) -> None:
        self._aborted = True
        self._block = None
        self._txs = []
        self._accounts = {}
        self._tip = None
        self._store._flush_ok = True

    def _ensure_open(self) -> None:
        if self._aborted:
            raise StorageUnavailableError("uow aborted", reason_code="aborted")
        if self._committed:
            raise StorageUnavailableError(
                "uow already committed", reason_code="committed"
            )


# Back-compat alias
_FakeUoW = FakeStorageUnitOfWork


class FakeStorage:
    """In-memory implementation of all storage ports + fault injection hooks."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._by_height: Dict[int, BlockRecord] = {}
        self._by_hash: Dict[str, BlockRecord] = {}
        self._txs: Dict[str, List[Mapping[str, Any]]] = {}
        self._accounts: Dict[str, AccountRecord] = {}
        self._tip = TipMeta(height=0, head_hash="")
        self._state_root = ""
        self._state_root_baseline = 0
        self._finalized_height = 0
        self._validators: List[Mapping[str, Any]] = []
        self._checkpoints: Dict[int, Mapping[str, Any]] = {}
        self._flush_ok = True
        self._approx_size = 0
        self._commit_count = 0
        self._enospc_aborts = 0

        # ── Fault injection (consumed unless sticky_*) ───────────────────────
        self.fail_next_commit = ""
        self.sticky_commit_fault = ""
        self.interrupt_next_commit = False
        self._crash_pending = False
        self.corrupt_block_hashes: Set[str] = set()
        self.corrupt_account_addresses: Set[str] = set()
        self.fail_next_stage: str = ""  # stage name → StorageUnavailableError
        self._mid_write_enospc_armed = False

    # ── Fault injection API ──────────────────────────────────────────────────

    def inject_commit_fault(self, kind: str, *, sticky: bool = False) -> None:
        """Arm a commit-time fault: disk_full | enospc_mid_write | io | corruption."""
        token = str(kind or "").strip().lower()
        if token not in {
            COMMIT_FAULT_DISK_FULL,
            COMMIT_FAULT_ENOSPC_MID,
            COMMIT_FAULT_IO,
            COMMIT_FAULT_CORRUPTION,
            "",
        }:
            raise ValueError(f"unknown commit fault: {kind!r}")
        if sticky:
            self.sticky_commit_fault = token
        else:
            self.fail_next_commit = token
            if token == COMMIT_FAULT_ENOSPC_MID:
                self._mid_write_enospc_armed = True

    def inject_block_corruption(self, block_hash: str) -> None:
        self.corrupt_block_hashes.add(str(block_hash or "").strip())

    def inject_account_corruption(self, address: str) -> None:
        self.corrupt_account_addresses.add(str(address or "").strip().lower())

    def inject_tip_orphan(self, *, height: int, head_hash: str) -> None:
        """Point tip ahead of missing body (simulates crash mid-batch WAL hole)."""
        self._tip = TipMeta(
            height=int(height),
            head_hash=str(head_hash or ""),
            state_root=self._state_root,
        )
        self._flush_ok = False
        self._crash_pending = True

    def set_finalized_height(self, height: int) -> None:
        self._finalized_height = max(0, int(height))

    def finalized_height(self) -> int:
        return int(self._finalized_height)

    def _raise_commit_fault_if_armed(self) -> None:
        fault = self.sticky_commit_fault or self.fail_next_commit
        if not fault:
            return
        if not self.sticky_commit_fault:
            self.fail_next_commit = ""
        if fault == COMMIT_FAULT_ENOSPC_MID:
            # Deferred until after ephemeral staging inside commit().
            self._mid_write_enospc_armed = True
            return
        if fault in (COMMIT_FAULT_DISK_FULL,):
            self._flush_ok = False
            raise StorageFullError(
                "ENOSPC: No space left on device",
                reason_code="disk_full",
            )
        if fault == COMMIT_FAULT_IO:
            self._flush_ok = False
            raise StorageUnavailableError("io error", reason_code="io")
        if fault == COMMIT_FAULT_CORRUPTION:
            self._flush_ok = False
            raise StorageCorruptionError("commit corrupt", reason_code="corruption")

    def _consume_mid_write_enospc(self) -> bool:
        if self._mid_write_enospc_armed:
            self._mid_write_enospc_armed = False
            if not self.sticky_commit_fault:
                self.fail_next_commit = ""
            return True
        if self.fail_next_commit == COMMIT_FAULT_ENOSPC_MID:
            self.fail_next_commit = ""
            return True
        return False

    def _maybe_stage_fault(self, stage: str) -> None:
        if self.fail_next_stage and self.fail_next_stage == stage:
            self.fail_next_stage = ""
            raise StorageUnavailableError(
                f"injected stage fault at {stage}",
                reason_code="stage_fault",
            )

    # ── StoragePort composite ────────────────────────────────────────────────

    @property
    def blocks(self) -> "FakeStorage":
        return self

    @property
    def state(self) -> "FakeStorage":
        return self

    @property
    def meta(self) -> "FakeStorage":
        return self

    @property
    def health(self) -> "FakeStorage":
        return self

    def begin_block_commit(
        self,
        *,
        expected_parent: str = "",
        expected_tip_height: int = -1,
    ) -> FakeStorageUnitOfWork:
        return FakeStorageUnitOfWork(
            self,
            expected_parent=expected_parent,
            expected_tip_height=expected_tip_height,
        )

    # ── BlockStorePort ───────────────────────────────────────────────────────

    def tip_height(self) -> int:
        return int(self._tip.height)

    def tip_hash(self) -> str:
        return str(self._tip.head_hash or "")

    def has_hash(self, block_hash: str) -> bool:
        return str(block_hash or "").strip() in self._by_hash

    def get_by_height(self, height: int) -> Optional[BlockRecord]:
        blk = self._by_height.get(int(height))
        if blk is None:
            return None
        if blk.block_hash in self.corrupt_block_hashes:
            raise StorageCorruptionError(
                f"corrupt block height={height}",
                reason_code="corrupt_block",
            )
        return blk

    def get_by_hash(self, block_hash: str) -> Optional[BlockRecord]:
        key = str(block_hash or "").strip()
        if key in self.corrupt_block_hashes:
            raise StorageCorruptionError(
                f"corrupt block hash={key[:16]}",
                reason_code="corrupt_block",
            )
        return self._by_hash.get(key)

    def iterate_heights(self, from_height: int, to_height: int) -> Sequence[BlockRecord]:
        out: List[BlockRecord] = []
        for h in range(int(from_height), int(to_height) + 1):
            blk = self.get_by_height(h)
            if blk is not None:
                out.append(blk)
        return out

    def reorg_truncate_above(self, height: int) -> None:
        cut = int(height)
        with self._lock:
            for h in list(self._by_height.keys()):
                if int(h) > cut:
                    blk = self._by_height.pop(h)
                    self._by_hash.pop(blk.block_hash, None)
                    self._txs.pop(blk.block_hash, None)
            if self._tip.height > cut:
                if cut <= 0:
                    self._tip = TipMeta(height=0, head_hash="")
                else:
                    tip_blk = self._by_height.get(cut)
                    self._tip = TipMeta(
                        height=cut,
                        head_hash=tip_blk.block_hash if tip_blk else "",
                        state_root=self._state_root,
                    )
            if self._finalized_height > cut:
                self._finalized_height = max(0, cut)

    # ── StateStorePort ───────────────────────────────────────────────────────

    def get_account(self, address: str) -> Optional[AccountRecord]:
        key = str(address or "").strip().lower()
        if key in self.corrupt_account_addresses:
            raise StorageCorruptionError(
                f"corrupt account {key[:16]}",
                reason_code="corrupt_account",
            )
        return self._accounts.get(key)

    def get_state_root(self) -> str:
        return str(self._state_root or "")

    def get_state_root_baseline(self) -> int:
        return int(self._state_root_baseline)

    def set_state_root_baseline(self, height: int) -> None:
        self._state_root_baseline = int(height)

    def get_balance(self, address: str) -> float:
        from runtime.amount import from_satoshi_float

        rec = self.get_account(address)
        if rec is None:
            return 0.0
        return float(from_satoshi_float(int(rec.balance_satoshi)))

    def get_balance_satoshi(self, address: str) -> int:
        rec = self.get_account(address)
        return int(rec.balance_satoshi) if rec is not None else 0

    def get_nonce(self, address: str) -> int:
        rec = self.get_account(address)
        return int(rec.nonce) if rec is not None else 0

    def get_all_accounts(self) -> Sequence[Mapping[str, Any]]:
        return [dict(a.to_mapping(), address=a.address) for a in self._accounts.values()]

    def get_total_supply(self) -> float:
        from runtime.amount import from_satoshi_float

        total = sum(int(a.balance_satoshi) for a in self._accounts.values())
        return float(from_satoshi_float(total))

    def compute_state_root(self) -> str:
        return str(self._state_root or "")

    def balance_delta(self, address: str, delta: float) -> None:
        from runtime.amount import to_satoshi

        self.balance_delta_satoshi(address, int(to_satoshi(delta)))

    def balance_delta_satoshi(self, address: str, delta_sat: int) -> None:
        key = str(address or "").strip().lower()
        cur = self._accounts.get(key)
        sat = int(cur.balance_satoshi) if cur else 0
        sat = max(0, sat + int(delta_sat))
        nonce = int(cur.nonce) if cur else 0
        code = cur.code if cur else ""
        storage_json = cur.storage_json if cur else "{}"
        self._accounts[key] = AccountRecord(
            address=key,
            balance_satoshi=sat,
            nonce=nonce,
            code=code,
            storage_json=storage_json,
        )

    def update_balance(self, address: str, delta: float) -> float:
        self.balance_delta(address, delta)
        return self.get_balance(address)

    def set_balance(self, address: str, balance: int) -> None:
        from runtime.amount import to_satoshi

        if isinstance(balance, bool):
            raise TypeError("bool is not an amount")
        key = str(address or "").strip().lower()
        cur = self._accounts.get(key)
        self._accounts[key] = AccountRecord(
            address=key,
            balance_satoshi=int(to_satoshi(balance)),
            nonce=int(cur.nonce) if cur else 0,
            code=cur.code if cur else "",
            storage_json=cur.storage_json if cur else "{}",
        )

    def nonce_increment(self, address: str) -> int:
        key = str(address or "").strip().lower()
        cur = self._accounts.get(key)
        nonce = (int(cur.nonce) if cur else 0) + 1
        self._accounts[key] = AccountRecord(
            address=key,
            balance_satoshi=int(cur.balance_satoshi) if cur else 0,
            nonce=nonce,
            code=cur.code if cur else "",
            storage_json=cur.storage_json if cur else "{}",
        )
        return nonce

    def increment_nonce(self, address: str) -> int:
        return self.nonce_increment(address)

    def save_account(
        self,
        address: str,
        balance: float = 0.0,
        nonce: int = 0,
        code: Any = None,
        storage: Any = None,
    ) -> None:
        from runtime.amount import to_satoshi

        key = str(address or "").strip().lower()
        storage_json = "{}" if storage is None else (
            storage if isinstance(storage, str) else str(storage)
        )
        self._accounts[key] = AccountRecord(
            address=key,
            balance_satoshi=int(to_satoshi(balance)),
            nonce=int(nonce),
            code=str(code or ""),
            storage_json=storage_json,
        )

    def reset_accounts_from_alloc(
        self, alloc: Mapping[str, Any], *, _in_atomic: bool = False
    ) -> None:
        self._accounts.clear()
        for addr, amount in (alloc or {}).items():
            self.set_balance(str(addr), float(amount))

    # ── MetaStorePort ────────────────────────────────────────────────────────

    def get_validators(self, active_only: bool = True) -> Sequence[Mapping[str, Any]]:
        _ = active_only
        return list(self._validators)

    def get_checkpoint(self, epoch: int) -> Optional[Mapping[str, Any]]:
        return self._checkpoints.get(int(epoch))

    def put_checkpoint(self, epoch: int, data: Mapping[str, Any]) -> None:
        self._checkpoints[int(epoch)] = dict(data)

    def get_meta(self, key: str, default: Any = None) -> Any:
        return self._checkpoints.get(f"meta:{key}", default)

    def set_meta(self, key: str, value: Any) -> None:
        self._checkpoints[f"meta:{key}"] = value

    def get_stats(self) -> Mapping[str, Any]:
        return {"tip": self.tip_height(), "accounts": len(self._accounts)}

    def get_burn_stats(self) -> Mapping[str, Any]:
        return {"total_burned": 0.0}

    def get_chain_metrics(self, window: int = 0) -> Mapping[str, Any]:
        _ = window
        return {"height": self.tip_height()}

    def save_block(self, block: Mapping[str, Any]) -> bool:
        rec = BlockRecord.from_mapping(block)
        self._by_height[rec.height] = rec
        self._by_hash[rec.block_hash] = rec
        self._tip = TipMeta(height=rec.height, head_hash=rec.block_hash)
        return True

    def truncate_all_blocks(self) -> None:
        self._by_height.clear()
        self._by_hash.clear()
        self._txs.clear()
        self._tip = TipMeta(height=0, head_hash="")

    def truncate_blocks_above(self, height: int) -> Any:
        self.reorg_truncate_above(int(height))
        return int(height)

    def get_transaction(self, tx_hash: str) -> Optional[Mapping[str, Any]]:
        return None

    def record_state_root_mismatch(self, *args: Any, **kwargs: Any) -> None:
        return None

    def get_block(self, height: int) -> Optional[Mapping[str, Any]]:
        blk = self.get_by_height(int(height))
        return dict(blk.to_mapping()) if blk else None

    def get_block_by_hash(self, block_hash: str) -> Optional[Mapping[str, Any]]:
        blk = self.get_by_hash(str(block_hash or ""))
        return dict(blk.to_mapping()) if blk else None

    def get_last_block(self) -> Optional[Mapping[str, Any]]:
        if self._tip.height <= 0 and not self._by_height:
            return None
        return self.get_block(self._tip.height)

    def get_chain_tip(self) -> int:
        return self.tip_height()

    def atomic(self):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            yield self

        return _cm()

    def unwrap(self) -> "FakeStorage":
        return self

    # ── StorageHealthPort ────────────────────────────────────────────────────

    def ping(self) -> bool:
        return True

    def approximate_size(self) -> int:
        return int(self._approx_size) + len(self._by_hash) + len(self._accounts)

    def last_flush_ok(self) -> bool:
        return bool(self._flush_ok)

    # ── Tip repair / crash reopen ────────────────────────────────────────────

    def repair_tip_consistency(self) -> None:
        """Mirror Rocks adapter: rewind tip to last height with a body."""
        tip_h = int(self._tip.height)
        if tip_h <= 0:
            return
        consistent = tip_h
        while consistent > 0:
            if consistent in self._by_height:
                break
            consistent -= 1
        if consistent == tip_h:
            return
        if consistent <= 0:
            self._tip = TipMeta(height=0, head_hash="", state_root="")
            self._finalized_height = 0
            self._flush_ok = True
            self._crash_pending = False
            return
        tip_blk = self._by_height[consistent]
        self._tip = TipMeta(
            height=consistent,
            head_hash=tip_blk.block_hash,
            state_root=self._state_root,
        )
        if self._finalized_height > consistent:
            self._finalized_height = consistent
        self._flush_ok = True
        self._crash_pending = False

    def reopen_after_crash(self) -> "FakeStorage":
        """Clone last committed durable state and run tip repair on open."""
        clone = FakeStorage()
        with self._lock:
            clone._by_height = copy.deepcopy(self._by_height)
            clone._by_hash = copy.deepcopy(self._by_hash)
            clone._txs = copy.deepcopy(self._txs)
            clone._accounts = copy.deepcopy(self._accounts)
            clone._tip = TipMeta(
                height=self._tip.height,
                head_hash=self._tip.head_hash,
                state_root=self._tip.state_root,
            )
            clone._state_root = self._state_root
            clone._state_root_baseline = self._state_root_baseline
            clone._finalized_height = self._finalized_height
            clone._validators = [dict(v) for v in self._validators]
            clone._checkpoints = copy.deepcopy(self._checkpoints)
            clone._crash_pending = bool(self._crash_pending)
            clone.corrupt_block_hashes = set(self.corrupt_block_hashes)
            clone.corrupt_account_addresses = set(self.corrupt_account_addresses)
        clone.repair_tip_consistency()
        return clone

    def snapshot_counts(self) -> Dict[str, int]:
        """Observability for stress assertions (heights / hashes / accounts)."""
        return {
            "heights": len(self._by_height),
            "hashes": len(self._by_hash),
            "accounts": len(self._accounts),
            "tip_height": int(self._tip.height),
            "finalized": int(self._finalized_height),
            "commits": int(self._commit_count),
            "enospc_aborts": int(self._enospc_aborts),
        }
