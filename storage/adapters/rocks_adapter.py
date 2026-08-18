"""RocksDB storage adapter (ADR 0006 Step B).

Implements ``StoragePort`` over ``RocksChainStore`` / Hybrid-like façades.
Domain never sees CF names, keycodec, or ``RocksWriteBatch`` — those stay here.

Atomic tip advance:
- Prefer one ``store.atomic()`` WriteBatch: block body + indexes + account
  writeback (+ tip meta already written by ``_insert_block``).
- Fallback: ``persist_block_atomic`` then ``commit_writeback_bundle``.
- ``sync_writes`` / WAL durability remain engine-owned (store open flags).

Crash recovery:
- On open, tip must resolve to an existing body; otherwise rewind to the last
  consistent height or fail-closed ``StorageCorruptionError``.
"""

from __future__ import annotations

import errno
import logging
from contextlib import AbstractContextManager
from typing import Any, Dict, List, Mapping, Optional, Sequence

from storage.types import (
    AccountRecord,
    BlockRecord,
    StorageConflictError,
    StorageCorruptionError,
    StorageError,
    StorageFullError,
    StorageUnavailableError,
    TipMeta,
)

logger = logging.getLogger("Storage.RocksAdapter")

__all__ = ["RocksDBStorageAdapter", "map_engine_error"]


def map_engine_error(exc: BaseException) -> StorageError:
    """Map OS / Rocks / decode failures to typed storage errors."""
    msg = str(exc or type(exc).__name__)
    low = msg.lower()
    en = getattr(exc, "errno", None)
    if (
        en == errno.ENOSPC
        or getattr(exc, "winerror", None) == 112  # ERROR_DISK_FULL
        or "no space" in low
        or "enospc" in low
        or "disk full" in low
        or "not enough space" in low
    ):
        return StorageFullError(msg, reason_code="disk_full")
    if (
        "corrupt" in low
        or "checksum" in low
        or "corruption" in low
        or ("json" in low and ("decode" in low or "expect" in low or "parse" in low))
        or "utf-8" in low
        or "invalid utf" in low
        or "truncated" in low
    ):
        return StorageCorruptionError(msg, reason_code="corruption")
    return StorageUnavailableError(msg, reason_code="unavailable")


# Back-compat alias used by unit tests.
_map_engine_error = map_engine_error


def _coerce_block(block: BlockRecord | Mapping[str, Any]) -> BlockRecord:
    if isinstance(block, BlockRecord):
        return block
    return BlockRecord.from_mapping(block)


