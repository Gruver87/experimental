#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hybrid storage: RocksDB hot path + SQLite aux for optional features."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from storage import keycodec as kc
from storage.database import Database as SqliteDatabase
from storage.rocks_store import RocksChainStore


class HybridDatabase:
    """Production store — RocksDB chain/state + SQLite aux.db for cold tables."""

    engine = "rocksdb_hybrid"

    def __init__(self, config: Any):
        chain_path = config.db_path
        aux_path = os.path.join(chain_path, "aux.db")
        rocks_sync = getattr(config, "rocksdb_sync", "FULL")
        sqlite_sync = getattr(config, "sqlite_synchronous", "NORMAL")
        self.db_path = chain_path
        self.synchronous = rocks_sync
        self._core = RocksChainStore(
            chain_path,
            synchronous=rocks_sync,
            block_cache_mb=int(getattr(config, "rocksdb_block_cache_mb", 0) or 0),
            write_buffer_mb=int(getattr(config, "rocksdb_write_buffer_mb", 0) or 0),
            column_families=bool(getattr(config, "rocksdb_column_families", False)),
        )
        self._aux = SqliteDatabase(aux_path, synchronous=sqlite_sync)
        self._aux.initialize()

    @property
    def conn(self):
        """Aux SQLite connection (bridge_locks and legacy SQL helpers)."""
        return self._aux.conn

    def initialize(self) -> None:
        self._core.initialize()
        self._migrate_aux_bridge_once()
        self._migrate_aux_evm_logs_once()
        self._migrate_aux_nft_tokens_once()
        self._migrate_aux_nft_offers_once()
        self._migrate_aux_nft_auctions_once()
        self._migrate_aux_nft_sales_once()

    def _migrate_aux_evm_logs_once(self) -> None:
        if self._core.get_meta("aux_evm_logs_migrated_v1"):
            return
        if not hasattr(self._aux, "conn"):
            return
        try:
            rows = self._aux.conn.execute("SELECT * FROM evm_logs ORDER BY id ASC").fetchall()
        except Exception as exc:
            print(f"[HybridDatabase] aux_evm_logs migrate deferred (will retry): {exc}")
            return
        if not rows:
            self._core.set_meta("aux_evm_logs_migrated_v1", True)
            return
        migrated = 0
        skipped_corrupt = 0
        with self._core.atomic():
            for row in rows:
                item = dict(row)
                topics_raw = item.get("topics") or "[]"
                if isinstance(topics_raw, str):
                    topics = self._aux._loads_json_or_none(topics_raw, context="migrate_evm_topics")
                else:
                    topics = topics_raw
                if topics is None or not isinstance(topics, list):
                    skipped_corrupt += 1
                    continue
                block_height = int(item.get("block_height", 0) or 0)
                tx_hash = str(item.get("tx_hash") or "")
                log_index = int(item.get("log_index", 0) or 0)
                key = kc.key_evm_log(block_height, tx_hash, log_index)
                if self._core._raw_get(key):
                    continue
                payload = json.dumps(
                    {
                        "contract_address": item.get("contract_address", ""),
                        "block_height": block_height,
                        "tx_hash": tx_hash,
                        "log_index": log_index,
                        "topics": topics,
                        "data": str(item.get("data", "")),
                        "timestamp": int(item.get("timestamp", 0) or 0),
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                self._core._raw_put(key, payload)
                self._core._raw_put(kc.key_evm_log_tx(tx_hash, log_index), payload)
                migrated += 1
            # Fail-closed: do not permanently mark migrated while corrupt rows remain.
            if skipped_corrupt == 0:
                self._core.set_meta("aux_evm_logs_migrated_v1", True)
        if skipped_corrupt:
            print(
                f"[HybridDatabase] aux_evm_logs migrate deferred: "
                f"{skipped_corrupt} corrupt JSON row(s) (migrated={migrated})"
            )
        elif migrated:
            print(f"[HybridDatabase] migrated {migrated} evm_logs from aux.db to Rocks")

    def _migrate_aux_nft_tokens_once(self) -> None:
        if self._core.get_meta("aux_nft_tokens_migrated_v1"):
            return
        try:
            rows = self._aux.conn.execute("SELECT * FROM nft_tokens ORDER BY created_at").fetchall()
        except Exception as exc:
            print(f"[HybridDatabase] aux_nft_tokens migrate deferred (will retry): {exc}")
            return
        migrated = 0
        skipped_corrupt = 0
        with self._core.atomic():
            for row in rows:
                item = dict(row)
                tid = str(item.get("token_id", "") or "")
                if not tid or self._core._raw_get(kc.key_nft_token(tid)):
                    continue
                meta = self._aux._loads_json_or_none(
                    item.get("metadata") or "{}", context="migrate_nft_token_meta"
                )
                if meta is None or not isinstance(meta, dict):
                    skipped_corrupt += 1
                    continue
                self._core.save_nft_token({**item, "metadata": meta})
                migrated += 1
            if skipped_corrupt == 0:
                self._core.set_meta("aux_nft_tokens_migrated_v1", True)
        if skipped_corrupt:
            print(
                f"[HybridDatabase] aux_nft_tokens migrate deferred: "
                f"{skipped_corrupt} corrupt JSON row(s) (migrated={migrated})"
            )
        elif migrated:
            print(f"[HybridDatabase] migrated {migrated} nft_tokens from aux.db to Rocks")

    def _migrate_aux_nft_offers_once(self) -> None:
        if self._core.get_meta("aux_nft_offers_migrated_v1"):
            return
        try:
            rows = self._aux.conn.execute("SELECT * FROM nft_offers ORDER BY created_at").fetchall()
        except Exception as exc:
            print(f"[HybridDatabase] aux_nft_offers migrate deferred (will retry): {exc}")
            return
        migrated = 0
        skipped_corrupt = 0
        with self._core.atomic():
            for row in rows:
                item = dict(row)
                oid = str(item.get("offer_id", "") or "")
                if not oid or self._core._raw_get(kc.key_nft_offer(oid)):
                    continue
                payload = self._aux._loads_json_or_none(
                    item.get("payload") or "{}", context="migrate_nft_offer"
                )
                if payload is None or not isinstance(payload, dict):
                    skipped_corrupt += 1
                    continue
                offer = {
                    "offer_id": oid,
                    "token_id": item.get("token_id", ""),
                    "bidder": item.get("bidder", ""),
                    "price": item.get("price", 0),
                    "expires_at": item.get("expires_at", 0),
                    "status": item.get("status", "pending"),
                    "created_at": item.get("created_at", 0),
                    **payload,
                }
                self._core.save_nft_offer(offer)
                migrated += 1
            if skipped_corrupt == 0:
                self._core.set_meta("aux_nft_offers_migrated_v1", True)
        if skipped_corrupt:
            print(
                f"[HybridDatabase] aux_nft_offers migrate deferred: "
                f"{skipped_corrupt} corrupt JSON row(s) (migrated={migrated})"
            )
        elif migrated:
            print(f"[HybridDatabase] migrated {migrated} nft_offers from aux.db to Rocks")

    def _migrate_aux_nft_auctions_once(self) -> None:
        if self._core.get_meta("aux_nft_auctions_migrated_v1"):
            return
        try:
            rows = self._aux.conn.execute("SELECT * FROM nft_auctions ORDER BY created_at").fetchall()
        except Exception as exc:
            print(f"[HybridDatabase] aux_nft_auctions migrate deferred (will retry): {exc}")
            return
        migrated = 0
        skipped_corrupt = 0
        with self._core.atomic():
            for row in rows:
                item = dict(row)
                aid = str(item.get("auction_id", "") or "")
                if not aid or self._core._raw_get(kc.key_nft_auction(aid)):
                    continue
                payload = self._aux._loads_json_or_none(
                    item.get("payload") or "{}", context="migrate_nft_auction"
                )
                if payload is None or not isinstance(payload, dict):
                    skipped_corrupt += 1
                    continue
                auction = {
                    "auction_id": aid,
                    "token_id": item.get("token_id", ""),
                    "seller": item.get("seller", ""),
                    "status": item.get("status", "active"),
                    "ends_at": item.get("ends_at", 0),
                    "created_at": item.get("created_at", 0),
                    **payload,
                }
                self._core.save_nft_auction(auction)
                migrated += 1
            if skipped_corrupt == 0:
                self._core.set_meta("aux_nft_auctions_migrated_v1", True)
        if skipped_corrupt:
            print(
                f"[HybridDatabase] aux_nft_auctions migrate deferred: "
                f"{skipped_corrupt} corrupt JSON row(s) (migrated={migrated})"
            )
        elif migrated:
            print(f"[HybridDatabase] migrated {migrated} nft_auctions from aux.db to Rocks")

    def _migrate_aux_nft_sales_once(self) -> None:
        if self._core.get_meta("aux_nft_sales_migrated_v1"):
            return
        try:
            rows = self._aux.conn.execute("SELECT * FROM nft_sales ORDER BY id").fetchall()
        except Exception as exc:
            print(f"[HybridDatabase] aux_nft_sales migrate deferred (will retry): {exc}")
            return
        migrated = 0
        max_id = 0
        with self._core.atomic():
            for row in rows:
                item = dict(row)
                sale_id = int(item.get("id", 0) or 0)
                created_at = int(item.get("created_at", 0) or 0)
                if sale_id <= 0:
                    continue
                key = kc.key_nft_sale(created_at, sale_id)
                if self._core._raw_get(key):
                    max_id = max(max_id, sale_id)
                    continue
                self._core.save_nft_sale({
                    "id": sale_id,
                    "token_id": item.get("token_id", ""),
                    "from_addr": item.get("from_addr", ""),
                    "to_addr": item.get("to_addr", ""),
                    "price": item.get("price", 0),
                    "sale_type": item.get("sale_type", "buy"),
                    "created_at": created_at,
                })
                max_id = max(max_id, sale_id)
                migrated += 1
            if max_id > 0:
                prev = int(self._core.get_meta("nft_sale_seq", 0) or 0)
                self._core.set_meta("nft_sale_seq", max(max_id, prev))
            self._core.set_meta("aux_nft_sales_migrated_v1", True)
        if migrated:
            print(f"[HybridDatabase] migrated {migrated} nft_sales from aux.db to Rocks")

    def _migrate_aux_bridge_once(self) -> None:
        if self._core.get_meta("aux_bridge_migrated_v1"):
            return
        with self._core.atomic():
            for row in self._aux.get_bridge_locks(limit=1_000_000):
                tx_hash = row.get("tx_hash", "") or ""
                if not tx_hash or self._core._raw_get(kc.key_bridge_lock(tx_hash)):
                    continue
                self._core._raw_put(
                    kc.key_bridge_lock(tx_hash),
                    json.dumps(row, ensure_ascii=False).encode("utf-8"),
                )
            for row in self._aux.conn.execute("SELECT * FROM bridge_credits").fetchall():
                credit = dict(row)
                credit_key = credit.get("credit_key", "") or ""
                if not credit_key or self._core.has_bridge_credit(credit_key):
                    continue
                self._core._raw_put(
                    kc.key_bridge_credit(credit_key),
                    json.dumps(credit, ensure_ascii=False).encode("utf-8"),
                )
            self._core.set_meta("aux_bridge_migrated_v1", True)

    def close(self) -> None:
        self._core.close()
        self._aux.close()

    def backup_to(self, dest_path: str) -> bool:
        return self._core.backup_to(dest_path)

    @contextmanager
    def atomic(self):
        with self._core.atomic():
            yield self

    # ── core delegation ───────────────────────────────────────────────────

    def set_meta(self, key: str, value: Any) -> None:
        self._core.set_meta(key, value)

    def get_meta(self, key: str, default: Any = None) -> Any:
        return self._core.get_meta(key, default)

    def save_block(self, block: Dict) -> bool:
        return self._core.save_block(block)

    def persist_block_atomic(
        self,
        block: Dict,
        transactions: List[Dict],
        burned_amount: float = 0.0,
        burn_address: str = "",
    ) -> bool:
        return self._core.persist_block_atomic(block, transactions, burned_amount, burn_address)

    def _persist_block_locked(
        self,
        block: Dict,
        transactions: List[Dict],
        burned_amount: float = 0.0,
        burn_address: str = "",
    ) -> None:
        self._core._persist_block_locked(block, transactions, burned_amount, burn_address)

    def get_block(self, height: int) -> Optional[Dict]:
        return self._core.get_block(height)

    def get_block_by_hash(self, block_hash: str) -> Optional[Dict]:
        return self._core.get_block_by_hash(block_hash)

    def get_latest_blocks(self, limit: int = 20) -> List[Dict]:
        return self._core.get_latest_blocks(limit)

    def get_chain_tip(self) -> int:
        return self._core.get_chain_tip()

    def get_last_block(self) -> Optional[Dict]:
        return self._core.get_last_block()

    def get_all_accounts(self) -> List[Dict]:
        return self._core.get_all_accounts()

    def compute_state_root(self) -> str:
        return self._core.compute_state_root()

    def get_live_state_root_meta(self) -> tuple[str, int]:
        if hasattr(self._core, "get_live_state_root_meta"):
            return self._core.get_live_state_root_meta()
        return "", -1

    def get_balance(self, address: str) -> float:
        return self._core.get_balance(address)

    def get_balance_satoshi(self, address: str) -> int:
        if hasattr(self._core, "get_balance_satoshi"):
            return int(self._core.get_balance_satoshi(address))
        from runtime.amount import to_satoshi

        return to_satoshi(self._core.get_balance(address))

    def get_nonce(self, address: str) -> int:
        return self._core.get_nonce(address)

    def get_account(self, address: str) -> Optional[Dict]:
        return self._core.get_account(address)

    def update_balance(self, address: str, delta: float) -> float:
        return self._core.update_balance(address, delta)

    def set_balance(self, address: str, balance: int) -> None:
        self._core.set_balance(address, balance)

    def balance_delta(self, address: str, delta: float) -> None:
        self._core.balance_delta(address, delta)

    def balance_delta_satoshi(self, address: str, delta_sat: int) -> None:
        if hasattr(self._core, "balance_delta_satoshi"):
            self._core.balance_delta_satoshi(address, int(delta_sat))
            return
        from runtime.amount import from_satoshi_float

        self._core.balance_delta(address, float(from_satoshi_float(int(delta_sat))))

    def increment_nonce(self, address: str) -> int:
        return self._core.increment_nonce(address)

    def nonce_increment(self, address: str) -> int:
        return self._core.nonce_increment(address)

    def save_account(
        self,
        address: str,
        balance: float = 0.0,
        nonce: int = 0,
        code: str | None = None,
        storage: str | None = None,
    ) -> None:
        self._core.save_account(address, balance, nonce, code, storage)

    def update_account_storage(self, address: str, storage: Dict) -> None:
        self._core.update_account_storage(address, storage)

    def commit_writeback_accounts(self, accounts: Dict[str, Any]) -> int:
        """Delegate store-lock Rocks writeback commit (v1.3.62)."""
        return int(self._core.commit_writeback_accounts(accounts))

    def load_writeback_accounts(self, addresses: List[str]) -> Dict[str, Any]:
        """Delegate Rocks batch account preload for writeback (v1.3.64)."""
        return dict(self._core.load_writeback_accounts(addresses))

    def commit_writeback_bundle(
        self,
        accounts: Dict[str, Any] | None,
        log_batches: List[Dict[str, Any]] | None = None,
        *,
        block_height: int = 0,
        tx_hash: str = "",
        timestamp: int = 0,
    ) -> Dict[str, int]:
        """Delegate unified accounts+logs writeback commit (v1.3.63)."""
        return dict(
            self._core.commit_writeback_bundle(
                accounts,
                log_batches,
                block_height=block_height,
                tx_hash=tx_hash,
                timestamp=timestamp,
            )
        )

    def save_validator(self, address: str, stake: float) -> None:
        self._core.save_validator(address, stake)

    def get_validators(self, active_only: bool = True) -> List[Dict]:
        return self._core.get_validators(active_only)

    def slash_validator(self, address: str) -> None:
        self._core.slash_validator(address)

    def save_transaction(self, tx: Dict) -> bool:
        return self._core.save_transaction(tx)

    def get_transaction(self, tx_hash: str) -> Optional[Dict]:
        return self._core.get_transaction(tx_hash)

    def get_transactions_in_block(self, height: int) -> List[Dict]:
        return self._core.get_transactions_in_block(height)

    def get_recent_transactions(self, limit: int = 30) -> List[Dict]:
        return self._core.get_recent_transactions(limit)

    def get_tx_receipt(self, tx_hash: str) -> Optional[Dict]:
        return self._core.get_tx_receipt(tx_hash)

    def get_receipts_by_block(self, block_height: int) -> List[Dict]:
        return self._core.get_receipts_by_block(block_height)

    def get_transactions_by_address(
        self,
        address: str,
        limit: int = 50,
        offset: int = 0,
        direction: str = "all",
    ) -> List[Dict]:
        return self._core.get_transactions_by_address(address, limit, offset, direction)

    def count_transactions_by_address(self, address: str, direction: str = "all") -> int:
        return self._core.count_transactions_by_address(address, direction)

    def get_address_activity(self, address: str) -> Dict:
        return self._core.get_address_activity(address)

    def get_proposer_audit_log(
        self,
        limit: int = 50,
        offset: int = 0,
        proposer: str = "",
    ) -> List[Dict]:
        return self._core.get_proposer_audit_log(limit, offset, proposer)

    def record_burn(self, block_height: int, burned_amount: float) -> None:
        self._core.record_burn(block_height, burned_amount)

    def get_total_burned(self) -> float:
        return self._core.get_total_burned()

    def get_burn_stats(self) -> Dict:
        return self._core.get_burn_stats()

    def reorg_truncate_above(self, height: int) -> None:
        self._core.reorg_truncate_above(height)

    def truncate_chain_state(self, height: int) -> int:
        return self._core.truncate_chain_state(height)

    def truncate_blocks_above(self, height: int) -> int:
        return self._core.truncate_blocks_above(height)

    def truncate_all_blocks(self) -> int:
        return self._core.truncate_all_blocks()

    def reset_accounts_from_alloc(self, alloc: Dict[str, float], *, _in_atomic: bool = False) -> None:
        self._core.reset_accounts_from_alloc(alloc, _in_atomic=_in_atomic)

    def get_cached_account_count(self) -> int | None:
        if hasattr(self._core, "get_cached_account_count"):
            return self._core.get_cached_account_count()
        return None

    def get_cached_total_supply(self) -> float | None:
        if hasattr(self._core, "get_cached_total_supply"):
            return self._core.get_cached_total_supply()
        return None

    def get_total_supply(self) -> float:
        return self._core.get_total_supply()

    def get_rocks_runtime_stats(self) -> Dict:
        if hasattr(self._core, "get_rocks_runtime_stats"):
            stats = dict(self._core.get_rocks_runtime_stats())
        else:
            stats = dict(self.get_stats())
        aux_fails = int(getattr(self._aux, "_json_decode_failures", 0) or 0)
        stats["aux_json_decode_failures"] = aux_fails
        tuning = dict(stats.get("rocksdb_tuning") or {})
        tuning["aux_json_decode_failures"] = aux_fails
        tuning["sqlite_json_decode_failures"] = aux_fails
        stats["rocksdb_tuning"] = tuning
        return stats

    def get_stats(self) -> Dict:
        stats = self._core.get_stats()
        stats["aux_path"] = os.path.join(self.db_path, "aux.db")
        aux_fails = int(getattr(self._aux, "_json_decode_failures", 0) or 0)
        stats["aux_json_decode_failures"] = aux_fails
        tuning = dict(stats.get("rocksdb_tuning") or {})
        tuning["aux_json_decode_failures"] = aux_fails
        # Surface aux decode failures next to rocks counter for /metrics.
        tuning["sqlite_json_decode_failures"] = aux_fails
        stats["rocksdb_tuning"] = tuning
        return stats

    def record_state_root_mismatch(self, *args: Any, **kwargs: Any) -> None:
        self._core.record_state_root_mismatch(*args, **kwargs)

    def get_state_root_mismatches(self, limit: int = 20) -> List[Dict]:
        if hasattr(self._core, "get_state_root_mismatches"):
            return self._core.get_state_root_mismatches(limit=limit)
        return self._aux.get_state_root_mismatches(limit=limit)

    def record_tx_propagation_event(self, *args: Any, **kwargs: Any) -> None:
        self._core.record_tx_propagation_event(*args, **kwargs)

    def get_tx_propagation_trace(self, tx_hash: str) -> Dict:
        return self._core.get_tx_propagation_trace(tx_hash)

    def get_recent_tx_propagation(self, limit: int = 20) -> List[Dict]:
        return self._core.get_recent_tx_propagation(limit=limit)

    def save_slash_event(self, validator: str, reason: str, epoch: int, penalty: int) -> None:
        self._core.save_slash_event(validator, reason, epoch, penalty)

    def get_slash_events(self, limit: int = 100) -> List[Dict]:
        return self._core.get_slash_events(limit)

    def get_chain_metrics(self, window: int = 32) -> Dict:
        return self._core.get_chain_metrics(window)

    # ── bridge (Rocks core — not aux.db) ─────────────────────────────────

    def save_bridge_lock(
        self,
        from_addr: str,
        to_chain: str,
        to_addr: str,
        amount: float,
        tx_hash: str,
    ) -> None:
        self._core.save_bridge_lock(from_addr, to_chain, to_addr, amount, tx_hash)

    def confirm_bridge_lock(self, tx_hash: str) -> None:
        self._core.confirm_bridge_lock(tx_hash)

    def get_bridge_locks(self, limit: int = 50) -> List[Dict]:
        return self._core.get_bridge_locks(limit)

    @staticmethod
    def bridge_credit_key(from_chain: str, event_tx_hash: str, log_index: int = 0) -> str:
        return RocksChainStore.bridge_credit_key(from_chain, event_tx_hash, log_index)

    def has_bridge_credit(self, credit_key: str) -> bool:
        return self._core.has_bridge_credit(credit_key)

    def save_bridge_credit(
        self,
        event_tx_hash: str,
        recipient: str,
        amount: float,
        from_chain: str,
        log_index: int = 0,
    ) -> str:
        return self._core.save_bridge_credit(
            event_tx_hash, recipient, amount, from_chain, log_index=log_index
        )

    def claim_and_credit_bridge_event(
        self,
        from_chain: str,
        event_tx_hash: str,
        recipient: str,
        amount: float,
        log_index: int = 0,
        abs_tx_hash: str = "",
    ) -> Dict:
        return self._core.claim_and_credit_bridge_event(
            from_chain,
            event_tx_hash,
            recipient,
            amount,
            log_index=log_index,
            abs_tx_hash=abs_tx_hash,
        )

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
        return self._core.debit_and_create_bridge_lock(
            from_addr,
            amount,
            burn_address,
            burn_amount,
            to_chain,
            to_addr,
            net_amount,
            tx_hash,
        )

    def refund_pending_bridge_lock(self, tx_hash: str) -> Dict:
        return self._core.refund_pending_bridge_lock(tx_hash)

    def save_evm_logs(
        self,
        contract_address: str,
        logs: List[Dict],
        block_height: int = 0,
        tx_hash: str = "",
        timestamp: int = 0,
    ) -> int:
        return self._core.save_evm_logs(
            contract_address, logs, block_height=block_height, tx_hash=tx_hash, timestamp=timestamp
        )

    def get_evm_logs(self, contract_address: str = "", limit: int = 100) -> List[Dict]:
        return self._core.get_evm_logs(contract_address=contract_address, limit=limit)

    def get_evm_logs_by_tx(self, tx_hash: str) -> List[Dict]:
        return self._core.get_evm_logs_by_tx(tx_hash)

    def query_evm_logs(
        self,
        from_block: int = 0,
        to_block: Optional[int] = None,
        addresses: Optional[List[str]] = None,
        topics: Optional[List] = None,
        limit: int = 10_000,
    ) -> List[Dict]:
        return self._core.query_evm_logs(
            from_block=from_block,
            to_block=to_block,
            addresses=addresses,
            topics=topics,
            limit=limit,
        )

    def save_nft_token(self, token: Dict) -> None:
        self._core.save_nft_token(token)

    def get_nft_tokens(self) -> List[Dict]:
        return self._core.get_nft_tokens()

    def save_nft_offer(self, offer: Dict) -> None:
        self._core.save_nft_offer(offer)

    def get_nft_offers(self) -> List[Dict]:
        return self._core.get_nft_offers()

    def save_nft_auction(self, auction: Dict) -> None:
        self._core.save_nft_auction(auction)

    def get_nft_auctions(self) -> List[Dict]:
        return self._core.get_nft_auctions()

    def save_nft_sale(self, sale: Dict) -> None:
        self._core.save_nft_sale(sale)

    def get_nft_sales(self, limit: int = 100) -> List[Dict]:
        return self._core.get_nft_sales(limit=limit)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._aux, name)
