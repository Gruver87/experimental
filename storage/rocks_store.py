#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RocksDB chain store — hot path (blocks, state, meta) via abs_native RocksEngine.

Reads are lock-free (RocksDB MVCC). Writes are serialized through WriteBatch commits.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from storage import keycodec as kc
from storage.database import Database as SqliteDatabase, observed_optional_int

logger = logging.getLogger(__name__)


def _rocks_available() -> bool:
    try:
        import abs_native  # type: ignore

        return hasattr(abs_native, "RocksEngine")
    except Exception:
        return False


class AccountCorruptError(RuntimeError):
    """Account blob present in Rocks but JSON decode failed (v1.3.65)."""


class RocksChainStore:
    """Production chain/state store backed by RocksDB (native PyO3)."""

    engine = "rocksdb"

    def __init__(
        self,
        db_path: str = "data/chainstore",
        *,
        synchronous: str = "FULL",
        block_cache_mb: int = 0,
        write_buffer_mb: int = 0,
        column_families: bool = False,
    ):
        if not _rocks_available():
            raise RuntimeError(
                "RocksDB engine requires abs_native with RocksEngine "
                "(rebuild: bash scripts/build_native.sh)"
            )
        import abs_native  # type: ignore

        self.db_path = db_path
        sync = (synchronous or "FULL").upper()
        self.synchronous = sync
        self.block_cache_mb = int(block_cache_mb or 0)
        self.write_buffer_mb = int(write_buffer_mb or 0)
        self.column_families = bool(column_families)
        self._write_lock = threading.RLock()
        self._pending_batch: Any | None = None
        os.makedirs(db_path, exist_ok=True)
        engine_kwargs = {
            "create_if_missing": True,
            "sync_writes": sync in ("FULL", "EXTRA", "STRICT"),
            "block_cache_mb": self.block_cache_mb,
            "write_buffer_mb": self.write_buffer_mb,
        }
        # Older wheels may lack column_families kwarg — only pass when supported.
        try:
            import inspect

            sig = inspect.signature(abs_native.RocksEngine)
            if "column_families" in sig.parameters:
                engine_kwargs["column_families"] = self.column_families
            elif self.column_families:
                raise RuntimeError(
                    "rocksdb_column_families requires a newer abs_native wheel"
                )
        except (TypeError, ValueError):
            if self.column_families:
                engine_kwargs["column_families"] = self.column_families
        self._engine = abs_native.RocksEngine(db_path, **engine_kwargs)
        self._schema_version = (
            "rocksdb-chain-v2-cf" if self.column_families else "rocksdb-chain-v1"
        )
        self._root_acc: Any | None = None
        self._batch_acc_dirty: dict[str, bytes | None] = {}
        self._json_decode_failures: int = 0
        self._ensure_schema()

    def _loads_json_or_none(self, raw: bytes | None, *, context: str) -> Optional[Dict]:
        """Decode a Rocks JSON blob; corrupt rows bump the fail-closed counter."""
        if raw is None:
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            self._json_decode_failures += 1
            logger.warning(
                "[RocksStore] corrupt %s (decode_failures=%s): %s",
                context,
                self._json_decode_failures,
                exc,
            )
            return None
        return data if isinstance(data, dict) else None

    def _loads_account_blob_or_none(self, raw: bytes | None, *, context: str) -> Optional[Dict]:
        """Dual-decode account row: ABAR binary (v1.3.147) or legacy JSON."""
        if raw is None:
            return None
        if len(raw) >= 4 and raw[:4] == b"ABAR":
            try:
                import abs_native as _abs

                if hasattr(_abs, "unpack_account_row"):
                    data = json.loads(_abs.unpack_account_row(raw))
                    return data if isinstance(data, dict) else None
            except Exception as exc:
                self._json_decode_failures += 1
                logger.warning(
                    "[RocksStore] corrupt %s ABAR (decode_failures=%s): %s",
                    context,
                    self._json_decode_failures,
                    exc,
                )
                return None
            self._json_decode_failures += 1
            logger.warning(
                "[RocksStore] corrupt %s ABAR (no native unpack)",
                context,
            )
            return None
        return self._loads_json_or_none(raw, context=context)

    def _pack_account_blob(self, row: Dict[str, Any]) -> bytes:
        """Pack account row as ABAR when native codec is present; else legacy JSON."""
        try:
            import abs_native as _abs

            if hasattr(_abs, "pack_account_row"):
                return bytes(
                    _abs.pack_account_row(json.dumps(row, ensure_ascii=False))
                )
        except Exception as exc:
            logger.warning(
                "[RocksStore] native pack_account_row failed, JSON fallback: %s", exc
            )
        return json.dumps(row, ensure_ascii=False).encode("utf-8")

    def _loads_tx_blob_or_none(self, raw: bytes | None, *, context: str) -> Optional[Dict]:
        """Dual-decode tx row: ATXV binary (v1.3.148) or legacy JSON."""
        if raw is None:
            return None
        if len(raw) >= 4 and raw[:4] == b"ATXV":
            try:
                import abs_native as _abs

                if hasattr(_abs, "unpack_tx_row"):
                    data = json.loads(_abs.unpack_tx_row(raw))
                    return data if isinstance(data, dict) else None
            except Exception as exc:
                self._json_decode_failures += 1
                logger.warning(
                    "[RocksStore] corrupt %s ATXV (decode_failures=%s): %s",
                    context,
                    self._json_decode_failures,
                    exc,
                )
                return None
            self._json_decode_failures += 1
            logger.warning(
                "[RocksStore] corrupt %s ATXV (no native unpack)",
                context,
            )
            return None
        return self._loads_json_or_none(raw, context=context)

    def _pack_tx_blob(self, row: Dict[str, Any]) -> bytes:
        """Pack tx row as ATXV when native codec is present; else legacy JSON."""
        try:
            import abs_native as _abs

            if hasattr(_abs, "pack_tx_row"):
                return bytes(_abs.pack_tx_row(json.dumps(row, ensure_ascii=False)))
        except Exception as exc:
            logger.warning(
                "[RocksStore] native pack_tx_row failed, JSON fallback: %s", exc
            )
        return json.dumps(row, ensure_ascii=False).encode("utf-8")

    def _loads_block_blob_or_none(self, raw: bytes | None, *, context: str) -> Optional[Dict]:
        """Dual-decode block row: ABLK binary (v1.3.149) or legacy JSON."""
        if raw is None:
            return None
        if len(raw) >= 4 and raw[:4] == b"ABLK":
            try:
                import abs_native as _abs

                if hasattr(_abs, "unpack_block_row"):
                    data = json.loads(_abs.unpack_block_row(raw))
                    return data if isinstance(data, dict) else None
            except Exception as exc:
                self._json_decode_failures += 1
                logger.warning(
                    "[RocksStore] corrupt %s ABLK (decode_failures=%s): %s",
                    context,
                    self._json_decode_failures,
                    exc,
                )
                return None
            self._json_decode_failures += 1
            logger.warning(
                "[RocksStore] corrupt %s ABLK (no native unpack)",
                context,
            )
            return None
        return self._loads_json_or_none(raw, context=context)

    def _pack_block_blob(self, block: Dict[str, Any]) -> bytes:
        """Pack block row as ABLK when native codec is present; else legacy JSON."""
        try:
            import abs_native as _abs

            if hasattr(_abs, "pack_block_row"):
                return bytes(
                    _abs.pack_block_row(json.dumps(block, ensure_ascii=False))
                )
        except Exception as exc:
            logger.warning(
                "[RocksStore] native pack_block_row failed, JSON fallback: %s", exc
            )
        return json.dumps(block, ensure_ascii=False).encode("utf-8")

    def _loads_receipt_blob_or_none(self, raw: bytes | None, *, context: str) -> Optional[Dict]:
        """Dual-decode receipt row: ATXR binary (v1.3.151) or legacy JSON."""
        if raw is None:
            return None
        if len(raw) >= 4 and raw[:4] == b"ATXR":
            try:
                import abs_native as _abs

                if hasattr(_abs, "unpack_receipt_row"):
                    data = json.loads(_abs.unpack_receipt_row(raw))
                    return data if isinstance(data, dict) else None
            except Exception as exc:
                self._json_decode_failures += 1
                logger.warning(
                    "[RocksStore] corrupt %s ATXR (decode_failures=%s): %s",
                    context,
                    self._json_decode_failures,
                    exc,
                )
                return None
            self._json_decode_failures += 1
            logger.warning(
                "[RocksStore] corrupt %s ATXR (no native unpack)",
                context,
            )
            return None
        return self._loads_json_or_none(raw, context=context)

    def _pack_receipt_blob(self, receipt: Dict[str, Any]) -> bytes:
        """Pack receipt row as ATXR when native codec is present; else legacy JSON."""
        try:
            import abs_native as _abs

            if hasattr(_abs, "pack_receipt_row"):
                return bytes(
                    _abs.pack_receipt_row(json.dumps(receipt, ensure_ascii=False))
                )
        except Exception as exc:
            logger.warning(
                "[RocksStore] native pack_receipt_row failed, JSON fallback: %s", exc
            )
        return json.dumps(receipt, ensure_ascii=False).encode("utf-8")

    def _ensure_schema(self) -> None:
        existing = self._raw_get(kc.key_meta("schema_version"))
        target = self._schema_version.encode("utf-8")
        if existing is None:
            self._raw_put(kc.key_meta("schema_version"), target)
            # Empty store: proposer counters are authoritative from genesis.
            # Legacy volumes already have schema_version — do not invent counts.
            self._raw_put(kc.key_meta("proposer_counts_v1"), b"1")
            self._raw_put(kc.key_meta("addr_tx_counts_v1"), b"1")
            return
        # One-way honesty: bump meta when CF mode is enabled on a legacy DB.
        if self.column_families and existing != target:
            self._raw_put(kc.key_meta("schema_version"), target)

    def initialize(self) -> None:
        self._ensure_schema()
        if not self.get_meta("tx_addr_index_v1"):
            with self._write_lock:
                for row in self._iter_transaction_rows():
                    self._insert_tx_indexes(row)
                self.set_meta("tx_addr_index_v1", True)
        if not self.get_meta("tx_recent_index_v1"):
            with self._write_lock:
                for row in self._iter_transaction_rows():
                    tx_hash = row.get("hash", row.get("tx_hash", "")) or ""
                    if not tx_hash:
                        continue
                    bh = int(row.get("block_height", 0) or 0)
                    ts = int(row.get("timestamp", 0) or 0)
                    self._raw_put(kc.key_tx_recent_index(bh, ts, tx_hash), b"\x01")
                self.set_meta("tx_recent_index_v1", True)

    # ── low-level I/O ─────────────────────────────────────────────────────

    def _raw_get(self, key: bytes) -> Optional[bytes]:
        val = self._engine.get(key)
        return bytes(val) if val is not None else None

    def _drop_root_acc(self) -> None:
        self._root_acc = None

    def _root_acc_enabled(self) -> bool:
        try:
            import abs_native  # type: ignore

            return hasattr(abs_native, "StateRootAccumulator")
        except Exception:
            return False

    def _ensure_root_acc(self) -> Any | None:
        if self._root_acc is not None:
            return self._root_acc
        if not self._root_acc_enabled():
            return None
        import abs_native  # type: ignore

        acc = abs_native.StateRootAccumulator()
        blobs = [value for _key, value in self._scan_prefix(kc.prefix_accounts())]
        if blobs:
            acc.load_from_blobs(blobs)
        self._root_acc = acc
        return acc

    def _account_key_address(self, key: bytes) -> str:
        return key[len(kc.P_ACCOUNT) :].decode("utf-8")

    def _root_acc_upsert_blob(self, value: bytes) -> None:
        acc = self._ensure_root_acc()
        if acc is not None:
            acc.upsert_account_blob(value)

    def _root_acc_remove(self, address: str) -> None:
        if self._root_acc is not None:
            self._root_acc.remove_account(address)

    def _flush_batch_acc_dirty(self) -> None:
        if not self._batch_acc_dirty:
            return
        acc = self._ensure_root_acc()
        if acc is not None:
            for addr, value in self._batch_acc_dirty.items():
                if value is None:
                    acc.remove_account(addr)
                else:
                    acc.upsert_account_blob(value)
        self._batch_acc_dirty.clear()

    def _raw_put(self, key: bytes, value: bytes) -> None:
        if key.startswith(kc.P_ACCOUNT):
            if self._pending_batch is not None:
                self._batch_acc_dirty[self._account_key_address(key)] = value
            else:
                self._root_acc_upsert_blob(value)
        if self._pending_batch is not None:
            self._pending_batch.put(key, value)
            return
        self._engine.put(key, value)

    def _raw_delete(self, key: bytes) -> None:
        if key.startswith(kc.P_ACCOUNT):
            if self._pending_batch is not None:
                self._batch_acc_dirty[self._account_key_address(key)] = None
            else:
                self._root_acc_remove(self._account_key_address(key))
        if self._pending_batch is not None:
            self._pending_batch.delete(key)
            return
        self._engine.delete(key)

    def _scan_prefix(self, prefix: bytes, limit: int = 100_000) -> List[tuple[bytes, bytes]]:
        rows = self._engine.prefix_scan(prefix, limit)
        return [(bytes(k), bytes(v)) for k, v in rows]

    @contextmanager
    def atomic(self):
        import abs_native  # type: ignore

        with self._write_lock:
            batch = abs_native.RocksWriteBatch()
            self._pending_batch = batch
            try:
                yield self
                self._engine.write_batch(batch)
                self._flush_batch_acc_dirty()
            except Exception:
                raise
            finally:
                self._pending_batch = None
                self._batch_acc_dirty.clear()

    def close(self) -> None:
        """Graceful RocksDB close — wait out WriteBatch, drop native engine (WAL flush via Drop).

        ADR 0014: never tear down while ``atomic()`` holds ``_write_lock``; incomplete
        batches are discarded only after the lock is acquired (commit finished or aborted).
        """
        with self._write_lock:
            if getattr(self, "_engine", None) is None:
                return
            if self._pending_batch is not None:
                logger.warning(
                    "[RocksDB] discarding incomplete WriteBatch on close path=%s",
                    self.db_path,
                )
                self._pending_batch = None
                self._batch_acc_dirty.clear()
            eng = self._engine
            self._engine = None  # type: ignore[assignment]
            try:
                flush = getattr(eng, "flush", None)
                if callable(flush):
                    flush()
            except Exception as exc:
                logger.warning("[RocksDB] flush on close failed: %s", exc)
            try:
                del eng
            except Exception as exc:
                logger.warning("[RocksDB] native engine drop failed: %s", exc)
            msg = f"[RocksDB] clean close ({self.db_path})"
            logger.info(msg)
            print(msg)

    def backup_to(self, dest_path: str) -> bool:
        try:
            if os.path.isdir(dest_path):
                shutil.rmtree(dest_path)
            self._engine.checkpoint(dest_path)
            return True
        except Exception as exc:
            print(f"[RocksDB] backup_to error: {exc}")
            return False

    # ── meta ──────────────────────────────────────────────────────────────

    def set_meta(self, key: str, value: Any) -> None:
        with self._write_lock:
            self._raw_put(
                kc.key_meta(key),
                json.dumps(value, ensure_ascii=False).encode("utf-8"),
            )

    def get_meta(self, key: str, default: Any = None) -> Any:
        raw = self._raw_get(kc.key_meta(key))
        if raw is None:
            return default
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            text = raw.decode("utf-8", errors="replace")
            stripped = text.strip()
            # Corrupt JSON object/array/string → fail-closed default.
            # Legacy plain-string meta (e.g. schema_version) is not JSON.
            if stripped[:1] in "{\"[":
                self._json_decode_failures += 1
                logger.warning(
                    "[RocksStore] corrupt meta %s (decode_failures=%s): %s",
                    key,
                    self._json_decode_failures,
                    exc,
                )
                # Fail-closed: never return a garbage string as valid meta.
                return default
            return text if text else default

    def _invalidate_obs_meta(self) -> None:
        for meta_key in (
            "stats_tx_count",
            "stats_account_count",
            "stats_receipt_count",
            "stats_proposer_audit",
            "total_supply_abs",
        ):
            self._raw_delete(kc.key_meta(meta_key))

    def _proposer_counts_enabled(self) -> bool:
        raw = self._raw_get(kc.key_meta("proposer_counts_v1"))
        return raw == b"1"

    def _bump_proposer_count(self, addr: str, delta: int) -> None:
        if not self._proposer_counts_enabled():
            return
        name = f"proposer_count:{SqliteDatabase._normalize_address(addr)}"
        cur = self._read_plain_meta_int(name)
        if cur is None:
            if int(delta) < 0:
                return
            cur = 0
        nxt = max(0, int(cur) + int(delta))
        self._raw_put(kc.key_meta(name), str(nxt).encode("utf-8"))

    def _addr_tx_counts_enabled(self) -> bool:
        raw = self._raw_get(kc.key_meta("addr_tx_counts_v1"))
        return raw == b"1"

    def _bump_addr_tx_count(self, addr: str, kind: str, delta: int) -> None:
        if not self._addr_tx_counts_enabled():
            return
        name = f"tx_{kind}_count:{SqliteDatabase._normalize_address(addr)}"
        cur = self._read_plain_meta_int(name)
        if cur is None:
            if int(delta) < 0:
                return
            cur = 0
        nxt = max(0, int(cur) + int(delta))
        self._raw_put(kc.key_meta(name), str(nxt).encode("utf-8"))

    def _max_indexed_tx_height(self, addr: str) -> int | None:
        """O(1) last-tx height from address indexes (no tx blob decode)."""
        prefixes = (kc.prefix_tx_from(addr), kc.prefix_tx_to(addr))
        engine = self._engine
        max_h: int | None = None
        for prefix in prefixes:
            last_kv = None
            if engine is not None and hasattr(engine, "prefix_last"):
                try:
                    last_kv = engine.prefix_last(prefix)
                except Exception as exc:
                    logger.warning(
                        "[RocksStore] prefix_last address index failed: %s", exc
                    )
                    last_kv = None
            if last_kv:
                key = bytes(last_kv[0])
            else:
                rows = self._scan_prefix(prefix)
                if not rows:
                    continue
                key = max(rows, key=lambda kv: kv[0])[0]
            rest = key[len(prefix) :]
            if len(rest) < 8:
                continue
            h = kc.unpack_u64(rest[:8])
            max_h = h if max_h is None else max(max_h, h)
        return max_h

    def _read_plain_meta_int(self, name: str) -> int | None:
        raw = self._raw_get(kc.key_meta(name))
        if raw is None:
            return None
        try:
            return int(raw.decode("utf-8"))
        except (TypeError, ValueError, UnicodeDecodeError):
            return None

    def _bump_plain_meta_int(self, name: str, delta: int) -> None:
        cur = self._read_plain_meta_int(name)
        if cur is None:
            return
        self._raw_put(kc.key_meta(name), str(cur + int(delta)).encode("utf-8"))

    def _cached_prefix_len(self, meta_key: str, prefix: bytes) -> int:
        cached = self._read_plain_meta_int(meta_key)
        if cached is not None:
            return cached
        n = len(self._scan_prefix(prefix))
        self._raw_put(kc.key_meta(meta_key), str(n).encode("utf-8"))
        return n

    def _adjust_total_supply_abs(self, delta_abs: float) -> None:
        raw = self._raw_get(kc.key_meta("total_supply_abs"))
        if raw is None:
            return
        try:
            cur = float(raw.decode("utf-8"))
        except (TypeError, ValueError, UnicodeDecodeError):
            self._raw_delete(kc.key_meta("total_supply_abs"))
            return
        self._raw_put(
            kc.key_meta("total_supply_abs"),
            format(float(cur) + float(delta_abs), ".12g").encode("utf-8"),
        )

    # ── blocks ────────────────────────────────────────────────────────────

    def _insert_block(self, block: Dict) -> None:
        from runtime.amount import money_abs

        height = int(block.get("height", block.get("number", 0)) or 0)
        block_hash = block.get("hash", block.get("block_hash", "")) or ""
        stored = dict(block)
        stored["total_burned"] = money_abs(
            block.get("total_burned", 0.0), field="total_burned"
        )
        # v1.3.149: typed ABLK value when native pack_block_row is available.
        payload = self._pack_block_blob(stored)
        self._raw_put(kc.key_block_height(height), payload)
        if block_hash:
            self._raw_put(kc.key_block_hash_to_height(block_hash), kc.pack_u64(height))
        # v1.3.66: O(1) tip meta (belt-and-suspenders with prefix_last)
        self._raw_put(kc.key_meta("chain_tip"), str(height).encode("utf-8"))
        if block_hash:
            self._raw_put(kc.key_meta("chain_tip_hash"), block_hash.encode("utf-8"))
        self._insert_proposer_audit(stored)

    def get_chain_tip(self) -> int:
        meta = self.get_meta("chain_tip")
        if meta is not None:
            try:
                return int(meta)
            except (TypeError, ValueError):
                pass
        engine = self._engine
        if engine is not None and hasattr(engine, "prefix_last"):
            try:
                last = engine.prefix_last(kc.prefix_block_heights())
                if last:
                    key, _val = last
                    return int(kc.unpack_u64(key[1:9]))
            except Exception as exc:
                logger.warning("[RocksStore] prefix_last chain tip failed: %s", exc)
        rows = self._scan_prefix(kc.prefix_block_heights())
        if not rows:
            return 0
        return max(kc.unpack_u64(key[1:9]) for key, _ in rows)

    def get_last_block(self) -> Optional[Dict]:
        tip = self.get_chain_tip()
        if tip < 0:
            return None
        block = self.get_block(tip)
        if block is not None:
            return block
        # tip meta may be 0 on an empty store — distinguish via missing height-0 block.
        return None

    def _insert_proposer_audit(self, block: Dict) -> None:
        from runtime.amount import money_abs

        height = int(block.get("height", block.get("number", 0)) or 0)
        audit = {
            "height": height,
            "block_hash": block.get("hash", block.get("block_hash", "")) or "",
            "proposer": SqliteDatabase._normalize_address(
                block.get("miner", block.get("proposer", "genesis")) or "genesis"
            ),
            "tx_count": int(block.get("tx_count", len(block.get("transactions", []))) or 0),
            "total_burned": money_abs(block.get("total_burned", 0.0), field="total_burned"),
            "block_ts": int(block.get("timestamp", int(time.time())) or 0),
            "recorded_at": int(time.time()),
        }
        created = self._raw_get(kc.key_proposer_audit(height)) is None
        self._raw_put(kc.key_proposer_audit(height), json.dumps(audit).encode("utf-8"))
        if created:
            self._bump_plain_meta_int("stats_proposer_audit", 1)
            self._bump_proposer_count(str(audit["proposer"]), 1)
        self._touch_live_state_root_meta(block)

    def _touch_live_state_root_meta(self, block: Dict) -> None:
        state_root = str(block.get("state_root", "") or "").strip()
        if not state_root:
            return
        height = int(block.get("height", block.get("number", 0)) or 0)
        self._raw_put(kc.key_meta("state_root"), state_root.encode("utf-8"))
        self._raw_put(kc.key_meta("live_state_root"), state_root.encode("utf-8"))
        self._raw_put(
            kc.key_meta("live_state_root_height"),
            str(height).encode("utf-8"),
        )

    def save_block(self, block: Dict) -> bool:
        with self._write_lock:
            try:
                self._insert_block(block)
                return True
            except Exception as exc:
                print(f"[RocksDB] save_block error: {exc}")
                return False

    def get_block(self, height: int) -> Optional[Dict]:
        raw = self._raw_get(kc.key_block_height(int(height)))
        return self._loads_block_blob_or_none(raw, context=f"block height={height}")

    def get_block_by_hash(self, block_hash: str) -> Optional[Dict]:
        raw_h = self._raw_get(kc.key_block_hash_to_height(block_hash))
        if not raw_h:
            return None
        return self.get_block(kc.unpack_u64(raw_h))

    def get_latest_blocks(self, limit: int = 20) -> List[Dict]:
        """Newest `limit` blocks via tip point-reads. Never prefix-scan heights."""
        limit = max(1, min(int(limit), 200))
        tip = int(self.get_chain_tip() or 0)
        blocks: List[Dict] = []
        h = tip
        sought = 0
        max_seek = max(limit * 4, limit + 64)
        while h >= 0 and len(blocks) < limit and sought < max_seek:
            raw = self._raw_get(kc.key_block_height(h))
            sought += 1
            h -= 1
            if raw is None:
                continue
            block = self._loads_block_blob_or_none(raw, context="latest_block")
            if block is None:
                logger.warning(
                    "[RocksStore] corrupt latest_block row skipped "
                    "(decode_failures=%s)",
                    self._json_decode_failures,
                )
                continue
            blocks.append(block)
        return blocks

    # ── accounts / state ──────────────────────────────────────────────────

    def _load_account(self, address: str) -> Dict[str, Any]:
        from runtime.amount import account_satoshi, dual_write_balance, from_satoshi_float

        raw = self._raw_get(kc.key_account(address))
        if not raw:
            return {
                "address": SqliteDatabase._normalize_address(address),
                "balance": 0.0,
                "balance_satoshi": 0,
                "nonce": 0,
                "code": None,
                "storage": None,
            }
        row = self._loads_account_blob_or_none(raw, context=f"account {address}")
        if row is None:
            # v1.3.65: corrupt blob must not become a zero-balance account.
            raise AccountCorruptError(
                f"corrupt_account_blob:{SqliteDatabase._normalize_address(address)}"
            )
        # Backfill satoshi for legacy float-only rows (in-memory; persisted on next write)
        if row.get("balance_satoshi") is None:
            dual_write_balance(row, row.get("balance", 0) or 0)
        else:
            sat = account_satoshi(row)
            row["balance_satoshi"] = sat
            row["balance"] = from_satoshi_float(sat)
        return row

    def _save_account_row(self, row: Dict[str, Any]) -> None:
        from runtime.amount import dual_write_balance, from_satoshi_float

        addr = SqliteDatabase._normalize_address(row.get("address", ""))
        row["address"] = addr
        created = self._raw_get(kc.key_account(addr)) is None
        if row.get("balance_satoshi") is not None:
            sat = max(0, int(row["balance_satoshi"]))
            row["balance_satoshi"] = sat
            row["balance"] = from_satoshi_float(sat)
        else:
            dual_write_balance(row, row.get("balance", 0) or 0)
        # v1.3.147: typed ABAR value when native pack_account_row is available.
        self._raw_put(kc.key_account(addr), self._pack_account_blob(row))
        if created:
            self._bump_plain_meta_int("stats_account_count", 1)

    def get_balance(self, address: str) -> float:
        from runtime.amount import account_balance_abs

        return account_balance_abs(self._load_account(address))

    def get_balance_satoshi(self, address: str) -> int:
        from runtime.amount import account_satoshi

        return account_satoshi(self._load_account(address))

    def get_nonce(self, address: str) -> int:
        return int(self._load_account(address).get("nonce", 0) or 0)

    def get_account(self, address: str) -> Optional[Dict]:
        from runtime.amount import account_satoshi

        row = self._load_account(address)
        sat = account_satoshi(row)
        if sat == 0 and row["nonce"] == 0 and not row.get("code") and not row.get("storage"):
            raw = self._raw_get(kc.key_account(address))
            return None if raw is None else row
        return row

    def _apply_balance_delta(self, address: str, delta: float) -> None:
        from runtime.amount import apply_delta_satoshi, dual_write_balance, from_satoshi_float

        row = self._load_account(address)
        cur_sat = int(row.get("balance_satoshi", 0) or 0)
        new_sat = apply_delta_satoshi(cur_sat, delta)
        dual_write_balance(row, from_satoshi_float(new_sat))
        # dual_write from float of new_sat is exact for representable amounts
        row["balance_satoshi"] = new_sat
        row["balance"] = from_satoshi_float(new_sat)
        self._adjust_total_supply_abs(from_satoshi_float(new_sat) - from_satoshi_float(cur_sat))
        self._save_account_row(row)

    def balance_delta(self, address: str, delta: float) -> None:
        self._apply_balance_delta(address, delta)

    def balance_delta_satoshi(self, address: str, delta_sat: int) -> None:
        """Integer satoshi balance change (Wave C apply path)."""
        from runtime.amount import apply_satoshi_delta, from_satoshi_float

        row = self._load_account(address)
        cur_sat = int(row.get("balance_satoshi", 0) or 0)
        new_sat = apply_satoshi_delta(cur_sat, int(delta_sat))
        row["balance_satoshi"] = new_sat
        row["balance"] = from_satoshi_float(new_sat)
        self._adjust_total_supply_abs(from_satoshi_float(new_sat) - from_satoshi_float(cur_sat))
        self._save_account_row(row)

    def update_balance(self, address: str, delta: float) -> float:
        with self._write_lock:
            self._apply_balance_delta(address, delta)
            return self.get_balance(address)

    def set_balance(self, address: str, balance: int) -> None:
        from runtime.amount import dual_write_balance, from_satoshi_float, to_satoshi

        if isinstance(balance, bool):
            raise TypeError("bool is not an amount")
        new_sat = to_satoshi(balance)
        with self._write_lock:
            row = self._load_account(address)
            old_sat = int(row.get("balance_satoshi", 0) or 0)
            dual_write_balance(row, balance)
            self._adjust_total_supply_abs(
                from_satoshi_float(new_sat) - from_satoshi_float(old_sat)
            )
            self._save_account_row(row)

    def increment_nonce(self, address: str) -> int:
        with self._write_lock:
            row = self._load_account(address)
            row["nonce"] = int(row.get("nonce", 0) or 0) + 1
            self._save_account_row(row)
            return int(row["nonce"])

    def nonce_increment(self, address: str) -> int:
        row = self._load_account(address)
        row["nonce"] = int(row.get("nonce", 0) or 0) + 1
        self._save_account_row(row)
        return int(row["nonce"])

    def save_account(
        self,
        address: str,
        balance: float = 0.0,
        nonce: int = 0,
        code: str | None = None,
        storage: str | None = None,
    ) -> None:
        from runtime.amount import dual_write_balance

        with self._write_lock:
            row = self._load_account(address)
            from runtime.amount import account_balance_abs

            old_abs = account_balance_abs(row)
            dual_write_balance(row, balance)
            row["nonce"] = int(nonce)
            row["code"] = code
            row["storage"] = storage
            self._adjust_total_supply_abs(float(balance) - float(old_abs))
            self._save_account_row(row)

    def update_account_storage(self, address: str, storage: Dict) -> None:
        with self._write_lock:
            row = self._load_account(address)
            row["storage"] = json.dumps(storage)
            self._save_account_row(row)

    def commit_writeback_accounts(self, accounts: Dict[str, Any]) -> int:
        """Store-lock aware batch commit of native-applied account rows (v1.3.62)."""
        out = self.commit_writeback_bundle(accounts, None)
        return int(out.get("accounts") or 0)

    def load_writeback_accounts(self, addresses: List[str]) -> Dict[str, Any]:
        """Batch-load account rows for native writeback apply (v1.3.64).

        Prefers ``RocksEngine.get_account_rows``; falls back to ``_load_account``.
        Applies satoshi dual-write backfill like ``_load_account``.
        """
        from runtime.amount import account_satoshi, dual_write_balance, from_satoshi_float
        from storage.database import Database as SqliteDatabase

        addrs: List[str] = []
        seen = set()
        for raw in list(addresses or []):
            addr = SqliteDatabase._normalize_address(str(raw))
            if not addr or addr in seen:
                continue
            seen.add(addr)
            addrs.append(addr)
        if not addrs:
            return {}

        engine = self._engine
        rows: Dict[str, Any] = {}
        if engine is not None and hasattr(engine, "get_account_rows"):
            try:
                loaded = json.loads(engine.get_account_rows(json.dumps(addrs)))
                if isinstance(loaded, dict):
                    rows = {str(k): dict(v) for k, v in loaded.items() if isinstance(v, dict)}
            except Exception as exc:
                logger.warning(
                    "[RocksStore] get_account_rows failed, per-account load: %s",
                    exc,
                )
                rows = {}

        out: Dict[str, Any] = {}
        for addr in addrs:
            row = dict(rows.get(addr) or self._load_account(addr))
            row["address"] = addr
            if row.get("balance_satoshi") is None:
                dual_write_balance(row, row.get("balance", 0) or 0)
            else:
                sat = account_satoshi(row)
                row["balance_satoshi"] = sat
                row["balance"] = from_satoshi_float(sat)
            if row.get("code") is None:
                row["code"] = ""
            if row.get("storage") is None:
                row["storage"] = "{}"
            out[addr] = row
        return out

    def commit_writeback_bundle(
        self,
        accounts: Dict[str, Any] | None,
        log_batches: List[Dict[str, Any]] | None = None,
        *,
        block_height: int = 0,
        tx_hash: str = "",
        timestamp: int = 0,
    ) -> Dict[str, int]:
        """One store-lock commit for accounts + EVM log batches (v1.3.63).

        Prefers ``RocksEngine.commit_writeback_bundle`` (single WriteBatch) when
        outside ``atomic()``; falls back to ``_save_account_row`` / dual log puts.
        """
        from runtime.amount import dual_write_balance, writeback_balance_abs
        from storage.database import Database as SqliteDatabase

        accounts = dict(accounts or {})
        log_batches = list(log_batches or [])
        if not accounts and not log_batches:
            return {"accounts": 0, "logs": 0}

        prepared: Dict[str, Dict[str, Any]] = {}
        log_rows: List[Dict[str, Any]] = []
        tip = int(block_height)
        txh = str(tx_hash or "")
        ts = int(timestamp or time.time())

        with self._write_lock:
            for addr_raw, row_in in accounts.items():
                addr = SqliteDatabase._normalize_address(str(addr_raw))
                merged = self._load_account(addr)
                row = dict(row_in or {})
                if row.get("balance_satoshi") is not None or row.get("balance") is not None:
                    dual_write_balance(merged, writeback_balance_abs(row))
                if "nonce" in row:
                    merged["nonce"] = int(row.get("nonce") or 0)
                if "code" in row:
                    merged["code"] = row.get("code")
                if "storage" in row:
                    storage = row.get("storage")
                    if isinstance(storage, dict):
                        merged["storage"] = json.dumps(
                            {str(k): int(v) for k, v in storage.items()}
                        )
                    else:
                        merged["storage"] = str(storage or "{}")
                merged["address"] = addr
                prepared[addr] = merged

            log_index = 0
            for batch in log_batches:
                addr = SqliteDatabase._normalize_address(str(batch.get("address") or ""))
                for entry in list(batch.get("logs") or []):
                    topics = entry.get("topics", [])
                    if not isinstance(topics, list):
                        topics = []
                    log_rows.append(
                        {
                            "contract_address": addr,
                            "block_height": tip,
                            "tx_hash": txh,
                            "log_index": int(log_index),
                            "topics": topics,
                            "data": str(entry.get("data", "")),
                            "timestamp": ts,
                        }
                    )
                    log_index += 1

            engine = self._engine
            if (
                engine is not None
                and hasattr(engine, "commit_writeback_bundle")
                and self._pending_batch is None
            ):
                for row in prepared.values():
                    blob = self._pack_account_blob(row)
                    self._root_acc_upsert_blob(blob)
                accounts_n, logs_n = engine.commit_writeback_bundle(
                    json.dumps(prepared, ensure_ascii=False),
                    json.dumps(log_rows, ensure_ascii=False),
                )
                return {"accounts": int(accounts_n), "logs": int(logs_n)}

            for row in prepared.values():
                self._save_account_row(row)
            for row in log_rows:
                payload = json.dumps(row, ensure_ascii=False).encode("utf-8")
                idx = int(row.get("log_index") or 0)
                self._raw_put(kc.key_evm_log(tip, txh, idx), payload)
                self._raw_put(kc.key_evm_log_tx(txh, idx), payload)
            return {"accounts": len(prepared), "logs": len(log_rows)}

    def get_all_accounts(self) -> List[Dict]:
        rows = self._scan_prefix(kc.prefix_accounts())
        out: List[Dict] = []
        for _key, value in rows:
            before = self._json_decode_failures
            row = self._loads_account_blob_or_none(value, context="account scan")
            if row is None:
                if self._json_decode_failures == before:
                    self._json_decode_failures += 1
                logger.warning(
                    "[RocksStore] corrupt account row skipped "
                    "(decode_failures=%s)",
                    self._json_decode_failures,
                )
                continue
            out.append(row)
        return sorted(out, key=lambda r: str(r.get("address", "")))

    def get_live_state_root_meta(self) -> tuple[str, int]:
        """Cached root from last committed block header (observability fast path)."""
        raw_root = self._raw_get(kc.key_meta("live_state_root"))
        raw_h = self._raw_get(kc.key_meta("live_state_root_height"))
        root = raw_root.decode("utf-8") if raw_root else ""
        try:
            height = int(raw_h.decode("utf-8")) if raw_h else -1
        except (UnicodeDecodeError, ValueError, TypeError) as exc:
            logger.warning(
                "[RocksStore] corrupt live_state_root_height meta: %s", exc
            )
            height = -1
        return root, height

    def compute_state_root(self) -> str:
        """Canonical state root via native accumulator or account blob scan.

        Wave C: native Rocks tip hasher emits integer ``b_satoshi`` only. Use it
        when tip encoding v2 is ceremony-armed; otherwise decode blobs and hash
        the legacy float ``\"b\"`` tip in Python.
        """
        from execution.state_root import compute_state_root_from_blobs
        from runtime.state_root_encoding import tip_encoding_version

        tip_v2 = tip_encoding_version() >= 2

        if self._batch_acc_dirty or self._pending_batch is not None:
            by_addr: dict[str, bytes] = {}
            for key, value in self._scan_prefix(kc.prefix_accounts()):
                by_addr[self._account_key_address(key)] = value
            for addr, value in self._batch_acc_dirty.items():
                if value is None:
                    by_addr.pop(addr, None)
                else:
                    by_addr[addr] = value
            return compute_state_root_from_blobs(list(by_addr.values()))

        if tip_v2:
            acc = self._ensure_root_acc()
            if acc is not None:
                return acc.root()
            if hasattr(self._engine, "state_root_from_account_prefix"):
                return self._engine.state_root_from_account_prefix(
                    kc.prefix_accounts(),
                    100_000,
                )
        blobs = [value for _key, value in self._scan_prefix(kc.prefix_accounts())]
        return compute_state_root_from_blobs(blobs)

    def reset_accounts_from_alloc(
        self, alloc: Dict[str, float], *, _in_atomic: bool = False
    ) -> None:
        if _in_atomic:
            self._reset_accounts_locked(alloc)
            return
        with self.atomic():
            self._reset_accounts_locked(alloc)

    def _reset_accounts_locked(self, alloc: Dict[str, float]) -> None:
        self._drop_root_acc()
        self._invalidate_obs_meta()
        for key, _value in self._scan_prefix(kc.prefix_accounts()):
            self._raw_delete(key)
        from runtime.amount import dual_write_balance

        for addr, amount in alloc.items():
            if isinstance(amount, bool):
                raise TypeError("bool is not an amount")
            row = {
                "address": SqliteDatabase._normalize_address(addr),
                "nonce": 0,
                "code": None,
                "storage": None,
            }
            dual_write_balance(row, amount)
            self._save_account_row(row)

    def get_cached_account_count(self) -> int | None:
        """O(1) meta only. None if never counted — callers must not prefix-scan."""
        return self._read_plain_meta_int("stats_account_count")

    def get_cached_total_supply(self) -> float | None:
        """O(1) meta only. None if missing — callers must not get_all_accounts()."""
        raw = self._raw_get(kc.key_meta("total_supply_abs"))
        if raw is None:
            return None
        try:
            return float(raw.decode("utf-8"))
        except (TypeError, ValueError, UnicodeDecodeError):
            return None

    def get_cached_total_burned(self) -> float | None:
        """O(1) prefix_last only. None if empty — never scan P_BURN on the poll path."""
        from runtime.amount import money_abs

        engine = self._engine
        if engine is None or not hasattr(engine, "prefix_last"):
            return None
        try:
            last_kv = engine.prefix_last(kc.P_BURN)
        except Exception as exc:
            logger.warning("[RocksStore] prefix_last cached burn failed: %s", exc)
            return None
        if not last_kv:
            return None
        _key, value = last_kv
        row = self._loads_json_or_none(bytes(value), context="burn_total_cached")
        if row is None:
            return None
        return money_abs(row.get("total_burned", 0.0), field="total_burned")

    def get_total_supply(self) -> float:
        from runtime.amount import account_balance_abs

        raw = self._raw_get(kc.key_meta("total_supply_abs"))
        if raw is not None:
            try:
                return float(raw.decode("utf-8"))
            except (TypeError, ValueError, UnicodeDecodeError):
                pass
        total = sum(account_balance_abs(a) for a in self.get_all_accounts())
        self._raw_put(
            kc.key_meta("total_supply_abs"),
            format(float(total), ".12g").encode("utf-8"),
        )
        return float(total)

    # ── validators ────────────────────────────────────────────────────────

    def save_validator(self, address: str, stake: float) -> None:
        from runtime.amount import money_abs

        with self._write_lock:
            addr = SqliteDatabase._normalize_address(address)
            row = {
                "address": addr,
                "stake": money_abs(stake, field="stake"),
                "active": 1,
                "slashed": 0,
                "joined_at": int(time.time()),
            }
            self._raw_put(kc.key_validator(addr), json.dumps(row).encode("utf-8"))

    def get_validators(self, active_only: bool = True) -> List[Dict]:
        rows = self._scan_prefix(kc.prefix_validators())
        out: List[Dict] = []
        for _key, value in rows:
            try:
                row = json.loads(value.decode("utf-8"))
            except Exception as exc:
                self._json_decode_failures += 1
                logger.warning(
                    "[RocksStore] corrupt validator row skipped "
                    "(decode_failures=%s): %s",
                    self._json_decode_failures,
                    exc,
                )
                continue
            if active_only and not int(row.get("active", 1)):
                continue
            out.append(row)
        return out

    def slash_validator(self, address: str) -> None:
        with self._write_lock:
            addr = SqliteDatabase._normalize_address(address)
            raw = self._raw_get(kc.key_validator(addr))
            if not raw:
                return
            row = self._loads_json_or_none(raw, context=f"slash_validator {addr}")
            if row is None:
                return
            row["slashed"] = 1
            row["active"] = 0
            self._raw_put(kc.key_validator(addr), json.dumps(row).encode("utf-8"))

    # ── transactions ──────────────────────────────────────────────────────

    def _insert_transaction(self, tx: Dict) -> None:
        from runtime.amount import tx_money_abs

        tx_hash = tx.get("hash", tx.get("tx_hash", "")) or ""
        if not tx_hash:
            return
        money = tx_money_abs(tx)
        gas = observed_optional_int(tx, "gas", "gas_limit")
        gas_used = observed_optional_int(tx, "gas_used")
        row = {
            "hash": tx_hash,
            "block_height": int(tx.get("block_height", 0) or 0),
            "from_addr": SqliteDatabase._normalize_address(tx.get("from_addr", tx.get("from", ""))),
            "to_addr": SqliteDatabase._normalize_address(tx.get("to_addr", tx.get("to", ""))),
            "value": money["value"],
            "fee": money["fee"],
            "burned": money["burned"],
            "nonce": tx.get("nonce", 0),
            "tx_data": tx.get("data", tx.get("tx_data", "")),
            # Omit / None / unknown → fail-closed 0 (never invent success).
            "status": SqliteDatabase._normalize_tx_status(tx.get("status")),
            "timestamp": int(tx.get("timestamp", time.time()) or 0),
        }
        if gas is not None:
            row["gas"] = gas
        if gas_used is not None:
            row["gas_used"] = gas_used
        # v1.3.148: typed ATXV value when native pack_tx_row is available.
        payload = self._pack_tx_blob(row)
        created = self._raw_get(kc.key_tx(tx_hash)) is None
        self._raw_put(kc.key_tx(tx_hash), payload)
        if created:
            self._bump_plain_meta_int("stats_tx_count", 1)
        if row["block_height"]:
            self._raw_put(kc.key_block_tx(row["block_height"], tx_hash), b"\x01")
        self._insert_tx_indexes(row)

    def _insert_tx_indexes(self, row: Dict) -> None:
        tx_hash = row.get("hash", row.get("tx_hash", "")) or ""
        if not tx_hash:
            return
        bh = int(row.get("block_height", 0) or 0)
        from_addr = row.get("from_addr", "")
        to_addr = row.get("to_addr", "")
        created_from = False
        created_to = False
        if from_addr:
            key = kc.key_tx_from_index(from_addr, bh, tx_hash)
            created_from = self._raw_get(key) is None
            self._raw_put(key, b"\x01")
            if created_from:
                self._bump_addr_tx_count(from_addr, "from", 1)
        if to_addr:
            key = kc.key_tx_to_index(to_addr, bh, tx_hash)
            created_to = self._raw_get(key) is None
            self._raw_put(key, b"\x01")
            if created_to:
                self._bump_addr_tx_count(to_addr, "to", 1)
        if from_addr and created_from:
            self._bump_addr_tx_count(from_addr, "touch", 1)
        if to_addr and created_to and to_addr != from_addr:
            self._bump_addr_tx_count(to_addr, "touch", 1)
        ts = int(row.get("timestamp", 0) or 0)
        self._raw_put(kc.key_tx_recent_index(bh, ts, tx_hash), b"\x01")

    def _delete_tx_indexes(self, row: Dict) -> None:
        tx_hash = row.get("hash", row.get("tx_hash", "")) or ""
        if not tx_hash:
            return
        bh = int(row.get("block_height", 0) or 0)
        from_addr = row.get("from_addr", "")
        to_addr = row.get("to_addr", "")
        if from_addr:
            key = kc.key_tx_from_index(from_addr, bh, tx_hash)
            existed = self._raw_get(key) is not None
            self._raw_delete(key)
            if existed:
                self._bump_addr_tx_count(from_addr, "from", -1)
                self._bump_addr_tx_count(from_addr, "touch", -1)
        if to_addr:
            key = kc.key_tx_to_index(to_addr, bh, tx_hash)
            existed = self._raw_get(key) is not None
            self._raw_delete(key)
            if existed:
                self._bump_addr_tx_count(to_addr, "to", -1)
                if to_addr != from_addr:
                    self._bump_addr_tx_count(to_addr, "touch", -1)
        ts = int(row.get("timestamp", 0) or 0)
        self._raw_delete(kc.key_tx_recent_index(bh, ts, tx_hash))

    def _tx_hash_from_index_key(self, key: bytes, prefix: bytes) -> str:
        body = key[len(prefix) :]
        if len(body) < 8 + 32:
            return ""
        return "0x" + body[8:].hex()

    def _tx_hash_from_recent_key(self, key: bytes) -> str:
        body = key[len(kc.P_TX_RECENT) :]
        if len(body) < 16 + 32:
            return ""
        return "0x" + body[16:].hex()

    def _prefix_last_kv(self, prefix: bytes) -> Optional[tuple[bytes, bytes]]:
        engine = self._engine
        if engine is None or not hasattr(engine, "prefix_last"):
            return None
        try:
            row = engine.prefix_last(prefix)
        except Exception as exc:
            logger.warning("[RocksStore] prefix_last failed: %s", exc)
            return None
        if not row:
            return None
        return bytes(row[0]), bytes(row[1])

    def _prefix_prev_kv(
        self, prefix: bytes, before: bytes
    ) -> Optional[tuple[bytes, bytes]]:
        engine = self._engine
        if engine is None or not hasattr(engine, "prefix_prev"):
            return None
        try:
            row = engine.prefix_prev(prefix, before)
        except Exception as exc:
            logger.warning("[RocksStore] prefix_prev failed: %s", exc)
            return None
        if not row:
            return None
        return bytes(row[0]), bytes(row[1])

    def _scan_range(
        self, start: bytes, end_exclusive: bytes, limit: int
    ) -> List[tuple[bytes, bytes]]:
        """Forward scan [start, end_exclusive). Never a full-CF walk."""
        limit = max(0, min(int(limit), 100_000))
        if limit == 0 or not start or end_exclusive <= start:
            return []
        engine = self._engine
        if engine is not None and hasattr(engine, "scan_range"):
            try:
                rows = engine.scan_range(start, end_exclusive, limit)
            except Exception as exc:
                logger.warning("[RocksStore] scan_range failed: %s", exc)
            else:
                return [(bytes(k), bytes(v)) for k, v in rows]
        # Old wheel: prefix_scan from `start` then clip. Multi-height EVM
        # ranges must not use this path (query_evm_logs loops heights).
        clipped: List[tuple[bytes, bytes]] = []
        for key, value in self._scan_prefix(start, limit=limit):
            if key >= end_exclusive:
                break
            clipped.append((key, value))
            if len(clipped) >= limit:
                break
        return clipped

    def _address_index_page_hashes(
        self, addr: str, direction: str, limit: int, offset: int
    ) -> List[str]:
        """Newest-first unique tx hashes from address indexes. No full CF scan."""
        prefixes: List[bytes] = []
        if direction in ("all", "sent"):
            prefixes.append(kc.prefix_tx_from(addr))
        if direction in ("all", "received"):
            prefixes.append(kc.prefix_tx_to(addr))
        need = max(0, int(offset)) + max(1, int(limit))
        cursors: List[Optional[tuple[bytes, bytes]]] = [
            self._prefix_last_kv(p) for p in prefixes
        ]
        seen: set[str] = set()
        ordered: List[str] = []
        while len(ordered) < need and any(c is not None for c in cursors):
            best_i = -1
            best_key: Optional[bytes] = None
            for i, kv in enumerate(cursors):
                if kv is None:
                    continue
                if best_key is None or kv[0] > best_key:
                    best_key = kv[0]
                    best_i = i
            if best_i < 0 or best_key is None:
                break
            prefix = prefixes[best_i]
            key = cursors[best_i][0]  # type: ignore[index]
            tx_hash = self._tx_hash_from_index_key(key, prefix)
            cursors[best_i] = self._prefix_prev_kv(prefix, key)
            if tx_hash and tx_hash not in seen:
                seen.add(tx_hash)
                ordered.append(tx_hash)
        return ordered[offset : offset + limit]

    def count_transactions_by_address(
        self, address: str, direction: str = "all"
    ) -> int:
        addr = SqliteDatabase._normalize_address(address)
        if direction == "sent":
            kind = "from"
        elif direction == "received":
            kind = "to"
        else:
            kind = "touch"
        n = self._read_plain_meta_int(f"tx_{kind}_count:{addr}")
        if self._addr_tx_counts_enabled():
            return int(n or 0)
        # Legacy volumes: do not prefix-scan. Unknown count is 0, not a full index walk.
        return int(n or 0)

    def count_address_transactions(
        self, address: str, direction: str = "all"
    ) -> int:
        return self.count_transactions_by_address(address, direction)

    def get_transactions_by_address(
        self,
        address: str,
        limit: int = 50,
        offset: int = 0,
        direction: str = "all",
    ) -> List[Dict]:
        addr = SqliteDatabase._normalize_address(address)
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        hashes = self._address_index_page_hashes(addr, direction, limit, offset)
        out: List[Dict] = []
        for tx_hash in hashes:
            raw = self._raw_get(kc.key_tx(tx_hash))
            if not raw:
                continue
            row = self._loads_tx_blob_or_none(
                raw, context=f"address_tx {tx_hash[:16]}"
            )
            if row is None:
                logger.warning(
                    "[RocksStore] corrupt address_tx row skipped "
                    "(decode_failures=%s)",
                    self._json_decode_failures,
                )
                continue
            out.append(self._serialize_tx_row(row, addr))
        return out

    def _insert_tx_receipt(self, tx: Dict, block_hash: str, block_height: int) -> None:
        from runtime.amount import tx_money_abs

        tx_hash = tx.get("hash", tx.get("tx_hash", "")) or ""
        if not tx_hash:
            return
        money = tx_money_abs(tx)
        receipt = {
            "tx_hash": tx_hash,
            "block_height": int(block_height),
            "block_hash": block_hash,
            "from_addr": SqliteDatabase._normalize_address(tx.get("from_addr", tx.get("from", ""))),
            "to_addr": SqliteDatabase._normalize_address(tx.get("to_addr", tx.get("to", ""))),
            "value": money["value"],
            "fee": money["fee"],
            "burned": money["burned"],
            "status": SqliteDatabase._normalize_tx_status(tx.get("status")),
            "created_at": int(time.time()),
        }
        gas_used = observed_optional_int(tx, "gas_used")
        if gas_used is not None:
            receipt["gas_used"] = gas_used
        # v1.3.151: typed ATXR value when native pack_receipt_row is available.
        rkey = kc.P_TX_RECEIPT + kc.key_tx(tx_hash)[1:]
        created = self._raw_get(rkey) is None
        self._raw_put(rkey, self._pack_receipt_blob(receipt))
        if created:
            self._bump_plain_meta_int("stats_receipt_count", 1)

    def save_transaction(self, tx: Dict) -> bool:
        with self._write_lock:
            try:
                self._insert_transaction(tx)
                return True
            except Exception as exc:
                print(f"[RocksDB] save_transaction error: {exc}")
                return False

    def get_transaction(self, tx_hash: str) -> Optional[Dict]:
        raw = self._raw_get(kc.key_tx(tx_hash))
        return self._loads_tx_blob_or_none(raw, context=f"tx {tx_hash[:16]}")

    def get_transactions_in_block(self, height: int) -> List[Dict]:
        prefix = kc.P_BLOCK_TX + kc.pack_u64(int(height))
        rows = self._scan_prefix(prefix)
        out: List[Dict] = []
        for key, _marker in rows:
            tx_hash_bytes = key[len(prefix) :]
            tx_key = kc.P_TX + tx_hash_bytes
            raw = self._raw_get(tx_key)
            if raw:
                row = self._loads_tx_blob_or_none(raw, context="block_tx")
                if row is None:
                    logger.warning(
                        "[RocksStore] corrupt block_tx row skipped "
                        "(decode_failures=%s)",
                        self._json_decode_failures,
                    )
                    continue
                out.append(row)
        return out

    def get_recent_transactions(self, limit: int = 30) -> List[Dict]:
        limit = max(1, min(int(limit), 200))
        out: List[Dict] = []
        # Inverted height/ts keys: lexicographic first == newest.
        start = kc.prefix_tx_recent()
        end = kc.prefix_family_end(start)
        for key, _marker in self._scan_range(start, end, limit * 2):
            tx_hash = self._tx_hash_from_recent_key(key)
            if not tx_hash:
                continue
            raw = self._raw_get(kc.key_tx(tx_hash))
            if raw:
                row = self._loads_tx_blob_or_none(
                    raw, context=f"recent_tx {tx_hash[:16]}"
                )
                if row is None:
                    logger.warning(
                        "[RocksStore] corrupt recent_tx row skipped "
                        "(decode_failures=%s)",
                        self._json_decode_failures,
                    )
                    continue
                out.append(row)
            if len(out) >= limit:
                break
        return out

    def get_tx_receipt(self, tx_hash: str) -> Optional[Dict]:
        raw = self._raw_get(kc.P_TX_RECEIPT + kc.key_tx(tx_hash)[1:])
        return self._loads_receipt_blob_or_none(raw, context=f"receipt {tx_hash[:16]}")

    def _format_receipt_row(self, row: Dict) -> Dict:
        from runtime.amount import tx_money_abs

        money = tx_money_abs(row)
        return {
            "tx_hash": row.get("tx_hash", ""),
            "block_height": row.get("block_height", 0),
            "block_hash": row.get("block_hash", ""),
            "from": row.get("from_addr", row.get("from", "")),
            "to": row.get("to_addr", row.get("to", "")),
            "value": money["value"],
            "fee": money["fee"],
            "burned": money["burned"],
            "gas_used": observed_optional_int(row, "gas_used"),
            "status": SqliteDatabase._normalize_tx_status(row.get("status")),
            "timestamp": row.get("created_at", row.get("timestamp", 0)),
        }

    def get_receipts_by_block(self, block_height: int) -> List[Dict]:
        height = int(block_height)
        out: List[Dict] = []
        for tx in self.get_transactions_in_block(height):
            tx_hash = tx.get("hash", tx.get("tx_hash", "")) or ""
            rcpt = self.get_tx_receipt(tx_hash) if tx_hash else None
            if rcpt:
                out.append(self._format_receipt_row(rcpt))
            else:
                out.append(
                    self._format_receipt_row(
                        {
                            **tx,
                            "tx_hash": tx_hash,
                            "block_hash": "",
                            "created_at": tx.get("timestamp", 0),
                        }
                    )
                )
        out.sort(key=lambda r: int(r.get("timestamp", 0)))
        return out

    def _serialize_tx_row(self, row: Dict, viewer_addr: str = "") -> Dict:
        from runtime.amount import tx_money_abs

        viewer = SqliteDatabase._normalize_address(viewer_addr)
        from_addr = SqliteDatabase._normalize_address(row.get("from_addr", ""))
        to_addr = SqliteDatabase._normalize_address(row.get("to_addr", ""))
        direction = "unknown"
        if viewer:
            if from_addr == viewer and to_addr == viewer:
                direction = "self"
            elif from_addr == viewer:
                direction = "sent"
            elif to_addr == viewer:
                direction = "received"
        money = tx_money_abs(row)
        return {
            "hash": row.get("hash", ""),
            "block_height": row.get("block_height", 0),
            "from": from_addr,
            "to": to_addr,
            "value": money["value"],
            "fee": money["fee"],
            "burned": money["burned"],
            "gas_used": observed_optional_int(row, "gas_used"),
            "status": SqliteDatabase._normalize_tx_status(row.get("status")),
            "timestamp": int(row.get("timestamp", 0)),
            "direction": direction,
        }

    def _iter_transaction_rows(self) -> List[Dict]:
        rows: List[Dict] = []
        for _key, value in self._scan_prefix(kc.P_TX):
            row = self._loads_tx_blob_or_none(value, context="TX row")
            if row is None:
                logger.warning(
                    "[RocksStore] corrupt TX row skipped (decode_failures=%s)",
                    self._json_decode_failures,
                )
                continue
            rows.append(row)
        return rows

    def get_address_activity(self, address: str) -> Dict:
        from runtime.amount import account_balance_abs, account_satoshi

        addr = SqliteDatabase._normalize_address(address)
        sent = self.count_transactions_by_address(addr, "sent")
        received = self.count_transactions_by_address(addr, "received")
        total = self.count_transactions_by_address(addr, "all")
        last_h = self._max_indexed_tx_height(addr)
        blocks_proposed = 0
        blocks_proposed_known = False
        if self._proposer_counts_enabled():
            counted = self._read_plain_meta_int(f"proposer_count:{addr}")
            blocks_proposed = int(counted or 0)
            blocks_proposed_known = True
        acct = self._load_account(addr)
        return {
            "address": addr,
            "balance": account_balance_abs(acct),
            "balance_satoshi": account_satoshi(acct),
            "nonce": int(acct.get("nonce", 0) or 0),
            "sent_count": sent,
            "received_count": received,
            "tx_count": total,
            "blocks_proposed": blocks_proposed,
            "blocks_proposed_known": blocks_proposed_known,
            "last_tx_height": last_h,
            "is_contract": bool(acct.get("code")),
        }

    def _decode_proposer_audit_blob(self, raw: bytes | None) -> Optional[Dict]:
        if raw is None:
            return None
        try:
            audit = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            self._json_decode_failures += 1
            logger.warning(
                "[RocksStore] corrupt proposer_audit list row skipped "
                "(decode_failures=%s): %s",
                self._json_decode_failures,
                exc,
            )
            return None
        return audit if isinstance(audit, dict) else None

    def _format_proposer_audit_row(self, audit: Dict) -> Dict:
        from runtime.amount import money_abs

        return {
            "height": audit.get("height", 0),
            "block_hash": audit.get("block_hash", ""),
            "proposer": audit.get("proposer", ""),
            "tx_count": audit.get("tx_count", 0),
            "total_burned": money_abs(audit.get("total_burned", 0.0), field="total_burned"),
            "timestamp": audit.get("block_ts", audit.get("timestamp", 0)),
            "recorded_at": audit.get("recorded_at", 0),
        }

    def get_proposer_audit_log(
        self,
        limit: int = 50,
        offset: int = 0,
        proposer: str = "",
    ) -> List[Dict]:
        """Newest-first page via height keys. Never prefix-scans the audit CF."""
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        want = SqliteDatabase._normalize_address(proposer) if proposer else ""
        tip = int(self.get_chain_tip() or 0)
        collected: List[Dict] = []
        if not want:
            h = tip - offset
            skip = 0
            max_seek = limit + 64
        else:
            h = tip
            skip = offset
            max_seek = max(512, (offset + limit) * 8)
        sought = 0
        while h >= 0 and len(collected) < limit and sought < max_seek:
            raw = self._raw_get(kc.key_proposer_audit(h))
            sought += 1
            h -= 1
            audit = self._decode_proposer_audit_blob(raw)
            if not audit:
                continue
            if want and SqliteDatabase._normalize_address(audit.get("proposer", "")) != want:
                continue
            if skip > 0:
                skip -= 1
                continue
            collected.append(audit)
        return [self._format_proposer_audit_row(r) for r in collected]

    def count_proposer_audit(self, proposer: str = "") -> int | None:
        if not str(proposer or "").strip():
            return self._cached_prefix_len("stats_proposer_audit", kc.P_PROPOSER_AUDIT)
        if not self._proposer_counts_enabled():
            return None
        addr = SqliteDatabase._normalize_address(proposer)
        n = self._read_plain_meta_int(f"proposer_count:{addr}")
        return int(n or 0)

    def get_proposer_stats(self, limit: int = 20) -> List[Dict]:
        """Top proposers from O(proposers) meta counters — not a full audit scan."""
        from runtime.amount import money_abs

        limit = max(1, min(int(limit), 100))
        if not self._proposer_counts_enabled():
            return []
        prefix = kc.key_meta("proposer_count:")
        rows: List[Dict] = []
        for key, value in self._scan_prefix(prefix):
            try:
                addr = key[len(prefix) :].decode("utf-8")
                n = int(value.decode("utf-8"))
            except (UnicodeDecodeError, ValueError, TypeError):
                continue
            rows.append(
                {
                    "proposer": addr,
                    "blocks_proposed": n,
                    "total_txs": 0,
                    "total_burned": money_abs(0, field="total_burned"),
                    "last_height": None,
                    "first_height": None,
                }
            )
        rows.sort(key=lambda r: int(r.get("blocks_proposed", 0) or 0), reverse=True)
        return rows[:limit]

    def get_proposer_detail(self, address: str, recent_limit: int = 10) -> Dict:
        from runtime.amount import money_abs

        addr = SqliteDatabase._normalize_address(address)
        known = self._proposer_counts_enabled()
        n = self._read_plain_meta_int(f"proposer_count:{addr}") if known else None
        recent = self.get_proposer_audit_log(limit=recent_limit, offset=0, proposer=addr)
        return {
            "proposer": addr,
            "blocks_proposed": int(n or 0),
            "blocks_proposed_known": bool(known),
            "total_txs": 0,
            "total_burned": money_abs(0, field="total_burned"),
            "first_height": recent[-1]["height"] if recent else None,
            "last_height": recent[0]["height"] if recent else None,
            "recent_blocks": recent,
        }

    # ── bridge (cross-chain) ─────────────────────────────────────────────

    @staticmethod
    def bridge_credit_key(from_chain: str, event_tx_hash: str, log_index: int = 0) -> str:
        """Replay key from source event identity (not claim recipient/amount)."""
        from crypto import native

        raw = (
            f"{(from_chain or '').strip()}:"
            f"{(event_tx_hash or '').strip()}:"
            f"{int(log_index)}"
        ).lower()
        return native.sha256_hex(raw.encode())

    def save_bridge_lock(
        self,
        from_addr: str,
        to_chain: str,
        to_addr: str,
        amount: float,
        tx_hash: str,
    ) -> None:
        from runtime.amount import money_abs

        row = {
            "tx_hash": tx_hash,
            "from_addr": from_addr,
            "to_chain": to_chain,
            "to_addr": to_addr,
            "amount": money_abs(amount),
            "status": "pending",
            "created_at": int(time.time()),
        }
        with self._write_lock:
            self._raw_put(kc.key_bridge_lock(tx_hash), json.dumps(row).encode("utf-8"))

    def confirm_bridge_lock(self, tx_hash: str) -> None:
        with self._write_lock:
            raw = self._raw_get(kc.key_bridge_lock(tx_hash))
            if not raw:
                return
            row = self._loads_json_or_none(raw, context=f"bridge_lock {tx_hash[:16]}")
            if row is None:
                return
            row["status"] = "confirmed"
            self._raw_put(kc.key_bridge_lock(tx_hash), json.dumps(row).encode("utf-8"))

    def get_bridge_locks(self, limit: int = 50) -> List[Dict]:
        limit = max(1, min(int(limit), 5000))
        rows: List[Dict] = []
        start = kc.prefix_bridge_locks()
        # Keys are tx-hash order, not time. Bound the walk; do not scan 100k.
        for _key, value in self._scan_range(
            start, kc.prefix_family_end(start), 5000
        ):
            try:
                rows.append(json.loads(value.decode("utf-8")))
            except Exception as exc:
                self._json_decode_failures += 1
                logger.warning(
                    "[RocksStore] corrupt bridge_lock row skipped "
                    "(decode_failures=%s): %s",
                    self._json_decode_failures,
                    exc,
                )
                continue
        rows.sort(key=lambda r: int(r.get("created_at", 0) or 0), reverse=True)
        from runtime.amount import money_abs

        out = []
        for row in rows[:limit]:
            row["amount"] = money_abs(row.get("amount", 0), field="amount")
            out.append(row)
        return out

    def has_bridge_credit(self, credit_key: str) -> bool:
        return self._raw_get(kc.key_bridge_credit(credit_key)) is not None

    def save_bridge_credit(
        self,
        event_tx_hash: str,
        recipient: str,
        amount: float,
        from_chain: str,
        log_index: int = 0,
    ) -> str:
        key = self.bridge_credit_key(from_chain, event_tx_hash, log_index)
        if self.has_bridge_credit(key):
            return key
        from runtime.amount import money_abs

        row = {
            "credit_key": key,
            "l1_tx_hash": event_tx_hash,
            "recipient": recipient,
            "amount": money_abs(amount),
            "from_chain": from_chain,
            "log_index": int(log_index),
            "credited_at": int(time.time()),
        }
        with self._write_lock:
            self._raw_put(kc.key_bridge_credit(key), json.dumps(row).encode("utf-8"))
        return key

    def claim_and_credit_bridge_event(
        self,
        from_chain: str,
        event_tx_hash: str,
        recipient: str,
        amount: float,
        log_index: int = 0,
        abs_tx_hash: str = "",
    ) -> Dict:
        """Insert-if-absent replay claim then credit recipient in one Rocks batch."""
        key = self.bridge_credit_key(from_chain, event_tx_hash, log_index)
        with self.atomic():
            if self.has_bridge_credit(key):
                return {"credited": False, "duplicate": True, "credit_key": key}
            from runtime.amount import money_abs

            amt = money_abs(amount)
            row = {
                "credit_key": key,
                "l1_tx_hash": event_tx_hash,
                "recipient": recipient,
                "amount": amt,
                "from_chain": from_chain,
                "log_index": int(log_index),
                "credited_at": int(time.time()),
            }
            self._raw_put(kc.key_bridge_credit(key), json.dumps(row).encode("utf-8"))
            self.balance_delta(recipient, amt)
            lock_hash = (abs_tx_hash or event_tx_hash or "").strip()
            if lock_hash:
                raw = self._raw_get(kc.key_bridge_lock(lock_hash))
                if raw:
                    lock_row = self._loads_json_or_none(
                        raw, context=f"bridge_lock {lock_hash[:16]}"
                    )
                    if lock_row is not None:
                        lock_row["status"] = "confirmed"
                        self._raw_put(
                            kc.key_bridge_lock(lock_hash),
                            json.dumps(lock_row).encode("utf-8"),
                        )
        return {"credited": True, "duplicate": False, "credit_key": key}

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
    ) -> None:
        """Debit sender (fail on underflow), burn fee share, persist lock — one Rocks batch."""
        from runtime.amount import dual_write_balance, from_satoshi_float, money_abs, try_debit_satoshi

        with self.atomic():
            row = self._load_account(from_addr)
            cur = int(row.get("balance_satoshi", 0) or 0)
            new_sat = try_debit_satoshi(cur, money_abs(amount))
            dual_write_balance(row, from_satoshi_float(new_sat))
            row["balance_satoshi"] = new_sat
            self._save_account_row(row)
            if burn_amount and burn_address:
                self.balance_delta(burn_address, money_abs(burn_amount, field="burn_amount"))
            lock_row = {
                "tx_hash": tx_hash,
                "from_addr": from_addr,
                "to_chain": to_chain,
                "to_addr": to_addr,
                "amount": money_abs(net_amount, field="net_amount"),
                "status": "pending",
                "created_at": int(time.time()),
            }
            self._raw_put(kc.key_bridge_lock(tx_hash), json.dumps(lock_row).encode("utf-8"))

    def refund_pending_bridge_lock(self, tx_hash: str) -> Dict:
        """Credit back pending lock amount and mark refunded atomically."""
        from runtime.amount import money_abs

        with self.atomic():
            raw = self._raw_get(kc.key_bridge_lock(tx_hash))
            if not raw:
                return {"refunded": False, "error": "Lock not found or already processed"}
            lock = self._loads_json_or_none(raw, context=f"bridge_lock {tx_hash[:16]}")
            if lock is None or lock.get("status") != "pending":
                return {"refunded": False, "error": "Lock not found or already processed"}
            self.balance_delta(lock["from_addr"], money_abs(lock["amount"]))
            lock["status"] = "refunded"
            self._raw_put(kc.key_bridge_lock(tx_hash), json.dumps(lock).encode("utf-8"))
        return {
            "refunded": True,
            "tx_hash": tx_hash,
            "amount": money_abs(lock["amount"]),
        }

    # ── burn ──────────────────────────────────────────────────────────────

    def _insert_burn_record(self, block_height: int, burned_amount: float) -> None:
        from runtime.amount import from_satoshi_float, money_abs, to_satoshi

        burned = money_abs(burned_amount, field="burned")
        total = from_satoshi_float(
            to_satoshi(self.get_total_burned()) + to_satoshi(burned)
        )
        row = {
            "block_height": int(block_height),
            "burned_amount": burned,
            "total_burned": total,
        }
        self._raw_put(kc.key_burn(int(block_height)), json.dumps(row).encode("utf-8"))

    def record_burn(self, block_height: int, burned_amount: float) -> None:
        with self._write_lock:
            self._insert_burn_record(block_height, burned_amount)

    def get_total_burned(self) -> float:
        # prefix_last is O(1); a full P_BURN scan grows with height and poisoned
        # both persist (_insert_burn_record) and GET /status after ~30h soak.
        from runtime.amount import money_abs

        engine = self._engine
        last_kv = None
        if engine is not None and hasattr(engine, "prefix_last"):
            try:
                last_kv = engine.prefix_last(kc.P_BURN)
            except Exception as exc:
                logger.warning("[RocksStore] prefix_last burn total failed: %s", exc)
                last_kv = None
        if last_kv:
            _key, value = last_kv
            row = self._loads_json_or_none(bytes(value), context="burn_total")
            if row is None:
                return 0.0
            return money_abs(row.get("total_burned", 0.0), field="total_burned")
        rows = self._scan_prefix(kc.P_BURN)
        if not rows:
            return 0.0
        last = max(rows, key=lambda kv: kc.unpack_u64(kv[0][1:9]))
        row = self._loads_json_or_none(last[1], context="burn_total")
        if row is None:
            return 0.0
        return money_abs(row.get("total_burned", 0.0), field="total_burned")

    def get_burn_stats(self) -> Dict:
        total = self.get_total_burned()
        return {"total_burned": total, "burn_address": ""}

    # ── block commit ──────────────────────────────────────────────────────

    def persist_block_atomic(
        self,
        block: Dict,
        transactions: List[Dict],
        burned_amount: float = 0.0,
        burn_address: str = "",
    ) -> bool:
        with self.atomic():
            try:
                self._persist_block_locked(block, transactions, burned_amount, burn_address)
                return True
            except Exception as exc:
                print(f"[RocksDB] persist_block_atomic error: {exc}")
                return False

    def _persist_block_locked(
        self,
        block: Dict,
        transactions: List[Dict],
        burned_amount: float = 0.0,
        burn_address: str = "",
    ) -> None:
        self._insert_block(block)
        block_hash = block.get("hash", block.get("block_hash", ""))
        block_height = int(block.get("height", block.get("number", 0)) or 0)
        for tx in transactions:
            self._insert_transaction(tx)
            self._insert_tx_receipt(tx, block_hash, block_height)
        if burned_amount > 0:
            self._insert_burn_record(block_height, burned_amount)
            if burn_address:
                self._apply_balance_delta(burn_address, burned_amount)

    # ── truncate / reorg ────────────────────────────────────────────────

    def reorg_truncate_above(self, height: int) -> None:
        self._drop_root_acc()
        cut = int(height)
        for key, value in list(self._scan_prefix(kc.prefix_block_heights())):
            h = kc.unpack_u64(key[1:9])
            if h <= cut:
                continue
            block = self._loads_block_blob_or_none(value, context="reorg block")
            if block is None:
                logger.warning(
                    "reorg_truncate_above: corrupt block JSON at height>%s "
                    "(decode_failures=%s)",
                    cut,
                    self._json_decode_failures,
                )
            else:
                block_hash = block.get("hash", block.get("block_hash", "")) or ""
                if block_hash:
                    self._raw_delete(kc.key_block_hash_to_height(block_hash))
            self._raw_delete(key)
        for key, _value in list(self._scan_prefix(kc.P_BLOCK_TX)):
            if len(key) >= 9 and kc.unpack_u64(key[1:9]) > cut:
                self._raw_delete(key)
        for key, value in list(self._scan_prefix(kc.P_TX)):
            row = self._loads_tx_blob_or_none(value, context="reorg tx")
            if row is None:
                logger.warning(
                    "reorg_truncate_above: corrupt tx JSON above height>%s "
                    "(decode_failures=%s)",
                    cut,
                    self._json_decode_failures,
                )
                self._raw_delete(key)
                continue
            if int(row.get("block_height", 0) or 0) > cut:
                self._delete_tx_indexes(row)
                self._raw_delete(key)
        for key, value in list(self._scan_prefix(kc.P_TX_RECEIPT)):
            row = self._loads_receipt_blob_or_none(value, context="reorg receipt")
            if row is None:
                logger.warning(
                    "reorg_truncate_above: corrupt receipt JSON above height>%s "
                    "(decode_failures=%s)",
                    cut,
                    self._json_decode_failures,
                )
                self._raw_delete(key)
                continue
            if int(row.get("block_height", 0) or 0) > cut:
                self._raw_delete(key)
        for key, value in self._scan_prefix(kc.P_PROPOSER_AUDIT):
            if kc.unpack_u64(key[1:9]) > cut:
                if self._proposer_counts_enabled():
                    audit = self._loads_json_or_none(
                        value, context="reorg proposer_audit"
                    )
                    if audit:
                        self._bump_proposer_count(str(audit.get("proposer", "")), -1)
                self._raw_delete(key)
        for key, _value in self._scan_prefix(kc.P_BURN):
            if kc.unpack_u64(key[1:9]) > cut:
                self._raw_delete(key)
        for key, value in list(self._scan_prefix(kc.P_STATE_ROOT_MM)):
            if len(key) >= 9 and kc.unpack_u64(key[1:9]) > cut:
                self._raw_delete(key)
        self._purge_height_scoped_indexes(cut)
        self._invalidate_obs_meta()
        tip = self.get_block(cut)
        if tip:
            self._touch_live_state_root_meta(tip)
            # Keep O(1) tip meta in sync with truncated height (v1.3.66+).
            self._raw_put(kc.key_meta("chain_tip"), str(cut).encode("utf-8"))
            tip_hash = tip.get("hash", tip.get("block_hash", "")) or ""
            if tip_hash:
                self._raw_put(kc.key_meta("chain_tip_hash"), tip_hash.encode("utf-8"))
            else:
                self._raw_delete(kc.key_meta("chain_tip_hash"))
        else:
            for meta_key in (
                "live_state_root",
                "live_state_root_height",
                "state_root",
                "chain_tip",
                "chain_tip_hash",
            ):
                self._raw_delete(kc.key_meta(meta_key))

    def _purge_height_scoped_indexes(self, cut: int) -> None:
        """Remove secondary Rocks indexes tied to blocks above *cut* (reorg safety)."""
        cut = int(cut)
        for key, _value in list(self._scan_prefix(kc.prefix_evm_logs())):
            if len(key) >= 9 and kc.unpack_u64(key[1:9]) > cut:
                self._raw_delete(key)
        for key, value in list(self._scan_prefix(kc.P_EVM_LOG_TX)):
            try:
                row = json.loads(value.decode("utf-8"))
                bh = int(row.get("block_height", 0) or 0)
            except Exception as exc:
                self._json_decode_failures += 1
                logger.warning(
                    "reorg purge: corrupt evm_log_tx JSON "
                    "(decode_failures=%s): %s",
                    self._json_decode_failures,
                    exc,
                )
                self._raw_delete(key)
                continue
            if bh > cut:
                self._raw_delete(key)
        for key, value in list(self._scan_prefix(kc.prefix_tx_prop_all())):
            try:
                row = json.loads(value.decode("utf-8"))
                bh = int(row.get("block_height", 0) or 0)
            except Exception as exc:
                self._json_decode_failures += 1
                logger.warning(
                    "reorg purge: corrupt tx_propagation JSON "
                    "(decode_failures=%s): %s",
                    self._json_decode_failures,
                    exc,
                )
                self._raw_delete(key)
                continue
            if bh > cut:
                self._raw_delete(key)

    def truncate_chain_state(self, height: int) -> int:
        with self.atomic():
            before = self.get_chain_tip()
            self.reorg_truncate_above(int(height))
            return max(0, before - int(height))

    def truncate_blocks_above(self, height: int) -> int:
        return self.truncate_chain_state(height)

    def truncate_all_blocks(self) -> int:
        count = 0
        with self.atomic():
            for key, _value in list(self._scan_prefix(kc.prefix_block_heights())):
                self._raw_delete(key)
                count += 1
        return count

    # ── observability stubs (index tables optional in P1) ───────────────

    def record_state_root_mismatch(
        self,
        height: int,
        expected_root: str,
        computed_root: str,
        source: str = "p2p",
        proposer: str = "",
        *,
        _no_commit: bool = False,
    ) -> None:
        row = {
            "height": int(height),
            "expected_root": expected_root,
            "computed_root": computed_root,
            "source": source,
            "proposer": proposer,
            "created_at": int(time.time()),
        }
        key = kc.P_STATE_ROOT_MM + kc.pack_u64(int(height)) + computed_root[:8].encode()
        self._raw_put(key, json.dumps(row).encode("utf-8"))

    def get_state_root_mismatches(self, limit: int = 20) -> List[Dict]:
        limit = max(1, min(int(limit), 100))
        rows: List[Dict] = []
        for _key, value in self._scan_prefix(kc.P_STATE_ROOT_MM, limit=limit * 4):
            try:
                rows.append(json.loads(value.decode("utf-8")))
            except Exception as exc:
                self._json_decode_failures += 1
                logger.warning(
                    "[RocksStore] corrupt state_root_mismatch row skipped "
                    "(decode_failures=%s): %s",
                    self._json_decode_failures,
                    exc,
                )
                continue
        rows.sort(key=lambda r: int(r.get("created_at", 0) or 0), reverse=True)
        return rows[:limit]

    def record_tx_propagation_event(
        self,
        tx_hash: str,
        stage: str,
        *,
        node_id: str = "",
        peer_id: str = "",
        block_height: int = 0,
        detail: Dict | None = None,
        _no_commit: bool = False,
    ) -> None:
        row = {
            "tx_hash": tx_hash,
            "stage": stage,
            "node_id": node_id,
            "peer_id": peer_id,
            "block_height": int(block_height),
            "detail": detail or {},
            "created_at": int(time.time()),
        }
        key = kc.key_tx_prop(tx_hash, stage)
        self._raw_put(key, json.dumps(row).encode("utf-8"))

    def _decode_tx_propagation_event(self, raw: bytes) -> Optional[Dict]:
        row = self._loads_json_or_none(raw, context="tx_propagation")
        if row is None:
            return None
        detail = row.get("detail") or {}
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except Exception as exc:
                self._json_decode_failures += 1
                logger.warning(
                    "[RocksStore] corrupt tx_propagation detail "
                    "(decode_failures=%s): %s",
                    self._json_decode_failures,
                    exc,
                )
                detail = {}
        if not isinstance(detail, dict):
            detail = {}
        return {
            "stage": row.get("stage", ""),
            "node_id": row.get("node_id", ""),
            "peer_id": row.get("peer_id", ""),
            "block_height": int(row.get("block_height", 0) or 0),
            "detail": detail,
            "timestamp": int(row.get("created_at", 0) or 0),
        }

    def _tx_propagation_status(
        self,
        events: List[Dict],
        receipt: Optional[Dict],
        tx_row: Optional[Dict],
    ) -> str:
        stages = [e.get("stage", "") for e in events]
        if receipt or tx_row:
            return "confirmed"
        if "block_included" in stages:
            return "included"
        if "mempool_local" in stages or "mempool_remote" in stages:
            return "mempool"
        if events:
            return "propagating"
        return "unknown"

    def get_tx_propagation_trace(self, tx_hash: str) -> Dict:
        events = [
            ev
            for ev in (
                self._decode_tx_propagation_event(value)
                for _key, value in self._scan_prefix(kc.prefix_tx_prop(tx_hash), limit=500)
            )
            if ev is not None
        ]
        events.sort(key=lambda e: int(e.get("timestamp", 0) or 0))
        receipt = self.get_tx_receipt(tx_hash)
        tx_row = self.get_transaction(tx_hash)
        return {
            "tx_hash": tx_hash,
            "status": self._tx_propagation_status(events, receipt, tx_row),
            "events": events,
            "receipt": receipt,
            "transaction": tx_row,
        }

    def get_recent_tx_propagation(self, limit: int = 20) -> List[Dict]:
        limit = max(1, min(int(limit), 100))
        last_ts: dict[str, int] = {}
        for _key, value in self._scan_prefix(kc.prefix_tx_prop_all(), limit=50_000):
            try:
                row = json.loads(value.decode("utf-8"))
            except Exception as exc:
                self._json_decode_failures += 1
                logger.warning("rocks tx-prop JSON decode failed: %s", exc)
                continue
            th = str(row.get("tx_hash") or "")
            if not th:
                continue
            ts = int(row.get("created_at", 0) or 0)
            last_ts[th] = max(last_ts.get(th, 0), ts)
        ordered = sorted(last_ts.items(), key=lambda item: item[1], reverse=True)[:limit]
        return [self.get_tx_propagation_trace(tx_hash) for tx_hash, _ in ordered]

    def _rocks_runtime_core(self) -> Dict:
        """Cheap Rocks snapshot for /metrics — no prefix scans."""
        stats: Dict = {
            "engine": self.engine,
            "json_decode_failures": int(self._json_decode_failures),
            "rocksdb_tuning": {
                "block_cache_mb": self.block_cache_mb,
                "write_buffer_mb": self.write_buffer_mb,
                "sync": self.synchronous,
                "column_families": self.column_families,
                "json_decode_failures": int(self._json_decode_failures),
            },
        }
        if hasattr(self._engine, "storage_properties"):
            try:
                stats["rocksdb_properties"] = dict(self._engine.storage_properties())
            except Exception as exc:
                logger.warning("rocks storage_properties failed: %s", exc)
                stats["rocksdb_properties_error"] = str(exc)
        if hasattr(self._engine, "tuning_config"):
            try:
                stats["rocksdb_tuning"].update(dict(self._engine.tuning_config()))
            except Exception as exc:
                logger.warning("rocks tuning_config failed: %s", exc)
                stats["rocksdb_tuning_error"] = str(exc)
        return stats

    def get_rocks_runtime_stats(self) -> Dict:
        """Prometheus path: tuning + LSM properties only (no tx/account prefix scan)."""
        return self._rocks_runtime_core()

    def get_stats(self) -> Dict:
        stats = self._rocks_runtime_core()
        stats["height"] = self.get_chain_tip()
        stats["total_transactions"] = self._cached_prefix_len("stats_tx_count", kc.P_TX)
        stats["total_accounts"] = self._cached_prefix_len(
            "stats_account_count", kc.prefix_accounts()
        )
        stats["total_burned"] = self.get_total_burned()
        stats["total_supply"] = self.get_total_supply()
        return stats

    def save_slash_event(self, validator: str, reason: str, epoch: int, penalty: int) -> None:
        events = self.get_meta("slash_events", []) or []
        events.append(
            {
                "validator": validator,
                "reason": reason,
                "epoch": int(epoch),
                "penalty": int(penalty),
                "timestamp": int(time.time()),
            }
        )
        self.set_meta("slash_events", events[-500:])

    def get_slash_events(self, limit: int = 100) -> List[Dict]:
        events = self.get_meta("slash_events", []) or []
        return list(events)[-int(limit) :]

    def _decode_evm_log_row(self, raw: bytes) -> Optional[Dict]:
        row = self._loads_json_or_none(raw, context="evm_log")
        if row is None:
            return None
        topics = row.get("topics", [])
        if isinstance(topics, str):
            try:
                topics = json.loads(topics)
            except Exception as exc:
                self._json_decode_failures += 1
                logger.warning(
                    "[RocksStore] corrupt evm_log topics "
                    "(decode_failures=%s): %s",
                    self._json_decode_failures,
                    exc,
                )
                topics = []
        row["topics"] = topics if isinstance(topics, list) else []
        return row

    def save_evm_logs(
        self,
        contract_address: str,
        logs: List[Dict],
        block_height: int = 0,
        tx_hash: str = "",
        timestamp: int = 0,
    ) -> int:
        if not logs:
            return 0
        ts = int(timestamp or time.time())
        saved = 0
        with self.atomic():
            for i, entry in enumerate(logs):
                topics = entry.get("topics", [])
                if not isinstance(topics, list):
                    topics = []
                row = {
                    "contract_address": contract_address,
                    "block_height": int(block_height),
                    "tx_hash": tx_hash or "",
                    "log_index": int(i),
                    "topics": topics,
                    "data": str(entry.get("data", "")),
                    "timestamp": ts,
                }
                payload = json.dumps(row, ensure_ascii=False).encode("utf-8")
                self._raw_put(kc.key_evm_log(block_height, tx_hash, i), payload)
                self._raw_put(kc.key_evm_log_tx(tx_hash, i), payload)
                saved += 1
        return saved

    def get_evm_logs(self, contract_address: str = "", limit: int = 100) -> List[Dict]:
        return self.query_evm_logs(
            addresses=[contract_address] if contract_address else None,
            limit=limit,
        )

    def get_evm_logs_by_tx(self, tx_hash: str) -> List[Dict]:
        if not tx_hash:
            return []
        rows = self._scan_prefix(kc.prefix_evm_logs_tx(tx_hash), limit=10_000)
        logs = [
            row
            for row in (self._decode_evm_log_row(val) for _, val in rows)
            if row is not None
        ]
        logs.sort(key=lambda r: (int(r.get("log_index", 0) or 0), int(r.get("block_height", 0) or 0)))
        return logs

    def _evm_log_tip_height(self) -> int:
        last = self._prefix_last_kv(kc.P_EVM_LOG)
        if last is not None and len(last[0]) >= 1 + 8:
            try:
                return int(kc.unpack_u64(last[0][1:9]))
            except ValueError:
                pass
        return int(self.get_chain_tip() or 0)

    def _scan_evm_log_blobs(
        self, from_block: int, to_block: Optional[int], budget: int
    ) -> List[tuple[bytes, bytes]]:
        """Logs in [from_block, to_block], O(rows in range) — not all P_EVM_LOG."""
        start = kc.prefix_evm_logs_block(from_block)
        engine = self._engine
        if to_block is None and engine is not None and hasattr(engine, "scan_range"):
            end = kc.prefix_family_end(kc.P_EVM_LOG)
            return self._scan_range(start, end, budget)
        if to_block is None:
            to_block = self._evm_log_tip_height()
        to_block = int(to_block)
        if from_block > to_block:
            return []
        end = kc.prefix_evm_logs_block(to_block + 1)
        if engine is not None and hasattr(engine, "scan_range"):
            return self._scan_range(start, end, budget)
        # Old wheel: per-height prefix, never a full P_EVM_LOG walk.
        out: List[tuple[bytes, bytes]] = []
        remaining = budget
        for height in range(from_block, to_block + 1):
            if remaining <= 0:
                break
            chunk = self._scan_prefix(
                kc.prefix_evm_logs_block(height), limit=remaining
            )
            out.extend(chunk)
            remaining -= len(chunk)
        return out

    def query_evm_logs(
        self,
        from_block: int = 0,
        to_block: Optional[int] = None,
        addresses: Optional[List[str]] = None,
        topics: Optional[List] = None,
        limit: int = 10_000,
    ) -> List[Dict]:
        from_block = max(0, int(from_block))
        limit = max(1, min(int(limit), 10_000))
        addr_set = None
        if addresses:
            addr_set = {kc.normalize_address_key(a) for a in addresses if a}
        if addr_set or topics:
            budget = min(50_000, max(limit * 32, 256))
        else:
            budget = limit
        rows = self._scan_evm_log_blobs(from_block, to_block, budget)
        out: List[Dict] = []
        for _, val in rows:
            row = self._decode_evm_log_row(val)
            if row is None:
                continue
            bh = int(row.get("block_height", 0) or 0)
            if to_block is not None and (bh < from_block or bh > int(to_block)):
                continue
            if bh < from_block:
                continue
            if addr_set and kc.normalize_address_key(row.get("contract_address", "")) not in addr_set:
                continue
            if topics and not SqliteDatabase._evm_log_topics_match(row.get("topics") or [], topics):
                continue
            out.append(row)
            if len(out) >= limit:
                break
        out.sort(key=lambda r: (int(r.get("block_height", 0) or 0), int(r.get("log_index", 0) or 0)))
        return out

    def _decode_nft_token(self, raw: bytes) -> Optional[Dict]:
        row = self._loads_json_or_none(raw, context="nft_token")
        if row is None:
            return None
        meta = row.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception as exc:
                self._json_decode_failures += 1
                logger.warning(
                    "[RocksStore] corrupt nft_token metadata "
                    "(decode_failures=%s): %s",
                    self._json_decode_failures,
                    exc,
                )
                meta = {}
        row["metadata"] = meta if isinstance(meta, dict) else {}
        row["for_sale"] = bool(row.get("for_sale"))
        from runtime.amount import money_abs
        row["price"] = money_abs(row.get("price", 0), field="price")
        return row

    def save_nft_token(self, token: Dict) -> None:
        from runtime.amount import money_abs

        tid = str(token.get("token_id", "") or "")
        if not tid:
            return
        row = {
            "token_id": tid,
            "name": token.get("name", ""),
            "description": token.get("description", ""),
            "image_url": token.get("image_url", ""),
            "owner": token.get("owner", ""),
            "creator": token.get("creator", ""),
            "price": money_abs(token.get("price", 0), field="price"),
            "for_sale": bool(token.get("for_sale")),
            "created_at": int(token.get("created_at", 0) or 0),
            "metadata": token.get("metadata") or {},
        }
        self._raw_put(
            kc.key_nft_token(tid),
            json.dumps(row, ensure_ascii=False).encode("utf-8"),
        )

    def get_nft_tokens(self) -> List[Dict]:
        rows = self._scan_prefix(kc.prefix_nft_tokens(), limit=50_000)
        out = [
            row
            for row in (self._decode_nft_token(val) for _, val in rows)
            if row is not None
        ]
        out.sort(key=lambda r: int(r.get("created_at", 0) or 0))
        return out

    def _decode_nft_offer(self, raw: bytes) -> Optional[Dict]:
        from runtime.amount import money_abs

        row = self._loads_json_or_none(raw, context="nft_offer")
        if row is None:
            return None
        row["price"] = money_abs(row.get("price", 0), field="price")
        return row

    def save_nft_offer(self, offer: Dict) -> None:
        from runtime.amount import money_abs

        oid = str(offer.get("offer_id", "") or "")
        if not oid:
            return
        row = dict(offer)
        row["offer_id"] = oid
        row["price"] = money_abs(row.get("price", 0), field="price")
        row["expires_at"] = int(row.get("expires_at", 0) or 0)
        row["created_at"] = int(row.get("created_at", 0) or 0)
        self._raw_put(
            kc.key_nft_offer(oid),
            json.dumps(row, ensure_ascii=False).encode("utf-8"),
        )

    def get_nft_offers(self) -> List[Dict]:
        rows = self._scan_prefix(kc.prefix_nft_offers(), limit=50_000)
        out = [
            row
            for row in (self._decode_nft_offer(val) for _, val in rows)
            if row is not None
        ]
        out.sort(key=lambda r: int(r.get("created_at", 0) or 0), reverse=True)
        return out

    def _decode_nft_auction(self, raw: bytes) -> Optional[Dict]:
        from runtime.amount import money_abs

        row = self._loads_json_or_none(raw, context="nft_auction")
        if row is None:
            return None
        for field in ("start_price", "reserve_price", "current_bid"):
            if field in row and row[field] is not None:
                row[field] = money_abs(row[field], field=field)
        return row

    def save_nft_auction(self, auction: Dict) -> None:
        from runtime.amount import money_abs

        aid = str(auction.get("auction_id", "") or "")
        if not aid:
            return
        row = dict(auction)
        row["auction_id"] = aid
        row["ends_at"] = int(row.get("ends_at", 0) or 0)
        row["created_at"] = int(row.get("created_at", 0) or 0)
        for field in ("start_price", "reserve_price", "current_bid"):
            if field in row and row[field] is not None:
                row[field] = money_abs(row[field], field=field)
        self._raw_put(
            kc.key_nft_auction(aid),
            json.dumps(row, ensure_ascii=False).encode("utf-8"),
        )

    def get_nft_auctions(self) -> List[Dict]:
        rows = self._scan_prefix(kc.prefix_nft_auctions(), limit=50_000)
        out = [
            row
            for row in (self._decode_nft_auction(val) for _, val in rows)
            if row is not None
        ]
        out.sort(key=lambda r: int(r.get("created_at", 0) or 0), reverse=True)
        return out

    def _decode_nft_sale(self, raw: bytes) -> Optional[Dict]:
        from runtime.amount import money_abs

        row = self._loads_json_or_none(raw, context="nft_sale")
        if row is None:
            return None
        return {
            "token_id": row.get("token_id", ""),
            "from": row.get("from", row.get("from_addr", "")),
            "to": row.get("to", row.get("to_addr", "")),
            "price": money_abs(row.get("price", 0), field="price"),
            "type": row.get("type", row.get("sale_type", "buy")),
            "timestamp": int(row.get("timestamp", row.get("created_at", 0)) or 0),
        }

    def save_nft_sale(self, sale: Dict) -> None:
        from runtime.amount import money_abs

        created_at = int(sale.get("timestamp", sale.get("created_at", 0)) or time.time())
        seq = int(sale.get("id", 0) or 0)
        if seq <= 0:
            seq = int(self.get_meta("nft_sale_seq", 0) or 0) + 1
            self.set_meta("nft_sale_seq", seq)
        row = {
            "id": seq,
            "token_id": sale.get("token_id", ""),
            "from": sale.get("from", sale.get("from_addr", "")),
            "to": sale.get("to", sale.get("to_addr", "")),
            "price": money_abs(sale.get("price", 0), field="price"),
            "type": sale.get("type", sale.get("sale_type", "buy")),
            "timestamp": created_at,
            "created_at": created_at,
        }
        self._raw_put(
            kc.key_nft_sale(created_at, seq),
            json.dumps(row, ensure_ascii=False).encode("utf-8"),
        )

    def get_nft_sales(self, limit: int = 100) -> List[Dict]:
        limit = max(1, min(int(limit), 500))
        start = kc.prefix_nft_sales()
        # Inverted timestamp keys: lexicographic first == newest.
        rows = self._scan_range(start, kc.prefix_family_end(start), limit)
        out = [
            row
            for row in (self._decode_nft_sale(val) for _, val in rows)
            if row is not None
        ]
        out.sort(key=lambda r: int(r.get("timestamp", 0) or 0), reverse=True)
        return out[:limit]

    def get_chain_metrics(self, window: int = 32) -> Dict:
        from runtime.amount import from_satoshi_float, to_satoshi

        tip = self.get_chain_tip()
        # Cached prefix lengths — never materialize every tx/receipt/audit on HTTP.
        tx_count = self._cached_prefix_len("stats_tx_count", kc.P_TX)
        receipt_count = self._cached_prefix_len("stats_receipt_count", kc.P_TX_RECEIPT)
        audit_count = self._cached_prefix_len("stats_proposer_audit", kc.P_PROPOSER_AUDIT)
        blocks = self.get_latest_blocks(limit=max(2, int(window)))
        avg_block_time = 0.0
        if len(blocks) >= 2:
            ordered = sorted(blocks, key=lambda b: int(b.get("height", b.get("number", 0)) or 0))
            intervals = []
            for i in range(1, len(ordered)):
                dt = int(ordered[i].get("timestamp", 0)) - int(ordered[i - 1].get("timestamp", 0))
                if dt > 0:
                    intervals.append(dt)
            if intervals:
                avg_block_time = sum(intervals) / len(intervals)
        window_tx = sum(int(b.get("tx_count", 0) or 0) for b in blocks)
        window_elapsed = 0.0
        if len(blocks) >= 2:
            ordered = sorted(
                blocks, key=lambda b: int(b.get("height", b.get("number", 0)) or 0)
            )
            window_elapsed = float(
                max(
                    0,
                    int(ordered[-1].get("timestamp", 0) or 0)
                    - int(ordered[0].get("timestamp", 0) or 0),
                )
            )
        tps = (window_tx / max(window_elapsed, 1.0)) if window_elapsed > 0 else 0.0
        return {
            "height": tip,
            "tx_count": tx_count,
            "receipt_count": receipt_count,
            "proposer_audit_count": audit_count,
            "receipts_enabled": True,
            "proposer_audit_enabled": True,
            "state_root_strict_p2p": True,
            "avg_block_time_sec": round(avg_block_time, 2),
            "target_block_time_sec": 15.0,
            "blocks_sampled": len(blocks),
            "window_tx_count": int(window_tx),
            "window_elapsed_sec": round(window_elapsed, 2),
            "tps": round(tps, 6),
            "burn_last_window": round(
                from_satoshi_float(
                    sum(to_satoshi(b.get("total_burned", 0) or 0) for b in blocks)
                ),
                6,
            ),
            "engine": self.engine,
        }