def _normalize_accounts(
    accounts: Sequence[AccountRecord] | Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(accounts, Mapping):
        for addr, row in accounts.items():
            if isinstance(row, AccountRecord):
                rec = row
            else:
                rec = AccountRecord.from_mapping(str(addr), row)
            if not rec.address:
                continue
            out[rec.address] = dict(rec.to_mapping())
        return out
    for row in accounts or ():
        if isinstance(row, AccountRecord):
            rec = row
        elif isinstance(row, Mapping):
            rec = AccountRecord.from_mapping(str(row.get("address") or ""), row)
        else:
            continue
        if not rec.address:
            continue
        out[rec.address] = dict(rec.to_mapping())
    return out


def _block_burn_fields(blk: BlockRecord) -> tuple[float, str]:
    from runtime.amount import money_abs

    payload = blk.payload or {}
    raw = payload.get("total_burned")
    if raw is None:
        raw = payload.get("burned_amount") or 0.0
    burned = money_abs(raw, field="burned")
    burn_addr = str(payload.get("burn_address") or "")
    return burned, burn_addr


class _RocksUoW:
    """Staged unit of work; durable only after successful ``commit()``."""

    def __init__(
        self,
        adapter: "RocksDBStorageAdapter",
        *,
        expected_parent: str,
        expected_tip_height: int,
    ) -> None:
        self._adapter = adapter
        self._expected_parent = str(expected_parent or "")
        self._expected_tip_height = int(expected_tip_height)
        self._block: Optional[BlockRecord] = None
        self._txs: List[Dict[str, Any]] = []
        self._accounts: Dict[str, Dict[str, Any]] = {}
        self._tip: Optional[TipMeta] = None
        self._aborted = False
        self._committed = False

    def write_block(self, block: BlockRecord | Mapping[str, Any]) -> None:
        self._ensure_open()
        self._block = _coerce_block(block)

    def write_transactions(self, transactions: Sequence[Mapping[str, Any]]) -> None:
        self._ensure_open()
        self._txs = [dict(t) for t in (transactions or ()) if isinstance(t, Mapping)]

    def write_state_delta(
        self,
        accounts: Sequence[AccountRecord] | Mapping[str, Mapping[str, Any]],
    ) -> None:
        self._ensure_open()
        self._accounts.update(_normalize_accounts(accounts))

    def set_tip(self, tip: TipMeta) -> None:
        self._ensure_open()
        if not isinstance(tip, TipMeta):
            raise StorageUnavailableError(
                "set_tip requires TipMeta", reason_code="invalid_tip"
            )
        self._tip = tip

    def commit(self) -> None:
        self._ensure_open()
        adapter = self._adapter
        store = adapter._store

        tip_h, tip_hash = adapter._read_tip_snapshot()

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

        blk = self._block
        hh = str(blk.block_hash or "")
        # Idempotent retry (import / crash-after-ack culture).
        try:
            if hh and store.get_block_by_hash(hh) is not None:
                self._committed = True
                adapter._last_flush_ok = True
                return
        except Exception as exc:
            raise map_engine_error(exc) from exc

        blk_map = dict(blk.to_mapping())
        if self._tip is not None:
            # Keep payload tip fields coherent with TipMeta fence.
            if self._tip.head_hash:
                blk_map["hash"] = str(self._tip.head_hash)
                blk_map["block_hash"] = str(self._tip.head_hash)
            if self._tip.state_root:
                blk_map["state_root"] = str(self._tip.state_root)
            blk_map["height"] = int(self._tip.height or blk.height)

        burned, burn_addr = _block_burn_fields(blk)
        txs = list(self._txs)
        accounts = dict(self._accounts)

        try:
            adapter._commit_block_bundle(
                block=blk_map,
                transactions=txs,
                accounts=accounts,
                burned_amount=burned,
                burn_address=burn_addr,
                tip=self._tip,
            )
            adapter._last_flush_ok = True
            self._committed = True
        except StorageError:
            adapter._last_flush_ok = False
            raise
        except Exception as exc:
            adapter._last_flush_ok = False
            raise map_engine_error(exc) from exc

    def abort(self) -> None:
        self._aborted = True
        self._block = None
        self._txs = []
        self._accounts = {}
        self._tip = None

    def _ensure_open(self) -> None:
        if self._aborted:
            raise StorageUnavailableError("uow aborted", reason_code="aborted")
        if self._committed:
            raise StorageUnavailableError(
                "uow already committed", reason_code="committed"
            )


class RocksDBStorageAdapter:
    """``StoragePort`` implementation over RocksChainStore / HybridDatabase-like store."""

    def __init__(
        self,
        store: Any,
        *,
        fail_closed_repair: bool = True,
        repair_on_open: bool = True,
    ) -> None:
        if store is None:
            raise StorageUnavailableError(
                "store is required", reason_code="missing_store"
            )
        self._store = store
        self._fail_closed_repair = bool(fail_closed_repair)
        self._last_flush_ok = True
        if repair_on_open:
            self.repair_tip_consistency()

    # ── StoragePort composite ────────────────────────────────────────────────

    @property
    def blocks(self) -> "RocksDBStorageAdapter":
        return self

    @property
    def state(self) -> "RocksDBStorageAdapter":
        return self

    @property
    def meta(self) -> "RocksDBStorageAdapter":
        return self

    @property
    def health(self) -> "RocksDBStorageAdapter":
        return self

    def begin_block_commit(
        self,
        *,
        expected_parent: str = "",
        expected_tip_height: int = -1,
    ) -> _RocksUoW:
        return _RocksUoW(
            self,
            expected_parent=expected_parent,
            expected_tip_height=expected_tip_height,
        )

    # ── Internal tip / commit helpers ────────────────────────────────────────

    def _read_tip_snapshot(self) -> tuple[int, str]:
        store = self._store
        try:
            tip_h = int(store.get_chain_tip() or 0)
        except Exception as exc:
            raise map_engine_error(exc) from exc
        tip_hash = ""
        try:
            last = store.get_last_block()
            if isinstance(last, Mapping):
                tip_hash = str(last.get("hash") or last.get("block_hash") or "")
        except Exception as exc:
            raise map_engine_error(exc) from exc
        return tip_h, tip_hash

    def _store_batch_open(self) -> bool:
        """True when caller already holds Rocks WriteBatch or SQLite transaction.

        Nested ``atomic()`` would replace ``_pending_batch`` and break tip fence —
        join the open batch instead (ADR 0006 D–E cutover).
        """
        store = self._store
        if getattr(store, "_pending_batch", None) is not None:
            return True
        core = getattr(store, "_core", None)
        if core is not None and getattr(core, "_pending_batch", None) is not None:
            return True
        conn = getattr(store, "conn", None)
        if conn is not None:
            try:
                if bool(getattr(conn, "in_transaction", False)):
                    return True
            except Exception as exc:
                logger.warning(
                    "in_transaction probe failed; assume open batch (no nested atomic): %s",
                    exc,
                )
                return True
        return False

    def _persist_locked_into_batch(
        self,
        *,
        block: Dict[str, Any],
        transactions: List[Dict[str, Any]],
        accounts: Dict[str, Dict[str, Any]],
        burned_amount: float,
        burn_address: str,
        tip: Optional[TipMeta],
    ) -> None:
        from runtime.amount import money_abs

        store = self._store
        if not hasattr(store, "_persist_block_locked"):
            raise StorageUnavailableError(
                "store has no _persist_block_locked",
                reason_code="no_persist_locked",
            )
        height = int(block.get("height") or 0)
        store._persist_block_locked(
            dict(block),
            list(transactions),
            money_abs(burned_amount, field="burned"),
            str(burn_address or ""),
        )
        if accounts:
            self._writeback_accounts(
                accounts,
                block_height=height,
                inside_atomic=True,
            )
        self._apply_tip_meta(tip, block)

    def _commit_block_bundle(
        self,
        *,
        block: Dict[str, Any],
        transactions: List[Dict[str, Any]],
        accounts: Dict[str, Dict[str, Any]],
        burned_amount: float,
        burn_address: str,
        tip: Optional[TipMeta],
    ) -> None:
        """Persist block (+ optional accounts) with best-effort single-batch atomicity."""
        from runtime.amount import money_abs

        store = self._store

        # Join outer Blockchain.db.atomic() / Hybrid→Rocks batch — no nested WriteBatch.
        if self._store_batch_open() and hasattr(store, "_persist_block_locked"):
            self._persist_locked_into_batch(
                block=block,
                transactions=transactions,
                accounts=accounts,
                burned_amount=burned_amount,
                burn_address=burn_address,
                tip=tip,
            )
            return

        # Standalone UoW: one Rocks/SQLite atomic via store.atomic() + locked helpers.
        if hasattr(store, "atomic") and hasattr(store, "_persist_block_locked"):
            cm = store.atomic()
            if isinstance(cm, AbstractContextManager) or hasattr(cm, "__enter__"):
                with cm:
                    self._persist_locked_into_batch(
                        block=block,
                        transactions=transactions,
                        accounts=accounts,
                        burned_amount=burned_amount,
                        burn_address=burn_address,
                        tip=tip,
                    )
                return

        # Fallback: public persist_block_atomic then writeback (two store commits).
        height = int(block.get("height") or 0)
        ok = False
        try:
            ok = bool(
                store.persist_block_atomic(
                    dict(block),
                    list(transactions),
                    burned_amount=money_abs(burned_amount or 0.0, field="burned"),
                    burn_address=str(burn_address or ""),
                )
            )
        except Exception as exc:
            raise map_engine_error(exc) from exc
        if not ok:
            raise StorageUnavailableError(
                "persist_block_atomic returned False",
                reason_code="persist_failed",
            )
        if accounts:
            self._writeback_accounts(
                accounts,
                block_height=height,
                inside_atomic=False,
            )
        self._apply_tip_meta(tip, block)

    def _writeback_accounts(
        self,
        accounts: Dict[str, Dict[str, Any]],
        *,
        block_height: int,
        inside_atomic: bool,
    ) -> None:
        store = self._store
        if hasattr(store, "commit_writeback_bundle"):
            store.commit_writeback_bundle(
                dict(accounts),
                None,
                block_height=int(block_height),
                tx_hash="",
                timestamp=0,
            )
            return
        if hasattr(store, "commit_writeback_accounts"):
            store.commit_writeback_accounts(dict(accounts))
            return
        if inside_atomic and hasattr(store, "_save_account_row"):
            for addr, row in accounts.items():
                payload = dict(row)
                payload["address"] = str(addr)
                store._save_account_row(payload)
            return
        raise StorageUnavailableError(
            "store has no writeback path",
            reason_code="no_writeback",
        )

    def _apply_tip_meta(self, tip: Optional[TipMeta], block: Mapping[str, Any]) -> None:
        """Optional explicit tip meta; ``_insert_block`` already fences tip on Rocks."""
        store = self._store
        if tip is None:
            return
        hh = str(tip.head_hash or block.get("hash") or block.get("block_hash") or "")
        height = int(tip.height)
        if hasattr(store, "set_chain_tip_meta"):
            store.set_chain_tip_meta(height, hh)
            return
        if hasattr(store, "set_meta"):
            store.set_meta("chain_tip", height)
            if hh:
                # chain_tip_hash is stored as raw bytes in RocksChainStore._insert_block;
                # set_meta JSON-encodes — only write height via set_meta for parity.
                pass
            if tip.state_root and hasattr(store, "set_meta"):
                store.set_meta("live_state_root", str(tip.state_root))
                store.set_meta("live_state_root_height", height)

    # ── BlockStorePort ───────────────────────────────────────────────────────

    def tip_height(self) -> int:
        try:
            return int(self._store.get_chain_tip() or 0)
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def tip_hash(self) -> str:
        try:
            last = self._store.get_last_block()
            if isinstance(last, Mapping):
                return str(last.get("hash") or last.get("block_hash") or "")
            return ""
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def has_hash(self, block_hash: str) -> bool:
        key = str(block_hash or "").strip()
        if not key:
            return False
        try:
            return self._store.get_block_by_hash(key) is not None
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def get_by_height(self, height: int) -> Optional[BlockRecord]:
        try:
            raw = self._store.get_block(int(height))
        except Exception as exc:
            raise map_engine_error(exc) from exc
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise StorageCorruptionError(
                f"non-mapping block at height={height}",
                reason_code="corrupt_block",
            )
        return BlockRecord.from_mapping(raw)

    def get_by_hash(self, block_hash: str) -> Optional[BlockRecord]:
        key = str(block_hash or "").strip()
        if not key:
            return None
        try:
            raw = self._store.get_block_by_hash(key)
        except Exception as exc:
            raise map_engine_error(exc) from exc
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise StorageCorruptionError(
                f"non-mapping block hash={key[:16]}",
                reason_code="corrupt_block",
            )
        return BlockRecord.from_mapping(raw)

    def iterate_heights(self, from_height: int, to_height: int) -> Sequence[BlockRecord]:
        lo = int(from_height)
        hi = int(to_height)
        if hi < lo:
            return []
        out: List[BlockRecord] = []
        for h in range(lo, hi + 1):
            blk = self.get_by_height(h)
            if blk is not None:
                out.append(blk)
        return out

    def reorg_truncate_above(self, height: int) -> None:
        try:
            self._store.reorg_truncate_above(int(height))
        except Exception as exc:
            raise map_engine_error(exc) from exc

    # ── StateStorePort ───────────────────────────────────────────────────────

    def get_account(self, address: str) -> Optional[Mapping[str, Any]]:
        addr = str(address or "").strip()
        if not addr:
            return None
        try:
            raw = self._store.get_account(addr)
        except Exception as exc:
            raise map_engine_error(exc) from exc
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise StorageCorruptionError(
                "corrupt account row",
                reason_code="corrupt_account",
            )
        out = dict(raw)
        out.setdefault("address", addr)
        return out

    def get_account_record(self, address: str) -> Optional[AccountRecord]:
        raw = self.get_account(address)
        if raw is None:
            return None
        return AccountRecord.from_mapping(str(address or ""), raw)

    def get_state_root(self) -> str:
        store = self._store
        if hasattr(store, "get_live_state_root_meta"):
            try:
                root, _h = store.get_live_state_root_meta()
                return str(root or "")
            except Exception as exc:
                raise map_engine_error(exc) from exc
        if hasattr(store, "get_state_root"):
            try:
                return str(store.get_state_root() or "")
            except Exception as exc:
                raise map_engine_error(exc) from exc
        if hasattr(store, "get_meta"):
            try:
                return str(store.get_meta("live_state_root") or "")
            except Exception as exc:
                raise map_engine_error(exc) from exc
        return ""

    def get_state_root_baseline(self) -> int:
        store = self._store
        if hasattr(store, "get_state_root_baseline"):
            try:
                return int(store.get_state_root_baseline() or 0)
            except Exception as exc:
                raise map_engine_error(exc) from exc
        if hasattr(store, "get_meta"):
            try:
                return int(store.get_meta("state_root_baseline") or 0)
            except Exception as exc:
                raise map_engine_error(exc) from exc
        return 0

    def get_balance(self, address: str) -> float:
        try:
            return float(self._store.get_balance(str(address or "")) or 0.0)
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def get_balance_satoshi(self, address: str) -> int:
        try:
            if hasattr(self._store, "get_balance_satoshi"):
                return int(self._store.get_balance_satoshi(str(address or "")) or 0)
            from runtime.amount import to_satoshi

            return int(to_satoshi(self.get_balance(address)))
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def get_nonce(self, address: str) -> int:
        try:
            return int(self._store.get_nonce(str(address or "")) or 0)
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def get_all_accounts(self) -> Sequence[Mapping[str, Any]]:
        try:
            rows = self._store.get_all_accounts()
            return [dict(r) for r in (rows or []) if isinstance(r, Mapping)]
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def get_total_supply(self) -> float:
        try:
            return float(self._store.get_total_supply() or 0.0)
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def compute_state_root(self) -> str:
        try:
            if hasattr(self._store, "compute_state_root"):
                return str(self._store.compute_state_root() or "")
            from execution.state_root import compute_db_state_root

            return str(compute_db_state_root(list(self.get_all_accounts())) or "")
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def balance_delta(self, address: str, delta: int) -> None:
        if isinstance(delta, bool):
            raise TypeError("bool is not an amount")
        try:
            self._store.balance_delta(str(address or ""), delta)
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def balance_delta_satoshi(self, address: str, delta_sat: int) -> None:
        try:
            self._store.balance_delta_satoshi(str(address or ""), int(delta_sat))
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def update_balance(self, address: str, delta: int) -> float:
        if isinstance(delta, bool):
            raise TypeError("bool is not an amount")
        try:
            return float(self._store.update_balance(str(address or ""), delta))
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def set_balance(self, address: str, balance: int) -> None:
        if isinstance(balance, bool):
            raise TypeError("bool is not an amount")
        try:
            self._store.set_balance(str(address or ""), balance)
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def nonce_increment(self, address: str) -> int:
        try:
            if hasattr(self._store, "nonce_increment"):
                return int(self._store.nonce_increment(str(address or "")))
            return int(self._store.increment_nonce(str(address or "")))
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def increment_nonce(self, address: str) -> int:
        try:
            if hasattr(self._store, "increment_nonce"):
                return int(self._store.increment_nonce(str(address or "")))
            return int(self.nonce_increment(address))
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def save_account(
        self,
        address: str,
        balance: int = 0,
        nonce: int = 0,
        code: Any = None,
        storage: Any = None,
    ) -> None:
        if isinstance(balance, bool):
            raise TypeError("bool is not an amount")
        try:
            self._store.save_account(
                str(address or ""),
                balance=balance,
                nonce=int(nonce),
                code=code,
                storage=storage,
            )
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def reset_accounts_from_alloc(
        self, alloc: Mapping[str, Any], *, _in_atomic: bool = False
    ) -> None:
        try:
            self._store.reset_accounts_from_alloc(dict(alloc or {}), _in_atomic=_in_atomic)
        except Exception as exc:
            raise map_engine_error(exc) from exc

    # ── MetaStorePort ────────────────────────────────────────────────────────

    def get_validators(self, active_only: bool = True) -> Sequence[Mapping[str, Any]]:
        store = self._store
        if not hasattr(store, "get_validators"):
            return []
        try:
            rows = store.get_validators(active_only=bool(active_only))
            return [dict(r) for r in (rows or []) if isinstance(r, Mapping)]
        except TypeError:
            try:
                rows = store.get_validators()
                return [dict(r) for r in (rows or []) if isinstance(r, Mapping)]
            except Exception as exc:
                raise map_engine_error(exc) from exc
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def get_checkpoint(self, epoch: int) -> Optional[Mapping[str, Any]]:
        store = self._store
        if hasattr(store, "get_checkpoint"):
            try:
                row = store.get_checkpoint(int(epoch))
                return dict(row) if isinstance(row, Mapping) else None
            except Exception as exc:
                raise map_engine_error(exc) from exc
        if hasattr(store, "get_meta"):
            try:
                row = store.get_meta(f"checkpoint:{int(epoch)}")
                return dict(row) if isinstance(row, Mapping) else None
            except Exception as exc:
                raise map_engine_error(exc) from exc
        return None

    def put_checkpoint(self, epoch: int, data: Mapping[str, Any]) -> None:
        store = self._store
        payload = dict(data or {})
        if hasattr(store, "put_checkpoint"):
            try:
                store.put_checkpoint(int(epoch), payload)
                return
            except Exception as exc:
                raise map_engine_error(exc) from exc
        if hasattr(store, "set_meta"):
            try:
                store.set_meta(f"checkpoint:{int(epoch)}", payload)
                return
            except Exception as exc:
                raise map_engine_error(exc) from exc
        raise StorageUnavailableError(
            "store has no checkpoint path",
            reason_code="no_checkpoint",
        )

    def get_meta(self, key: str, default: Any = None) -> Any:
        try:
            if hasattr(self._store, "get_meta"):
                return self._store.get_meta(str(key), default)
            return default
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def set_meta(self, key: str, value: Any) -> None:
        try:
            self._store.set_meta(str(key), value)
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def get_stats(self) -> Mapping[str, Any]:
        try:
            if hasattr(self._store, "get_stats"):
                return dict(self._store.get_stats() or {})
            return {}
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def get_burn_stats(self) -> Mapping[str, Any]:
        try:
            if hasattr(self._store, "get_burn_stats"):
                return dict(self._store.get_burn_stats() or {})
            return {}
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def get_chain_metrics(self, window: int = 0) -> Mapping[str, Any]:
        try:
            if hasattr(self._store, "get_chain_metrics"):
                if window:
                    return dict(self._store.get_chain_metrics(window) or {})
                return dict(self._store.get_chain_metrics() or {})
            return {}
        except Exception as exc:
            raise map_engine_error(exc) from exc

    # ── Block surgery / legacy dict mirrors (Wave F) ──────────────────────────

    def save_block(self, block: Mapping[str, Any]) -> bool:
        try:
            return bool(self._store.save_block(dict(block)))
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def truncate_all_blocks(self) -> None:
        try:
            self._store.truncate_all_blocks()
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def truncate_blocks_above(self, height: int) -> Any:
        try:
            return self._store.truncate_blocks_above(int(height))
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def get_transaction(self, tx_hash: str) -> Optional[Mapping[str, Any]]:
        try:
            row = self._store.get_transaction(str(tx_hash or ""))
            return dict(row) if isinstance(row, Mapping) else None
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def record_state_root_mismatch(self, *args: Any, **kwargs: Any) -> None:
        if not hasattr(self._store, "record_state_root_mismatch"):
            return
        try:
            self._store.record_state_root_mismatch(*args, **kwargs)
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def get_block(self, height: int) -> Optional[Mapping[str, Any]]:
        """Legacy dict mirror used by Blockchain / tip_safety readers."""
        try:
            raw = self._store.get_block(int(height))
            return dict(raw) if isinstance(raw, Mapping) else None
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def get_block_by_hash(self, block_hash: str) -> Optional[Mapping[str, Any]]:
        try:
            raw = self._store.get_block_by_hash(str(block_hash or ""))
            return dict(raw) if isinstance(raw, Mapping) else None
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def get_last_block(self) -> Optional[Mapping[str, Any]]:
        try:
            raw = self._store.get_last_block()
            return dict(raw) if isinstance(raw, Mapping) else None
        except Exception as exc:
            raise map_engine_error(exc) from exc

    def get_chain_tip(self) -> int:
        return self.tip_height()

    def atomic(self) -> AbstractContextManager[Any]:
        store = self._store
        if not hasattr(store, "atomic"):
            raise StorageUnavailableError(
                "store has no atomic()", reason_code="no_atomic"
            )
        return store.atomic()

    def unwrap(self) -> Any:
        return self._store

    # ── StorageHealthPort ────────────────────────────────────────────────────

    def ping(self) -> bool:
        try:
            _ = self.tip_height()
            return True
        except Exception as exc:
            logger.warning("storage ping failed: %s", exc)
            return False

    def approximate_size(self) -> int:
        store = self._store
        if hasattr(store, "approximate_size"):
            try:
                return int(store.approximate_size() or 0)
            except Exception as exc:
                logger.warning("approximate_size failed: %s", exc)
                return 0
        return 0

    def last_flush_ok(self) -> bool:
        return bool(self._last_flush_ok)

    # ── Repair ───────────────────────────────────────────────────────────────

    def repair_tip_consistency(self) -> None:
        """Ensure tip points at an existing body; rewind or fail-closed."""
        store = self._store
        try:
            tip_h = int(store.get_chain_tip() or 0)
        except Exception as exc:
            raise map_engine_error(exc) from exc
        if tip_h <= 0:
            return

        consistent = int(tip_h)
        while consistent > 0:
            try:
                body = store.get_block(consistent)
            except Exception as exc:
                mapped = map_engine_error(exc)
                if isinstance(mapped, StorageCorruptionError) and self._fail_closed_repair:
                    raise mapped from exc
                body = None
            if body is not None:
                break
            consistent -= 1

        if consistent == tip_h:
            return

        logger.warning(
            "[RocksAdapter] tip #%s missing body — repair rewind to #%s",
            tip_h,
            consistent,
        )
        try:
            store.reorg_truncate_above(int(consistent))
        except Exception as exc:
            raise map_engine_error(exc) from exc

        # Verify repair landed on a body (or empty chain).
        if consistent <= 0:
            return
        try:
            body = store.get_block(consistent)
        except Exception as exc:
            raise map_engine_error(exc) from exc
        if body is None and self._fail_closed_repair:
            raise StorageCorruptionError(
                f"tip #{tip_h} orphan after crash; repair to #{consistent} failed",
                reason_code="tip_orphan",
            )
