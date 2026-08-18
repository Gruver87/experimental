#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Absolute Blockchain — единый слой хранения данных.
Один SQLite-файл, WAL-режим, все таблицы.
"""

import sqlite3
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

from runtime.amount import money_abs, parse_finite_number

logger = logging.getLogger("Database")


def observed_optional_int(row: Optional[Dict[str, Any]], *keys: str) -> Optional[int]:
    """First present integer field. Missing is None — never default 21000."""
    if not isinstance(row, dict):
        return None
    for key in keys:
        if key not in row:
            continue
        raw = row.get(key)
        if raw is None or raw == "":
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    return None


class Database:
    """
    Центральная база данных узла.
    Один экземпляр на весь процесс — используется через self.db во всех модулях.
    """

    engine = "sqlite"

    def __init__(self, db_path: str = "data/blockchain.db", synchronous: str = "NORMAL"):
        self.db_path = db_path
        self.synchronous = (synchronous or "NORMAL").upper()
        self.lock = threading.RLock()
        self._json_decode_failures = 0
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # доступ к полям по имени
        self._configure()

    def _loads_json_or_none(self, raw: Any, *, context: str = "") -> Optional[Any]:
        """Fail-closed JSON decode; bumps counter instead of inventing defaults."""
        if raw is None:
            return None
        try:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8")
            return json.loads(raw)
        except Exception as exc:
            self._json_decode_failures += 1
            logger.warning(
                "[DB] corrupt %s JSON (decode_failures=%s): %s",
                context or "row",
                self._json_decode_failures,
                exc,
            )
            return None

    def _loads_json(self, raw: Any, *, context: str, default: Any) -> Any:
        """Decode JSON; on failure bump counter and return default."""
        parsed = self._loads_json_or_none(raw, context=context)
        return default if parsed is None else parsed

    # ── Инициализация ────────────────────────────────────────────────────────

    def _configure(self):
        """Настройка SQLite, создание таблиц и миграция старой схемы."""
        self.conn.execute("PRAGMA journal_mode=WAL")
        sync = self.synchronous if self.synchronous in ("OFF", "NORMAL", "FULL", "EXTRA") else "NORMAL"
        self.conn.execute(f"PRAGMA synchronous={sync}")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Добавляет недостающие колонки и переименовывает block_hash -> hash."""
        import json as _json

        # Читаем текущие колонки таблицы blocks
        cols_info = self.conn.execute("PRAGMA table_info(blocks)").fetchall()
        block_cols = {row[1] for row in cols_info}

        # ── 1. Переименование block_hash -> hash (старая схема) ──────────────
        if "block_hash" in block_cols and "hash" not in block_cols:
            # SQLite 3.25+ поддерживает RENAME COLUMN
            try:
                self.conn.execute("ALTER TABLE blocks RENAME COLUMN block_hash TO hash")
                block_cols.discard("block_hash")
                block_cols.add("hash")
                print("[DB] Migration: renamed 'block_hash' -> 'hash'")
            except Exception:
                # Fallback: добавляем колонку hash и копируем значения
                self.conn.execute("ALTER TABLE blocks ADD COLUMN hash TEXT DEFAULT ''")
                self.conn.execute("UPDATE blocks SET hash = block_hash")
                block_cols.add("hash")
                print("[DB] Migration: added 'hash' column (copied from block_hash)")

        # ── 2. Добавляем недостающие колонки ─────────────────────────────────
        add_cols = [
            ("blocks", "data",         "TEXT DEFAULT '{}'"),
            ("blocks", "tx_count",     "INTEGER DEFAULT 0"),
            ("blocks", "gas_used",     "INTEGER DEFAULT 0"),
            ("blocks", "total_burned", "REAL DEFAULT 0.0"),
            ("blocks", "extra_data",   "TEXT DEFAULT ''"),
            ("transactions", "burned",   "REAL NOT NULL DEFAULT 0.0"),
            ("transactions", "fee",      "REAL NOT NULL DEFAULT 0.0"),
            ("transactions", "gas_used", "INTEGER NOT NULL DEFAULT 21000"),
            ("accounts", "code",    "TEXT DEFAULT ''"),
            ("accounts", "storage", "TEXT DEFAULT ''"),
            ("accounts", "balance_satoshi", "INTEGER"),
            ("plasma_blocks", "merkle_root", "TEXT NOT NULL DEFAULT ''"),
            ("plasma_blocks", "tx_root",     "TEXT NOT NULL DEFAULT ''"),
        ]
        existing: dict = {"blocks": block_cols}
        for table, col, col_def in add_cols:
            if table not in existing:
                c = self.conn.execute(f"PRAGMA table_info({table})")
                existing[table] = {row[1] for row in c.fetchall()}
            if col not in existing[table]:
                try:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
                    print(f"[DB] Migration: added '{table}.{col}'")
                    existing[table].add(col)
                except Exception as e:
                    print(f"[DB] Migration warning ({table}.{col}): {e}")

        # ── 3. Заполняем data для старых блоков ──────────────────────────────
        try:
            count = self.conn.execute(
                "SELECT COUNT(*) FROM blocks WHERE data='{}' OR data IS NULL OR data=''"
            ).fetchone()[0]
            if count > 0:
                rows = self.conn.execute(
                    "SELECT height, hash, parent_hash, timestamp, miner "
                    "FROM blocks WHERE data='{}' OR data IS NULL OR data=''"
                ).fetchall()
                for row in rows:
                    block_dict = {
                        "height": row[0], "hash": row[1] or "",
                        "parent_hash": row[2] or "", "timestamp": row[3] or 0,
                        "miner": row[4] or "genesis",
                        "tx_count": 0, "gas_used": 0,
                        "total_burned": 0.0, "extra_data": "legacy",
                        "transactions": [],
                    }
                    self.conn.execute(
                        "UPDATE blocks SET data=? WHERE height=?",
                        (_json.dumps(block_dict), row[0])
                    )
                print(f"[DB] Migration: backfilled 'data' for {count} old block(s)")
        except Exception as e:
            print(f"[DB] Migration backfill warning: {e}")

        self._backfill_tx_receipts_v48()
        self._backfill_proposer_audit_v49()
        self._backfill_balance_satoshi_v80()

    def _backfill_balance_satoshi_v80(self) -> None:
        """Populate balance_satoshi from float balance where NULL (idempotent)."""
        try:
            from runtime.amount import to_satoshi

            cols = {row[1] for row in self.conn.execute("PRAGMA table_info(accounts)").fetchall()}
            if "balance_satoshi" not in cols:
                return
            rows = self.conn.execute(
                "SELECT address, balance FROM accounts WHERE balance_satoshi IS NULL"
            ).fetchall()
            for r in rows:
                sat = to_satoshi(r["balance"] or 0)
                self.conn.execute(
                    "UPDATE accounts SET balance_satoshi=? WHERE address=?",
                    (sat, r["address"]),
                )
            if rows:
                print(f"[DB] v1.2.80: backfilled balance_satoshi for {len(rows)} account(s)")
                self.conn.commit()
        except Exception as e:
            print(f"[DB] balance_satoshi backfill warning: {e}")

    def _backfill_proposer_audit_v49(self) -> None:
        """Build proposer audit rows from historical blocks (Wave 49, idempotent)."""
        try:
            missing = self.conn.execute(
                """SELECT height, hash, miner, tx_count, total_burned, timestamp
                   FROM blocks
                   WHERE height NOT IN (SELECT height FROM block_proposer_audit)"""
            ).fetchall()
            for r in missing:
                self._insert_proposer_audit({
                    "height": r["height"],
                    "hash": r["hash"],
                    "miner": r["miner"],
                    "tx_count": r["tx_count"],
                    "total_burned": r["total_burned"],
                    "timestamp": r["timestamp"],
                })
            if missing:
                print(f"[DB] Wave 49: backfilled {len(missing)} proposer audit row(s)")
        except Exception as e:
            print(f"[DB] proposer audit backfill warning: {e}")

    def _backfill_tx_receipts_v48(self) -> None:
        """Build tx_receipts for transactions missing receipts (Wave 48, idempotent)."""
        try:
            missing = self.conn.execute(
                """SELECT t.*, b.hash AS block_hash
                   FROM transactions t
                   LEFT JOIN blocks b ON b.height = t.block_height
                   WHERE t.hash NOT IN (SELECT tx_hash FROM tx_receipts)"""
            ).fetchall()
            for r in missing:
                d = dict(r)
                self._insert_tx_receipt(
                    d,
                    d.get("block_hash") or "",
                    int(d.get("block_height") or 0),
                )
            if missing:
                print(f"[DB] Wave 48: backfilled {len(missing)} tx receipt(s)")
        except Exception as e:
            print(f"[DB] tx_receipts backfill warning: {e}")

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS blocks (
                height       INTEGER PRIMARY KEY,
                hash         TEXT    UNIQUE NOT NULL,
                parent_hash  TEXT    NOT NULL,
                timestamp    INTEGER NOT NULL,
                miner        TEXT    NOT NULL,
                tx_count     INTEGER DEFAULT 0,
                gas_used     INTEGER DEFAULT 0,
                total_burned REAL    DEFAULT 0.0,
                extra_data   TEXT    DEFAULT '',
                data         TEXT    NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS transactions (
                hash         TEXT    PRIMARY KEY,
                block_height INTEGER NOT NULL,
                from_addr    TEXT    NOT NULL,
                to_addr      TEXT    NOT NULL,
                value        REAL    NOT NULL DEFAULT 0.0,
                gas          INTEGER NOT NULL DEFAULT 21000,
                gas_used     INTEGER NOT NULL DEFAULT 21000,
                fee          REAL    NOT NULL DEFAULT 0.0,
                burned       REAL    NOT NULL DEFAULT 0.0,
                nonce        INTEGER NOT NULL DEFAULT 0,
                tx_data      TEXT    DEFAULT '',
                status       INTEGER DEFAULT 0,
                timestamp    INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS accounts (
                address  TEXT    PRIMARY KEY,
                balance  REAL    NOT NULL DEFAULT 0.0,
                nonce    INTEGER NOT NULL DEFAULT 0,
                code     TEXT    DEFAULT NULL,
                storage  TEXT    DEFAULT NULL
            );

            CREATE TABLE IF NOT EXISTS validators (
                address  TEXT    PRIMARY KEY,
                stake    REAL    NOT NULL DEFAULT 0.0,
                active   INTEGER DEFAULT 1,
                slashed  INTEGER DEFAULT 0,
                joined_at INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS checkpoints (
                epoch      INTEGER PRIMARY KEY,
                block_hash TEXT    NOT NULL,
                justified  INTEGER DEFAULT 0,
                finalized  INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS burn_stats (
                block_height  INTEGER PRIMARY KEY,
                burned_amount REAL    NOT NULL DEFAULT 0.0,
                total_burned  REAL    NOT NULL DEFAULT 0.0
            );

            CREATE TABLE IF NOT EXISTS bridge_locks (
                tx_hash    TEXT    PRIMARY KEY,
                from_addr  TEXT    NOT NULL,
                to_chain   TEXT    NOT NULL,
                to_addr    TEXT    NOT NULL,
                amount     REAL    NOT NULL,
                status     TEXT    DEFAULT 'pending',
                created_at INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS bridge_credits (
                credit_key  TEXT PRIMARY KEY,
                l1_tx_hash  TEXT NOT NULL,
                recipient   TEXT NOT NULL,
                amount      REAL NOT NULL,
                from_chain  TEXT NOT NULL,
                credited_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS minivm_contracts (
                address     TEXT PRIMARY KEY,
                bytecode    TEXT NOT NULL,
                storage     TEXT NOT NULL DEFAULT '{}',
                deployed_at INTEGER NOT NULL DEFAULT 0,
                calls       INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS slash_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                validator  TEXT NOT NULL,
                reason     TEXT NOT NULL,
                epoch      INTEGER NOT NULL DEFAULT 0,
                penalty    INTEGER NOT NULL DEFAULT 0,
                timestamp  INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS evm_logs (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                contract_address TEXT NOT NULL,
                block_height     INTEGER NOT NULL DEFAULT 0,
                tx_hash          TEXT NOT NULL DEFAULT '',
                log_index        INTEGER NOT NULL DEFAULT 0,
                topics           TEXT NOT NULL DEFAULT '[]',
                data             TEXT NOT NULL DEFAULT '',
                timestamp        INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_evm_logs_contract ON evm_logs(contract_address);
            CREATE INDEX IF NOT EXISTS idx_evm_logs_block ON evm_logs(block_height);
            CREATE INDEX IF NOT EXISTS idx_evm_logs_tx ON evm_logs(tx_hash);

            CREATE TABLE IF NOT EXISTS oracle_feeds (
                feed_id       TEXT PRIMARY KEY,
                symbol        TEXT NOT NULL,
                value         REAL NOT NULL,
                source        TEXT NOT NULL DEFAULT '',
                reporter      TEXT NOT NULL DEFAULT '',
                signature     TEXT NOT NULL DEFAULT '',
                payload       TEXT NOT NULL DEFAULT '{}',
                block_height  INTEGER NOT NULL DEFAULT 0,
                submitted_at  INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_oracle_feeds_symbol ON oracle_feeds(symbol);
            CREATE INDEX IF NOT EXISTS idx_oracle_feeds_ts ON oracle_feeds(submitted_at);

            CREATE TABLE IF NOT EXISTS oracle_reports (
                report_id   TEXT PRIMARY KEY,
                symbol      TEXT NOT NULL,
                reporter    TEXT NOT NULL,
                value       REAL NOT NULL,
                signature   TEXT NOT NULL DEFAULT '',
                payload     TEXT NOT NULL DEFAULT '{}',
                submitted_at INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_oracle_reports_symbol ON oracle_reports(symbol);

            CREATE TABLE IF NOT EXISTS lightning_channels (
                channel_id   TEXT PRIMARY KEY,
                node1        TEXT NOT NULL,
                node2        TEXT NOT NULL,
                capacity     REAL NOT NULL,
                balance1     REAL NOT NULL,
                balance2     REAL NOT NULL,
                status       TEXT NOT NULL DEFAULT 'open',
                fee_rate     REAL NOT NULL DEFAULT 0.00001,
                created_at   INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS lightning_payments (
                payment_id   TEXT PRIMARY KEY,
                channel_id   TEXT NOT NULL,
                from_node    TEXT NOT NULL,
                to_node      TEXT NOT NULL,
                amount       REAL NOT NULL,
                fee          REAL NOT NULL DEFAULT 0,
                status       TEXT NOT NULL DEFAULT 'completed',
                payment_hash TEXT NOT NULL DEFAULT '',
                timestamp    INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_ln_payments_channel ON lightning_payments(channel_id);

            CREATE TABLE IF NOT EXISTS lightning_htlcs (
                htlc_id       TEXT PRIMARY KEY,
                channel_id    TEXT NOT NULL,
                payment_hash  TEXT NOT NULL,
                amount        REAL NOT NULL,
                expiry        INTEGER NOT NULL,
                sender        TEXT NOT NULL,
                receiver      TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'pending',
                preimage      TEXT NOT NULL DEFAULT '',
                created_at    INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_ln_htlcs_channel ON lightning_htlcs(channel_id);

            CREATE TABLE IF NOT EXISTS lightning_channel_states (
                channel_id    TEXT NOT NULL,
                version       INTEGER NOT NULL,
                balance1      REAL NOT NULL,
                balance2      REAL NOT NULL,
                state_hash    TEXT NOT NULL,
                sig_node1     TEXT NOT NULL DEFAULT '',
                sig_node2     TEXT NOT NULL DEFAULT '',
                updated_at    INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (channel_id, version)
            );

            CREATE TABLE IF NOT EXISTS plasma_deposits (
                deposit_id    TEXT PRIMARY KEY,
                from_addr     TEXT NOT NULL,
                amount        REAL NOT NULL,
                main_tx_hash  TEXT NOT NULL DEFAULT '',
                created_at    INTEGER NOT NULL DEFAULT 0,
                status        TEXT NOT NULL DEFAULT 'confirmed'
            );

            CREATE TABLE IF NOT EXISTS plasma_blocks (
                block_id      INTEGER PRIMARY KEY,
                block_hash    TEXT NOT NULL,
                parent_hash   TEXT NOT NULL,
                transactions  TEXT NOT NULL DEFAULT '[]',
                total_amount  REAL NOT NULL DEFAULT 0,
                tx_count      INTEGER NOT NULL DEFAULT 0,
                created_at    INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS plasma_exits (
                exit_id     TEXT PRIMARY KEY,
                deposit_id  TEXT NOT NULL,
                user_addr   TEXT NOT NULL,
                amount      REAL NOT NULL,
                created_at  INTEGER NOT NULL DEFAULT 0,
                status      TEXT NOT NULL DEFAULT 'pending'
            );

            CREATE TABLE IF NOT EXISTS crypto_wills (
                will_id         TEXT PRIMARY KEY,
                owner           TEXT NOT NULL,
                heir            TEXT NOT NULL,
                amount          REAL NOT NULL,
                assets          TEXT NOT NULL DEFAULT '{}',
                execution_time  INTEGER NOT NULL DEFAULT 0,
                created_at      INTEGER NOT NULL DEFAULT 0,
                status          TEXT NOT NULL DEFAULT 'pending',
                witnesses       TEXT NOT NULL DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_crypto_wills_owner ON crypto_wills(owner);
            CREATE INDEX IF NOT EXISTS idx_crypto_wills_status ON crypto_wills(status);

            CREATE TABLE IF NOT EXISTS wasm_contracts (
                address     TEXT PRIMARY KEY,
                code        TEXT NOT NULL,
                owner       TEXT NOT NULL,
                name        TEXT NOT NULL DEFAULT '',
                created_at  INTEGER NOT NULL DEFAULT 0,
                call_count  INTEGER NOT NULL DEFAULT 0,
                storage_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS wasm_events (
                event_id      TEXT PRIMARY KEY,
                contract_addr TEXT NOT NULL DEFAULT '',
                event_type    TEXT NOT NULL DEFAULT '',
                payload       TEXT NOT NULL DEFAULT '{}',
                timestamp     INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_wasm_events_ts ON wasm_events(timestamp);

            CREATE TABLE IF NOT EXISTS ai_agents (
                agent_id          TEXT PRIMARY KEY,
                name              TEXT NOT NULL,
                owner             TEXT NOT NULL,
                agent_type        TEXT NOT NULL DEFAULT 'transformer',
                status            TEXT NOT NULL DEFAULT 'active',
                created_at        INTEGER NOT NULL DEFAULT 0,
                last_action       INTEGER NOT NULL DEFAULT 0,
                performance_score REAL NOT NULL DEFAULT 0,
                total_profit      REAL NOT NULL DEFAULT 0,
                actions_count     INTEGER NOT NULL DEFAULT 0,
                strategy_json     TEXT NOT NULL DEFAULT '{}',
                memory_json       TEXT NOT NULL DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_ai_agents_owner ON ai_agents(owner);

            CREATE TABLE IF NOT EXISTS mev_simulations (
                sim_id     TEXT PRIMARY KEY,
                sim_type   TEXT NOT NULL,
                profit     REAL NOT NULL DEFAULT 0,
                payload    TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_mev_sim_ts ON mev_simulations(created_at);

            CREATE TABLE IF NOT EXISTS reorg_assessments (
                assess_id  TEXT PRIMARY KEY,
                kind       TEXT NOT NULL,
                payload    TEXT NOT NULL DEFAULT '{}',
                created_at INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_reorg_assess_ts ON reorg_assessments(created_at);

            CREATE TABLE IF NOT EXISTS nft_tokens (
                token_id    TEXT PRIMARY KEY,
                name        TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                image_url   TEXT NOT NULL DEFAULT '',
                owner       TEXT NOT NULL DEFAULT '',
                creator     TEXT NOT NULL DEFAULT '',
                price       REAL NOT NULL DEFAULT 0,
                for_sale    INTEGER NOT NULL DEFAULT 0,
                created_at  INTEGER NOT NULL DEFAULT 0,
                metadata    TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_nft_owner ON nft_tokens(owner);

            CREATE TABLE IF NOT EXISTS nft_offers (
                offer_id    TEXT PRIMARY KEY,
                token_id    TEXT NOT NULL,
                bidder      TEXT NOT NULL DEFAULT '',
                price       REAL NOT NULL DEFAULT 0,
                expires_at  INTEGER NOT NULL DEFAULT 0,
                status      TEXT NOT NULL DEFAULT 'pending',
                created_at  INTEGER NOT NULL DEFAULT 0,
                payload     TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_nft_offer_token ON nft_offers(token_id);

            CREATE TABLE IF NOT EXISTS nft_auctions (
                auction_id  TEXT PRIMARY KEY,
                token_id    TEXT NOT NULL,
                seller      TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'active',
                ends_at     INTEGER NOT NULL DEFAULT 0,
                payload     TEXT NOT NULL DEFAULT '{}',
                created_at  INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS nft_sales (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                token_id    TEXT NOT NULL,
                from_addr   TEXT NOT NULL DEFAULT '',
                to_addr     TEXT NOT NULL DEFAULT '',
                price       REAL NOT NULL DEFAULT 0,
                sale_type   TEXT NOT NULL DEFAULT 'buy',
                created_at  INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_nft_sales_ts ON nft_sales(created_at);

            CREATE TABLE IF NOT EXISTS tx_receipts (
                tx_hash       TEXT PRIMARY KEY,
                block_height  INTEGER NOT NULL,
                block_hash    TEXT NOT NULL DEFAULT '',
                from_addr     TEXT NOT NULL DEFAULT '',
                to_addr       TEXT NOT NULL DEFAULT '',
                value         REAL NOT NULL DEFAULT 0,
                fee           REAL NOT NULL DEFAULT 0,
                burned        REAL NOT NULL DEFAULT 0,
                gas_used      INTEGER NOT NULL DEFAULT 0,
                status        INTEGER NOT NULL DEFAULT 0,
                created_at    INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_tx_receipt_block ON tx_receipts(block_height);

            CREATE TABLE IF NOT EXISTS block_proposer_audit (
                height        INTEGER PRIMARY KEY,
                block_hash    TEXT NOT NULL DEFAULT '',
                proposer      TEXT NOT NULL DEFAULT '',
                tx_count      INTEGER NOT NULL DEFAULT 0,
                total_burned  REAL NOT NULL DEFAULT 0.0,
                block_ts      INTEGER NOT NULL DEFAULT 0,
                recorded_at   INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_proposer_audit_addr ON block_proposer_audit(proposer);
            CREATE INDEX IF NOT EXISTS idx_proposer_audit_ts ON block_proposer_audit(block_ts);

            CREATE TABLE IF NOT EXISTS state_root_mismatches (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                height        INTEGER NOT NULL,
                expected_root TEXT NOT NULL DEFAULT '',
                computed_root TEXT NOT NULL DEFAULT '',
                source        TEXT NOT NULL DEFAULT 'p2p',
                proposer      TEXT NOT NULL DEFAULT '',
                created_at    INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_state_root_mm_height ON state_root_mismatches(height);

            CREATE TABLE IF NOT EXISTS tx_propagation_events (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                tx_hash       TEXT NOT NULL,
                stage         TEXT NOT NULL,
                node_id       TEXT NOT NULL DEFAULT '',
                peer_id       TEXT NOT NULL DEFAULT '',
                block_height  INTEGER NOT NULL DEFAULT 0,
                detail        TEXT NOT NULL DEFAULT '{}',
                created_at    INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_tx_prop_stage ON tx_propagation_events(tx_hash);
            CREATE INDEX IF NOT EXISTS idx_tx_prop_ts ON tx_propagation_events(created_at);

            CREATE INDEX IF NOT EXISTS idx_tx_block ON transactions(block_height);
            CREATE INDEX IF NOT EXISTS idx_tx_from  ON transactions(from_addr);
            CREATE INDEX IF NOT EXISTS idx_tx_to    ON transactions(to_addr);
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_blocks_ts ON blocks(timestamp);
        """)

    def initialize(self):
        """Публичный метод инициализации (вызывается из NodeOrchestrator)."""
        self._configure()

    # ── Блоки ────────────────────────────────────────────────────────────────

    def save_block(self, block: Dict) -> bool:
        with self.lock:
            try:
                self._insert_block(block)
                self.conn.commit()
                return True
            except Exception as e:
                self.conn.rollback()
                print(f"[DB] save_block error: {e}")
                return False

    def _insert_block(self, block: Dict) -> None:
        from runtime.amount import money_abs

        burned = money_abs(block.get("total_burned", 0.0), field="total_burned")
        stored = dict(block)
        stored["total_burned"] = burned
        self.conn.execute(
            """INSERT OR REPLACE INTO blocks
               (height, hash, parent_hash, timestamp, miner,
                tx_count, gas_used, total_burned, extra_data, data)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                block.get("height", block.get("number", 0)),
                block.get("hash", block.get("block_hash", "")),
                block.get("parent_hash", "0" * 64),
                block.get("timestamp", int(time.time())),
                block.get("miner", ""),
                block.get("tx_count", len(block.get("transactions", []))),
                block.get("gas_used", 0),
                burned,
                block.get("extra_data", ""),
                json.dumps(stored),
            ),
        )
        self._insert_proposer_audit(stored)

    def _insert_proposer_audit(self, block: Dict) -> None:
        from runtime.amount import money_abs

        height = int(block.get("height", block.get("number", 0)) or 0)
        block_hash = block.get("hash", block.get("block_hash", "")) or ""
        proposer = self._normalize_address(
            block.get("miner", block.get("proposer", "genesis")) or "genesis"
        )
        self.conn.execute(
            """INSERT OR REPLACE INTO block_proposer_audit
               (height, block_hash, proposer, tx_count, total_burned, block_ts, recorded_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                height,
                block_hash,
                proposer,
                int(block.get("tx_count", len(block.get("transactions", []))) or 0),
                money_abs(block.get("total_burned", 0.0), field="total_burned"),
                int(block.get("timestamp", int(time.time())) or 0),
                int(time.time()),
            ),
        )

    def persist_block_atomic(
        self,
        block: Dict,
        transactions: List[Dict],
        burned_amount: float = 0.0,
        burn_address: str = "",
    ) -> bool:
        """Атомарно сохраняет блок, транзакции и статистику сжигания."""
        with self.lock:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                self._persist_block_locked(block, transactions, burned_amount, burn_address)
                self.conn.commit()
                return True
            except Exception as e:
                self.conn.rollback()
                print(f"[DB] persist_block_atomic error: {e}")
                return False

    def _persist_block_locked(
        self,
        block: Dict,
        transactions: List[Dict],
        burned_amount: float = 0.0,
        burn_address: str = "",
    ) -> None:
        """Persist block + txs inside an open transaction (caller holds BEGIN)."""
        self._insert_block(block)
        block_hash = block.get("hash", block.get("block_hash", ""))
        block_height = int(block.get("height", block.get("number", 0)) or 0)
        for tx in transactions:
            self._insert_transaction(tx)
            self._insert_tx_receipt(tx, block_hash, block_height)
            tx_hash = tx.get("hash", tx.get("tx_hash", ""))
            if tx_hash:
                proposer = self._normalize_address(
                    block.get("miner", block.get("proposer", ""))
                )
                self.record_tx_propagation_event(
                    tx_hash,
                    "block_included",
                    block_height=block_height,
                    detail={"proposer": proposer, "block_hash": block_hash},
                    _no_commit=True,
                )
                self.record_tx_propagation_event(
                    tx_hash,
                    "block_confirmed",
                    block_height=block_height,
                    detail={"receipt": True},
                    _no_commit=True,
                )
        if burned_amount > 0:
            self._insert_burn_record(block.get("height", 0), burned_amount)
            if burn_address:
                self._apply_balance_delta(burn_address, burned_amount)

    @contextmanager
    def atomic(self):
        """Single-writer SQLite transaction for block execution."""
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def balance_delta(self, address: str, delta: float) -> None:
        """Balance change without commit (inside atomic()). ABS float edge → satoshi."""
        self._apply_balance_delta(address, delta)

    def balance_delta_satoshi(self, address: str, delta_sat: int) -> None:
        """Integer satoshi balance change without commit (Wave C apply path)."""
        from runtime.amount import apply_satoshi_delta, from_satoshi_float

        row = self.conn.execute(
            "SELECT balance, balance_satoshi FROM accounts WHERE address=?",
            (address,),
        ).fetchone()
        if row and row["balance_satoshi"] is not None:
            cur_sat = int(row["balance_satoshi"])
        elif row:
            from runtime.amount import to_satoshi

            cur_sat = to_satoshi(row["balance"] or 0)
        else:
            cur_sat = 0
        new_sat = apply_satoshi_delta(cur_sat, int(delta_sat))
        new_abs = from_satoshi_float(new_sat)
        self.conn.execute(
            """INSERT INTO accounts (address, balance, balance_satoshi, nonce)
               VALUES (?, ?, ?, 0)
               ON CONFLICT(address) DO UPDATE
               SET balance=excluded.balance, balance_satoshi=excluded.balance_satoshi""",
            (address, new_abs, new_sat),
        )

    def nonce_increment(self, address: str) -> int:
        """Nonce bump without commit (inside atomic())."""
        self.conn.execute(
            """INSERT INTO accounts (address, balance, balance_satoshi, nonce) VALUES (?,0,0,1)
               ON CONFLICT(address) DO UPDATE SET nonce=nonce+1""",
            (address,),
        )
        row = self.conn.execute(
            "SELECT nonce FROM accounts WHERE address=?", (address,)
        ).fetchone()
        return int(row["nonce"]) if row else 1

    def get_all_accounts(self) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT address, balance, balance_satoshi, nonce, code, storage "
                "FROM accounts ORDER BY address"
            ).fetchall()
            return [dict(r) for r in rows]

    def compute_state_root(self) -> str:
        from execution.state_root import compute_db_state_root

        return compute_db_state_root(self.get_all_accounts())

    def get_block(self, height: int) -> Optional[Dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT data FROM blocks WHERE height=?", (height,)
            ).fetchone()
            if not row:
                return None
            return self._loads_json_or_none(row["data"], context=f"block:{height}")

    def get_block_by_hash(self, block_hash: str) -> Optional[Dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT data FROM blocks WHERE hash=?", (block_hash,)
            ).fetchone()
            if not row:
                return None
            return self._loads_json_or_none(row["data"], context=f"block_hash:{block_hash}")

    def get_latest_blocks(self, limit: int = 20) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT data FROM blocks ORDER BY height DESC LIMIT ?", (limit,)
            ).fetchall()
            out: List[Dict] = []
            for r in rows:
                parsed = self._loads_json_or_none(r["data"], context="latest_block")
                if parsed is not None:
                    out.append(parsed)
            return out

    def get_chain_tip(self) -> int:
        """Возвращает высоту последнего блока (0 если цепь пуста)."""
        with self.lock:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(height),0) as h FROM blocks"
            ).fetchone()
            return row["h"] if row else 0

    def get_last_block(self) -> Optional[Dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT data FROM blocks ORDER BY height DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            return self._loads_json_or_none(row["data"], context="last_block")

    def reorg_truncate_above(self, height: int) -> None:
        """Remove chain rows above height. Caller must hold atomic()."""
        cut = int(height)
        self.conn.execute(
            "DELETE FROM transactions WHERE block_height > ?", (cut,)
        )
        self.conn.execute(
            "DELETE FROM tx_receipts WHERE block_height > ?", (cut,)
        )
        self.conn.execute(
            "DELETE FROM block_proposer_audit WHERE height > ?", (cut,)
        )
        self.conn.execute(
            "DELETE FROM state_root_mismatches WHERE height > ?", (cut,)
        )
        self.conn.execute(
            "DELETE FROM burn_stats WHERE block_height > ?", (cut,)
        )
        self.conn.execute(
            "DELETE FROM evm_logs WHERE block_height > ?", (cut,)
        )
        self.conn.execute(
            "DELETE FROM tx_propagation_events WHERE block_height > ?", (cut,)
        )
        self.conn.execute("DELETE FROM blocks WHERE height > ?", (cut,))

    def truncate_chain_state(self, height: int) -> int:
        """Remove blocks, txs, and burn stats above height."""
        with self.atomic():
            before = self.get_chain_tip()
            self.reorg_truncate_above(int(height))
            return max(0, before - int(height))

    def reset_accounts_from_alloc(
        self, alloc: Dict[str, float], *, _in_atomic: bool = False
    ) -> None:
        """Reset all account balances/nonces from genesis allocation map."""
        if _in_atomic:
            self._reset_accounts_from_alloc_locked(alloc)
            return
        with self.atomic():
            self._reset_accounts_from_alloc_locked(alloc)

    def _reset_accounts_from_alloc_locked(self, alloc: Dict[str, float]) -> None:
        from runtime.amount import dual_write_balance

        self.conn.execute("DELETE FROM accounts")
        for addr, amount in alloc.items():
            if isinstance(amount, bool):
                raise TypeError("bool is not an amount")
            payload: dict = {}
            dual_write_balance(payload, amount)
            self.conn.execute(
                "INSERT INTO accounts (address, balance, balance_satoshi, nonce) VALUES (?, ?, ?, 0)",
                (addr, payload["balance"], payload["balance_satoshi"]),
            )

    def truncate_blocks_above(self, height: int) -> int:
        """Full chain truncate above tip (parity with Rocks / P2P fork resync)."""
        return self.truncate_chain_state(height)
    def truncate_all_blocks(self) -> int:
        """Remove entire chain (used when joining peer with different genesis)."""
        with self.atomic():
            cur = self.conn.execute("DELETE FROM blocks")
            return cur.rowcount

    # ── Транзакции ───────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_tx_status(status: Any) -> int:
        """Map receipt/tx status to 0|1. Missing/unknown → 0 (fail-closed)."""
        if status is None:
            return 0
        if isinstance(status, bool):
            return 1 if status else 0
        if isinstance(status, (int, float)):
            return 1 if int(status) != 0 else 0
        s = str(status).strip().lower()
        if not s:
            return 0
        if s in ("1", "true", "ok", "success", "confirmed", "mined"):
            return 1
        if s in ("0", "false", "failed", "reverted", "pending"):
            return 0
        try:
            return 1 if int(s) != 0 else 0
        except ValueError:
            return 0

    def _insert_transaction(self, tx: Dict) -> None:
        from runtime.amount import tx_money_abs

        money = tx_money_abs(tx)
        self.conn.execute(
            """INSERT OR REPLACE INTO transactions
               (hash, block_height, from_addr, to_addr, value,
                gas, gas_used, fee, burned, nonce, tx_data, status, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                tx.get("hash", tx.get("tx_hash", "")),
                tx.get("block_height", 0),
                self._normalize_address(tx.get("from_addr", tx.get("from", ""))),
                self._normalize_address(tx.get("to_addr", tx.get("to", ""))),
                money["value"],
                tx.get("gas", 21000),
                tx.get("gas_used", tx.get("gas", 21000)),
                money["fee"],
                money["burned"],
                tx.get("nonce", 0),
                tx.get("data", tx.get("tx_data", "")),
                # Omit / None / unknown → fail-closed 0 (never invent success).
                self._normalize_tx_status(tx.get("status")),
                tx.get("timestamp", int(time.time())),
            ),
        )

    def _insert_tx_receipt(self, tx: Dict, block_hash: str, block_height: int) -> None:
        from runtime.amount import tx_money_abs

        tx_hash = tx.get("hash", tx.get("tx_hash", ""))
        if not tx_hash:
            return
        money = tx_money_abs(tx)
        self.conn.execute(
            """INSERT OR REPLACE INTO tx_receipts
               (tx_hash, block_height, block_hash, from_addr, to_addr, value,
                fee, burned, gas_used, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                tx_hash,
                int(tx.get("block_height", block_height) or block_height),
                block_hash,
                self._normalize_address(tx.get("from_addr", tx.get("from", ""))),
                self._normalize_address(tx.get("to_addr", tx.get("to", ""))),
                money["value"],
                money["fee"],
                money["burned"],
                int(tx.get("gas_used", tx.get("gas", 21000))),
                # Omitted status → fail-closed (normalize None → 0).
                self._normalize_tx_status(tx.get("status")),
                int(tx.get("timestamp", time.time())),
            ),
        )

    def get_tx_receipt(self, tx_hash: str) -> Optional[Dict]:
        from runtime.amount import tx_money_abs

        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM tx_receipts WHERE tx_hash = ?", (tx_hash,)
            ).fetchone()
            if not row:
                return None
            money = tx_money_abs(dict(row))
            return {
                "tx_hash": row["tx_hash"],
                "block_height": row["block_height"],
                "block_hash": row["block_hash"],
                "from": row["from_addr"],
                "to": row["to_addr"],
                "value": money["value"],
                "fee": money["fee"],
                "burned": money["burned"],
                "gas_used": row["gas_used"],
                "status": self._normalize_tx_status(row["status"]),
                "timestamp": row["created_at"],
            }

    def get_receipts_by_block(self, block_height: int) -> List[Dict]:
        from runtime.amount import tx_money_abs

        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM tx_receipts WHERE block_height = ? ORDER BY created_at",
                (int(block_height),),
            ).fetchall()
            out: List[Dict] = []
            for r in rows:
                money = tx_money_abs(dict(r))
                out.append(
                    {
                        "tx_hash": r["tx_hash"],
                        "block_height": r["block_height"],
                        "block_hash": r["block_hash"],
                        "from": r["from_addr"],
                        "to": r["to_addr"],
                        "value": money["value"],
                        "fee": money["fee"],
                        "burned": money["burned"],
                        "gas_used": r["gas_used"],
                        "status": self._normalize_tx_status(r["status"]),
                        "timestamp": r["created_at"],
                    }
                )
            return out

    def get_chain_metrics(self, window: int = 32) -> Dict:
        """Core L1 metrics: block time, throughput hints."""
        from runtime.amount import from_satoshi_float, to_satoshi

        with self.lock:
            tip = self.get_chain_tip()
            tx_count = self.conn.execute(
                "SELECT COUNT(*) as c FROM transactions"
            ).fetchone()["c"]
            receipt_count = 0
            proposer_audit_count = 0
            receipts_enabled = False
            proposer_audit_enabled = False
            try:
                receipt_count = self.conn.execute(
                    "SELECT COUNT(*) as c FROM tx_receipts"
                ).fetchone()["c"]
                receipts_enabled = True
            except Exception as exc:
                print(f"[DB] get_chain_metrics receipts: {exc}")
            try:
                proposer_audit_count = self.conn.execute(
                    "SELECT COUNT(*) as c FROM block_proposer_audit"
                ).fetchone()["c"]
                proposer_audit_enabled = True
            except Exception as exc:
                print(f"[DB] get_chain_metrics proposer_audit: {exc}")
            rows = self.conn.execute(
                "SELECT height, timestamp, tx_count, total_burned FROM blocks "
                "ORDER BY height DESC LIMIT ?",
                (int(window),),
            ).fetchall()
            avg_block_time = 0.0
            if len(rows) >= 2:
                intervals = []
                ordered = sorted(rows, key=lambda r: r["height"])
                for i in range(1, len(ordered)):
                    dt = int(ordered[i]["timestamp"]) - int(ordered[i - 1]["timestamp"])
                    if dt > 0:
                        intervals.append(dt)
                if intervals:
                    avg_block_time = sum(intervals) / len(intervals)
            target = 15.0
            window_tx = sum(int(r["tx_count"] or 0) for r in rows)
            window_elapsed = 0.0
            if len(rows) >= 2:
                ordered = sorted(rows, key=lambda r: r["height"])
                window_elapsed = float(
                    max(0, int(ordered[-1]["timestamp"]) - int(ordered[0]["timestamp"]))
                )
            tps = (window_tx / max(window_elapsed, 1.0)) if window_elapsed > 0 else 0.0
            return {
                "height": tip,
                "tx_count": int(tx_count),
                "receipt_count": int(receipt_count),
                "proposer_audit_count": int(proposer_audit_count),
                "receipts_enabled": receipts_enabled,
                "proposer_audit_enabled": proposer_audit_enabled,
                "state_root_strict_p2p": True,
                "avg_block_time_sec": round(avg_block_time, 2),
                "target_block_time_sec": target,
                "blocks_sampled": len(rows),
                "window_tx_count": int(window_tx),
                "window_elapsed_sec": round(window_elapsed, 2),
                "tps": round(tps, 6),
                "burn_last_window": round(
                    from_satoshi_float(
                        sum(to_satoshi(r["total_burned"] or 0) for r in rows)
                    ),
                    6,
                ),
                "engine": self.engine,
            }

    def get_proposer_audit_log(
        self,
        limit: int = 50,
        offset: int = 0,
        proposer: str = "",
    ) -> List[Dict]:
        from runtime.amount import money_abs

        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        with self.lock:
            if proposer:
                addr = self._normalize_address(proposer)
                rows = self.conn.execute(
                    """SELECT * FROM block_proposer_audit
                       WHERE proposer=?
                       ORDER BY height DESC LIMIT ? OFFSET ?""",
                    (addr, limit, offset),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    """SELECT * FROM block_proposer_audit
                       ORDER BY height DESC LIMIT ? OFFSET ?""",
                    (limit, offset),
                ).fetchall()
            return [
                {
                    "height": r["height"],
                    "block_hash": r["block_hash"],
                    "proposer": r["proposer"],
                    "tx_count": r["tx_count"],
                    "total_burned": money_abs(r["total_burned"], field="total_burned"),
                    "timestamp": r["block_ts"],
                    "recorded_at": r["recorded_at"],
                }
                for r in rows
            ]

    def count_proposer_audit(
        self, proposer: str = ""
    ) -> int:
        with self.lock:
            if proposer:
                addr = self._normalize_address(proposer)
                return int(self.conn.execute(
                    "SELECT COUNT(*) as c FROM block_proposer_audit WHERE proposer=?",
                    (addr,),
                ).fetchone()["c"])
            return int(self.conn.execute(
                "SELECT COUNT(*) as c FROM block_proposer_audit"
            ).fetchone()["c"])

    def get_proposer_stats(self, limit: int = 20) -> List[Dict]:
        """Top proposers by blocks proposed."""
        limit = max(1, min(int(limit), 100))
        with self.lock:
            rows = self.conn.execute(
                """SELECT proposer,
                          COUNT(*) as blocks_proposed,
                          SUM(tx_count) as total_txs,
                          SUM(total_burned) as total_burned,
                          MAX(height) as last_height,
                          MIN(height) as first_height
                   FROM block_proposer_audit
                   GROUP BY proposer
                   ORDER BY blocks_proposed DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_proposer_detail(self, address: str, recent_limit: int = 10) -> Dict:
        from runtime.amount import money_abs

        addr = self._normalize_address(address)
        with self.lock:
            row = self.conn.execute(
                """SELECT COUNT(*) as blocks_proposed,
                          SUM(tx_count) as total_txs,
                          SUM(total_burned) as total_burned,
                          MAX(height) as last_height,
                          MIN(height) as first_height
                   FROM block_proposer_audit WHERE proposer=?""",
                (addr,),
            ).fetchone()
            recent = self.get_proposer_audit_log(
                limit=recent_limit, offset=0, proposer=addr
            )
            return {
                "proposer": addr,
                "blocks_proposed": int(row["blocks_proposed"] or 0),
                "total_txs": int(row["total_txs"] or 0),
                "total_burned": money_abs(row["total_burned"] or 0, field="total_burned"),
                "first_height": row["first_height"],
                "last_height": row["last_height"],
                "recent_blocks": recent,
            }

    def record_state_root_mismatch(
        self,
        height: int,
        expected_root: str,
        computed_root: str,
        source: str = "p2p",
        proposer: str = "",
    ) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT INTO state_root_mismatches
                   (height, expected_root, computed_root, source, proposer, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    int(height),
                    str(expected_root or ""),
                    str(computed_root or ""),
                    str(source or "p2p"),
                    self._normalize_address(proposer),
                    int(time.time()),
                ),
            )
            self.conn.commit()

    def get_state_root_mismatches(self, limit: int = 20) -> List[Dict]:
        limit = max(1, min(int(limit), 100))
        with self.lock:
            rows = self.conn.execute(
                """SELECT height, expected_root, computed_root, source, proposer, created_at
                   FROM state_root_mismatches
                   ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def record_tx_propagation_event(
        self,
        tx_hash: str,
        stage: str,
        node_id: str = "",
        peer_id: str = "",
        block_height: int = 0,
        detail: Any = None,
        _no_commit: bool = False,
    ) -> None:
        if not tx_hash or not stage:
            return
        payload = detail if isinstance(detail, dict) else {}
        with self.lock:
            self.conn.execute(
                """INSERT INTO tx_propagation_events
                   (tx_hash, stage, node_id, peer_id, block_height, detail, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    str(tx_hash),
                    str(stage),
                    str(node_id or ""),
                    str(peer_id or ""),
                    int(block_height or 0),
                    json.dumps(payload, ensure_ascii=False),
                    int(time.time()),
                ),
            )
            if not _no_commit:
                self.conn.commit()

    def get_tx_propagation_trace(self, tx_hash: str) -> Dict:
        with self.lock:
            rows = self.conn.execute(
                """SELECT stage, node_id, peer_id, block_height, detail, created_at
                   FROM tx_propagation_events
                   WHERE tx_hash=?
                   ORDER BY id ASC""",
                (str(tx_hash),),
            ).fetchall()
            events = []
            for r in rows:
                detail = self._loads_json_or_none(r["detail"] or "{}", context="tx_propagation_detail")
                if detail is None:
                    detail = {}
                events.append({
                    "stage": r["stage"],
                    "node_id": r["node_id"],
                    "peer_id": r["peer_id"],
                    "block_height": r["block_height"],
                    "detail": detail,
                    "timestamp": r["created_at"],
                })
            receipt = self.get_tx_receipt(tx_hash)
            tx_row = self.get_transaction(tx_hash)
            stages = [e["stage"] for e in events]
            status = "unknown"
            if receipt or tx_row:
                status = "confirmed"
            elif "block_included" in stages:
                status = "included"
            elif "mempool_local" in stages or "mempool_remote" in stages:
                status = "mempool"
            elif events:
                status = "propagating"
            return {
                "tx_hash": tx_hash,
                "status": status,
                "events": events,
                "receipt": receipt,
                "transaction": tx_row,
            }

    def get_recent_tx_propagation(self, limit: int = 20) -> List[Dict]:
        limit = max(1, min(int(limit), 100))
        with self.lock:
            rows = self.conn.execute(
                """SELECT tx_hash, MAX(created_at) as last_ts
                   FROM tx_propagation_events
                   GROUP BY tx_hash
                   ORDER BY last_ts DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [
                self.get_tx_propagation_trace(r["tx_hash"])
                for r in rows
            ]

    def save_transaction(self, tx: Dict) -> bool:
        with self.lock:
            try:
                self._insert_transaction(tx)
                self.conn.commit()
                return True
            except Exception as e:
                self.conn.rollback()
                print(f"[DB] save_transaction error: {e}")
                return False

    def get_transaction(self, tx_hash: str) -> Optional[Dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM transactions WHERE hash=?", (tx_hash,)
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def _normalize_address(address: str) -> str:
        return (address or "").strip().lower()

    def _serialize_tx_row(self, row: Dict, viewer_addr: str = "") -> Dict:
        from runtime.amount import tx_money_abs

        viewer = self._normalize_address(viewer_addr)
        from_addr = self._normalize_address(row.get("from_addr", ""))
        to_addr = self._normalize_address(row.get("to_addr", ""))
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
            "status": self._normalize_tx_status(row.get("status")),
            "timestamp": int(row.get("timestamp", 0)),
            "direction": direction,
        }

    def count_address_transactions(
        self, address: str, direction: str = "all"
    ) -> int:
        addr = self._normalize_address(address)
        if not addr:
            return 0
        with self.lock:
            if direction == "sent":
                q = "SELECT COUNT(*) as c FROM transactions WHERE LOWER(from_addr)=?"
                params: tuple = (addr,)
            elif direction == "received":
                q = "SELECT COUNT(*) as c FROM transactions WHERE LOWER(to_addr)=?"
                params = (addr,)
            else:
                q = (
                    "SELECT COUNT(*) as c FROM transactions "
                    "WHERE LOWER(from_addr)=? OR LOWER(to_addr)=?"
                )
                params = (addr, addr)
            return int(self.conn.execute(q, params).fetchone()["c"])

    def get_transactions_by_address(
        self,
        address: str,
        limit: int = 50,
        offset: int = 0,
        direction: str = "all",
    ) -> List[Dict]:
        addr = self._normalize_address(address)
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        with self.lock:
            if direction == "sent":
                where = "LOWER(from_addr)=?"
                params: List = [addr]
            elif direction == "received":
                where = "LOWER(to_addr)=?"
                params = [addr]
            else:
                where = "(LOWER(from_addr)=? OR LOWER(to_addr)=?)"
                params = [addr, addr]
            rows = self.conn.execute(
                f"""SELECT * FROM transactions
                    WHERE {where}
                    ORDER BY block_height DESC, rowid DESC
                    LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            ).fetchall()
            return [self._serialize_tx_row(dict(r), addr) for r in rows]

    def get_address_activity(self, address: str) -> Dict:
        addr = self._normalize_address(address)
        with self.lock:
            sent = int(self.conn.execute(
                "SELECT COUNT(*) as c FROM transactions WHERE LOWER(from_addr)=?",
                (addr,),
            ).fetchone()["c"])
            received = int(self.conn.execute(
                "SELECT COUNT(*) as c FROM transactions WHERE LOWER(to_addr)=?",
                (addr,),
            ).fetchone()["c"])
            total = int(self.conn.execute(
                "SELECT COUNT(*) as c FROM transactions "
                "WHERE LOWER(from_addr)=? OR LOWER(to_addr)=?",
                (addr, addr),
            ).fetchone()["c"])
            blocks_proposed = int(self.conn.execute(
                "SELECT COUNT(*) as c FROM blocks WHERE LOWER(miner)=?",
                (addr,),
            ).fetchone()["c"])
            row = self.conn.execute(
                """SELECT MAX(block_height) as h FROM transactions
                   WHERE LOWER(from_addr)=? OR LOWER(to_addr)=?""",
                (addr, addr),
            ).fetchone()
            last_h = int(row["h"]) if row and row["h"] is not None else None
            bal_row = self.conn.execute(
                "SELECT balance, balance_satoshi FROM accounts WHERE address=?", (addr,)
            ).fetchone()
            nonce_row = self.conn.execute(
                "SELECT nonce FROM accounts WHERE address=?", (addr,)
            ).fetchone()
            code_row = self.conn.execute(
                "SELECT code FROM accounts WHERE address=?", (addr,)
            ).fetchone()
            from runtime.amount import account_balance_abs, account_satoshi

            bal_dict = dict(bal_row) if bal_row else None
            return {
                "address": addr,
                "balance": account_balance_abs(bal_dict),
                "balance_satoshi": account_satoshi(bal_dict),
                "nonce": int(nonce_row["nonce"]) if nonce_row else 0,
                "sent_count": sent,
                "received_count": received,
                "tx_count": total,
                "blocks_proposed": blocks_proposed,
                "last_tx_height": last_h,
                "is_contract": bool(code_row and code_row["code"]),
            }

    def get_recent_transactions(self, limit: int = 30) -> List[Dict]:
        """Последние транзакции по всей цепи (для dashboard/explorer)."""
        with self.lock:
            rows = self.conn.execute(
                """SELECT * FROM transactions
                   ORDER BY block_height DESC, rowid DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_transactions_in_block(self, height: int) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM transactions WHERE block_height=?", (height,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Аккаунты / балансы ───────────────────────────────────────────────────

    def get_balance(self, address: str) -> float:
        from runtime.amount import account_balance_abs

        with self.lock:
            row = self.conn.execute(
                "SELECT balance, balance_satoshi FROM accounts WHERE address=?",
                (address,),
            ).fetchone()
            return account_balance_abs(dict(row) if row else None)

    def get_balance_satoshi(self, address: str) -> int:
        from runtime.amount import account_satoshi

        with self.lock:
            row = self.conn.execute(
                "SELECT balance, balance_satoshi FROM accounts WHERE address=?",
                (address,),
            ).fetchone()
            return account_satoshi(dict(row) if row else None)

    def _apply_balance_delta(self, address: str, delta: float) -> None:
        from runtime.amount import apply_delta_satoshi, from_satoshi_float, to_satoshi

        row = self.conn.execute(
            "SELECT balance, balance_satoshi FROM accounts WHERE address=?",
            (address,),
        ).fetchone()
        if row and row["balance_satoshi"] is not None:
            cur_sat = int(row["balance_satoshi"])
        elif row:
            cur_sat = to_satoshi(row["balance"] or 0)
        else:
            cur_sat = 0
        new_sat = apply_delta_satoshi(cur_sat, delta)
        new_abs = from_satoshi_float(new_sat)
        self.conn.execute(
            """INSERT INTO accounts (address, balance, balance_satoshi, nonce)
               VALUES (?, ?, ?, 0)
               ON CONFLICT(address) DO UPDATE
               SET balance=excluded.balance, balance_satoshi=excluded.balance_satoshi""",
            (address, new_abs, new_sat),
        )

    def update_balance(self, address: str, delta: float) -> float:
        """Изменяет баланс на delta (может быть отрицательным). Возвращает новый баланс."""
        with self.lock:
            self._apply_balance_delta(address, delta)
            self.conn.commit()
            return self.get_balance(address)

    def set_balance(self, address: str, balance: int) -> None:
        from runtime.amount import dual_write_balance

        if isinstance(balance, bool):
            raise TypeError("bool is not an amount")
        payload: dict = {}
        dual_write_balance(payload, balance)
        with self.lock:
            self.conn.execute(
                """INSERT INTO accounts (address, balance, balance_satoshi) VALUES (?,?,?)
                   ON CONFLICT(address) DO UPDATE SET
                     balance=excluded.balance,
                     balance_satoshi=excluded.balance_satoshi""",
                (address, payload["balance"], payload["balance_satoshi"]),
            )
            self.conn.commit()

    def get_nonce(self, address: str) -> int:
        with self.lock:
            row = self.conn.execute(
                "SELECT nonce FROM accounts WHERE address=?", (address,)
            ).fetchone()
            return row["nonce"] if row else 0

    def increment_nonce(self, address: str) -> int:
        with self.lock:
            self.conn.execute(
                """INSERT INTO accounts (address, balance, balance_satoshi, nonce) VALUES (?,0,0,1)
                   ON CONFLICT(address) DO UPDATE SET nonce=nonce+1""",
                (address,),
            )
            self.conn.commit()
            return self.get_nonce(address)

    def get_account(self, address: str) -> Optional[Dict]:
        from runtime.amount import account_satoshi, from_satoshi_float

        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM accounts WHERE address=?", (address,)
            ).fetchone()
            if not row:
                return None
            out = dict(row)
            sat = account_satoshi(out)
            out["balance_satoshi"] = sat
            out["balance"] = from_satoshi_float(sat)
            return out

    def save_account(self, address: str, balance: float = 0.0,
                     nonce: int = 0, code: str = None, storage: str = None) -> None:
        from runtime.amount import dual_write_balance

        if isinstance(balance, bool):
            raise TypeError("bool is not an amount")
        payload: dict = {}
        dual_write_balance(payload, balance)
        with self.lock:
            self.conn.execute(
                """INSERT INTO accounts (address, balance, balance_satoshi, nonce, code, storage)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(address) DO UPDATE
                   SET balance=excluded.balance, balance_satoshi=excluded.balance_satoshi,
                       nonce=excluded.nonce, code=excluded.code, storage=excluded.storage""",
                (address, payload["balance"], payload["balance_satoshi"], nonce, code, storage),
            )
            self.conn.commit()

    def update_account_storage(self, address: str, storage: Dict) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE accounts SET storage=? WHERE address=?",
                (json.dumps(storage), address),
            )
            self.conn.commit()

    # ── Валидаторы ───────────────────────────────────────────────────────────

    def save_validator(self, address: str, stake: float) -> None:
        from runtime.amount import money_abs

        stake_abs = money_abs(stake, field="stake")
        with self.lock:
            self.conn.execute(
                """INSERT INTO validators (address, stake, joined_at)
                   VALUES (?,?,?)
                   ON CONFLICT(address) DO UPDATE SET stake=excluded.stake""",
                (address, stake_abs, int(time.time())),
            )
            self.conn.commit()

    def get_validators(self, active_only: bool = True) -> List[Dict]:
        with self.lock:
            query = "SELECT * FROM validators"
            if active_only:
                query += " WHERE active=1 AND slashed=0"
            rows = self.conn.execute(query).fetchall()
            return [dict(r) for r in rows]

    def slash_validator(self, address: str) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE validators SET slashed=1, active=0 WHERE address=?", (address,)
            )
            self.conn.commit()

    # ── Финальность (Casper FFG) ─────────────────────────────────────────────

    def save_checkpoint(self, epoch: int, block_hash: str,
                        justified: bool = False, finalized: bool = False) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT INTO checkpoints (epoch, block_hash, justified, finalized)
                   VALUES (?,?,?,?)
                   ON CONFLICT(epoch) DO UPDATE
                   SET justified=excluded.justified, finalized=excluded.finalized""",
                (epoch, block_hash, int(justified), int(finalized)),
            )
            self.conn.commit()

    def get_checkpoint(self, epoch: int) -> Optional[Dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM checkpoints WHERE epoch=?", (epoch,)
            ).fetchone()
            return dict(row) if row else None

    # ── Сжигание токенов ─────────────────────────────────────────────────────

    def _insert_burn_record(self, block_height: int, burned_amount: float) -> None:
        from runtime.amount import from_satoshi_float, money_abs, to_satoshi

        burned = money_abs(burned_amount, field="burned")
        prev = self.conn.execute(
            "SELECT COALESCE(MAX(total_burned),0) as tb FROM burn_stats"
        ).fetchone()
        total = from_satoshi_float(
            to_satoshi(prev["tb"] if prev else 0) + to_satoshi(burned)
        )
        self.conn.execute(
            """INSERT OR REPLACE INTO burn_stats (block_height, burned_amount, total_burned)
               VALUES (?,?,?)""",
            (block_height, burned, total),
        )

    def record_burn(self, block_height: int, burned_amount: float) -> None:
        with self.lock:
            self._insert_burn_record(block_height, burned_amount)
            self.conn.commit()

    def get_total_burned(self) -> float:
        from runtime.amount import money_abs

        with self.lock:
            row = self.conn.execute(
                "SELECT COALESCE(MAX(total_burned),0) as tb FROM burn_stats"
            ).fetchone()
            return money_abs(row["tb"] if row else 0, field="total_burned")

    def get_burn_stats(self) -> Dict:
        from runtime.amount import money_abs

        with self.lock:
            row = self.conn.execute(
                """SELECT COUNT(*) as blocks_with_burn,
                          COALESCE(SUM(burned_amount),0) as total,
                          COALESCE(AVG(burned_amount),0) as avg_per_block
                   FROM burn_stats"""
            ).fetchone()
            return {
                "total_burned": money_abs(row["total"] or 0, field="total_burned"),
                "avg_per_block": money_abs(row["avg_per_block"] or 0, field="avg_per_block"),
                "blocks_with_burn": int(row["blocks_with_burn"]),
            }

    # ── Мост (Cross-chain) ───────────────────────────────────────────────────

    def save_bridge_lock(self, from_addr: str, to_chain: str, to_addr: str,
                         amount: float, tx_hash: str) -> None:
        from runtime.amount import money_abs

        amt = money_abs(amount)
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO bridge_locks
                   (tx_hash, from_addr, to_chain, to_addr, amount, status, created_at)
                   VALUES (?,?,?,?,?,'pending',?)""",
                (tx_hash, from_addr, to_chain, to_addr, amt, int(time.time())),
            )
            self.conn.commit()

    def confirm_bridge_lock(self, tx_hash: str) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE bridge_locks SET status='confirmed' WHERE tx_hash=?", (tx_hash,)
            )
            self.conn.commit()

    def get_bridge_locks(self, limit: int = 50) -> List[Dict]:
        from runtime.amount import money_abs

        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM bridge_locks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            out = []
            for r in rows:
                row = dict(r)
                row["amount"] = money_abs(row.get("amount", 0), field="amount")
                out.append(row)
            return out

    def bridge_credit_key(self, from_chain: str, event_tx_hash: str, log_index: int = 0) -> str:
        """Replay key from source event identity (not claim recipient/amount)."""
        from crypto import native

        raw = (
            f"{(from_chain or '').strip()}:"
            f"{(event_tx_hash or '').strip()}:"
            f"{int(log_index)}"
        ).lower()
        return native.sha256_hex(raw.encode())

    def has_bridge_credit(self, credit_key: str) -> bool:
        with self.lock:
            row = self.conn.execute(
                "SELECT 1 FROM bridge_credits WHERE credit_key=?", (credit_key,)
            ).fetchone()
            return row is not None

    def save_bridge_credit(
        self,
        event_tx_hash: str,
        recipient: str,
        amount: float,
        from_chain: str,
        log_index: int = 0,
    ) -> str:
        key = self.bridge_credit_key(from_chain, event_tx_hash, log_index)
        from runtime.amount import money_abs

        amt = money_abs(amount)
        with self.lock:
            self.conn.execute(
                """INSERT OR IGNORE INTO bridge_credits
                   (credit_key, l1_tx_hash, recipient, amount, from_chain, credited_at)
                   VALUES (?,?,?,?,?,?)""",
                (key, event_tx_hash, recipient, amt, from_chain, int(time.time())),
            )
            self.conn.commit()
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
        """
        Insert-if-absent replay claim then credit recipient in one transaction.
        Returns {credited, duplicate, credit_key}.
        """
        from runtime.amount import money_abs

        amt = money_abs(amount)
        key = self.bridge_credit_key(from_chain, event_tx_hash, log_index)
        with self.atomic():
            row = self.conn.execute(
                "SELECT 1 FROM bridge_credits WHERE credit_key=?", (key,)
            ).fetchone()
            if row is not None:
                return {"credited": False, "duplicate": True, "credit_key": key}
            self.conn.execute(
                """INSERT INTO bridge_credits
                   (credit_key, l1_tx_hash, recipient, amount, from_chain, credited_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    key,
                    event_tx_hash,
                    recipient,
                    amt,
                    from_chain,
                    int(time.time()),
                ),
            )
            self.balance_delta(recipient, amt)
            lock_hash = (abs_tx_hash or event_tx_hash or "").strip()
            if lock_hash:
                self.conn.execute(
                    "UPDATE bridge_locks SET status='confirmed' WHERE tx_hash=?",
                    (lock_hash,),
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
        """Debit sender (fail on underflow), burn fee share, persist lock atomically."""
        from runtime.amount import (
            account_balance_abs,
            account_satoshi,
            dual_write_balance,
            from_satoshi_float,
            money_abs,
            try_debit_satoshi,
        )

        with self.atomic():
            row = self.get_account(from_addr) or {
                "address": from_addr,
                "balance": 0.0,
                "balance_satoshi": 0,
                "nonce": 0,
            }
            cur = int(account_satoshi(row))
            new_sat = try_debit_satoshi(cur, money_abs(amount))
            dual_write_balance(row, from_satoshi_float(new_sat))
            self.conn.execute(
                """INSERT INTO accounts (address, balance, balance_satoshi, nonce)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(address) DO UPDATE
                   SET balance=excluded.balance, balance_satoshi=excluded.balance_satoshi""",
                (
                    from_addr,
                    account_balance_abs(row),
                    int(new_sat),
                    int(row.get("nonce") or 0),
                ),
            )
            if burn_amount and burn_address:
                self.balance_delta(burn_address, money_abs(burn_amount, field="burn_amount"))
            self.conn.execute(
                """INSERT OR REPLACE INTO bridge_locks
                   (tx_hash, from_addr, to_chain, to_addr, amount, status, created_at)
                   VALUES (?,?,?,?,?,'pending',?)""",
                (
                    tx_hash,
                    from_addr,
                    to_chain,
                    to_addr,
                    money_abs(net_amount, field="net_amount"),
                    int(time.time()),
                ),
            )

    def refund_pending_bridge_lock(self, tx_hash: str) -> Dict:
        """Credit back pending lock amount and mark refunded atomically."""
        from runtime.amount import money_abs

        with self.atomic():
            row = self.conn.execute(
                "SELECT * FROM bridge_locks WHERE tx_hash=?", (tx_hash,)
            ).fetchone()
            if not row:
                return {"refunded": False, "error": "Lock not found or already processed"}
            lock = dict(row)
            if lock.get("status") != "pending":
                return {"refunded": False, "error": "Lock not found or already processed"}
            self.balance_delta(lock["from_addr"], money_abs(lock["amount"]))
            self.conn.execute(
                "UPDATE bridge_locks SET status='refunded' WHERE tx_hash=?",
                (tx_hash,),
            )
        return {
            "refunded": True,
            "tx_hash": tx_hash,
            "amount": money_abs(lock["amount"]),
        }

    def save_minivm_contract(self, address: str, bytecode: list, storage: dict, calls: int = 0) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO minivm_contracts
                   (address, bytecode, storage, deployed_at, calls)
                   VALUES (?,?,?,?,?)""",
                (
                    address,
                    json.dumps(bytecode, ensure_ascii=False),
                    json.dumps(storage, ensure_ascii=False),
                    int(time.time()),
                    calls,
                ),
            )
            self.conn.commit()

    def load_minivm_contracts(self) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM minivm_contracts").fetchall()
            out = []
            for row in rows:
                item = dict(row)
                bytecode = self._loads_json_or_none(item.get("bytecode") or "[]", context="minivm_bytecode")
                storage = self._loads_json_or_none(item.get("storage") or "{}", context="minivm_storage")
                item["bytecode"] = bytecode if bytecode is not None else []
                item["storage"] = storage if storage is not None else {}
                out.append(item)
            return out

    def save_slash_event(self, validator: str, reason: str, epoch: int, penalty: int) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT INTO slash_events (validator, reason, epoch, penalty, timestamp)
                   VALUES (?,?,?,?,?)""",
                (validator, reason, epoch, penalty, int(time.time())),
            )
            self.conn.execute(
                "UPDATE validators SET slashed=1, active=0 WHERE address=?",
                (validator,),
            )
            self.conn.commit()

    def get_slash_events(self, limit: int = 100) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM slash_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def save_evm_logs(
        self,
        contract_address: str,
        logs: List[Dict],
        block_height: int = 0,
        tx_hash: str = "",
        timestamp: int = 0,
    ) -> int:
        """Persist EVM event logs emitted during contract execution."""
        if not logs:
            return 0
        import time as _time
        ts = int(timestamp or _time.time())
        saved = 0
        with self.lock:
            base_idx = self.conn.execute(
                "SELECT COUNT(*) AS c FROM evm_logs WHERE contract_address=?",
                (contract_address,),
            ).fetchone()["c"]
            for i, entry in enumerate(logs):
                topics = entry.get("topics", [])
                if isinstance(topics, list):
                    topics_json = json.dumps(topics)
                else:
                    topics_json = "[]"
                data = entry.get("data", "")
                self.conn.execute(
                    """INSERT INTO evm_logs
                       (contract_address, block_height, tx_hash, log_index, topics, data, timestamp)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        contract_address,
                        int(block_height),
                        tx_hash or "",
                        int(base_idx) + i,
                        topics_json,
                        str(data),
                        ts,
                    ),
                )
                saved += 1
            self.conn.commit()
        return saved

    def get_evm_logs(
        self,
        contract_address: str = "",
        limit: int = 100,
    ) -> List[Dict]:
        return self.query_evm_logs(
            addresses=[contract_address] if contract_address else None,
            limit=limit,
        )

    def get_evm_logs_by_tx(self, tx_hash: str) -> List[Dict]:
        if not tx_hash:
            return []
        with self.lock:
            rows = self.conn.execute(
                """SELECT * FROM evm_logs WHERE tx_hash=?
                   ORDER BY log_index ASC, id ASC""",
                (tx_hash,),
            ).fetchall()
            return self._rows_to_evm_logs(rows)

    def query_evm_logs(
        self,
        from_block: int = 0,
        to_block: Optional[int] = None,
        addresses: Optional[List[str]] = None,
        topics: Optional[List] = None,
        limit: int = 10_000,
    ) -> List[Dict]:
        """Query persisted EVM logs (eth_getLogs-style filter)."""
        to_block = 2**63 - 1 if to_block is None else int(to_block)
        from_block = max(0, int(from_block))
        clauses = ["block_height >= ?", "block_height <= ?"]
        params: List = [from_block, to_block]
        if addresses:
            normalized = [self._normalize_address(a) for a in addresses if a]
            if normalized:
                placeholders = ",".join("?" for _ in normalized)
                clauses.append(f"contract_address IN ({placeholders})")
                params.extend(normalized)
        sql = (
            "SELECT * FROM evm_logs WHERE "
            + " AND ".join(clauses)
            + " ORDER BY block_height ASC, log_index ASC, id ASC LIMIT ?"
        )
        params.append(int(limit))
        with self.lock:
            rows = self.conn.execute(sql, params).fetchall()
        logs = self._rows_to_evm_logs(rows)
        if topics:
            logs = [row for row in logs if self._evm_log_topics_match(row.get("topics", []), topics)]
        return logs

    def _rows_to_evm_logs(self, rows) -> List[Dict]:
        out = []
        for r in rows:
            item = dict(r)
            topics = self._loads_json_or_none(item.get("topics") or "[]", context="evm_log_topics")
            item["topics"] = topics if topics is not None else []
            out.append(item)
        return out

    @staticmethod
    def _evm_log_topics_match(log_topics: List, filter_topics: List) -> bool:
        if not filter_topics:
            return True
        for i, rule in enumerate(filter_topics):
            if rule is None:
                continue
            if i >= len(log_topics):
                return False
            log_topic = str(log_topics[i]).lower()
            if isinstance(rule, (list, tuple)):
                allowed = {str(t).lower() for t in rule if t is not None}
                if log_topic not in allowed:
                    return False
            elif log_topic != str(rule).lower():
                return False
        return True

    def save_oracle_feed(
        self,
        feed_id: str,
        symbol: str,
        value: float,
        source: str = "",
        reporter: str = "",
        signature: str = "",
        payload: str = "{}",
        block_height: int = 0,
        submitted_at: int = 0,
    ) -> None:
        import time as _time
        value = parse_finite_number(value, field="value")
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO oracle_feeds
                   (feed_id, symbol, value, source, reporter, signature,
                    payload, block_height, submitted_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    feed_id,
                    symbol,
                    value,
                    source,
                    reporter,
                    signature,
                    payload,
                    int(block_height),
                    int(submitted_at or _time.time()),
                ),
            )
            self.conn.commit()

    def get_oracle_feeds(self, symbol: str = "", limit: int = 50) -> List[Dict]:
        with self.lock:
            if symbol:
                rows = self.conn.execute(
                    """SELECT * FROM oracle_feeds WHERE symbol=?
                       ORDER BY submitted_at DESC LIMIT ?""",
                    (symbol.lower(), int(limit)),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM oracle_feeds ORDER BY submitted_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            return [dict(r) for r in rows]

    def save_oracle_report(self, report: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO oracle_reports
                   (report_id, symbol, reporter, value, signature, payload, submitted_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    report["report_id"],
                    report["symbol"],
                    report["reporter"],
                    parse_finite_number(report["value"], field="value"),
                    report.get("signature", ""),
                    report.get("payload", "{}"),
                    int(report.get("submitted_at", 0)),
                ),
            )
            self.conn.commit()

    def get_oracle_reports(
        self, symbol: str = "", since: int = 0, limit: int = 50
    ) -> List[Dict]:
        with self.lock:
            if symbol:
                rows = self.conn.execute(
                    """SELECT * FROM oracle_reports
                       WHERE symbol=? AND submitted_at>=?
                       ORDER BY submitted_at DESC LIMIT ?""",
                    (symbol.lower(), int(since), int(limit)),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    """SELECT * FROM oracle_reports
                       WHERE submitted_at>=?
                       ORDER BY submitted_at DESC LIMIT ?""",
                    (int(since), int(limit)),
                ).fetchall()
            return [dict(r) for r in rows]

    # ── Lightning Network (Wave 40 persistence) ─────────────────────────────

    def save_lightning_channel(self, ch: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO lightning_channels
                   (channel_id, node1, node2, capacity, balance1, balance2,
                    status, fee_rate, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    ch["channel_id"],
                    ch["node1"],
                    ch["node2"],
                    money_abs(ch["capacity"], field="capacity"),
                    money_abs(ch["balance1"], field="balance1"),
                    money_abs(ch["balance2"], field="balance2"),
                    ch.get("status", "open"),
                    parse_finite_number(ch.get("fee_rate", 0.00001), field="fee_rate"),
                    int(ch.get("created_at", 0)),
                ),
            )
            self.conn.commit()

    def get_lightning_channels(self, status: str = "") -> List[Dict]:
        with self.lock:
            if status:
                rows = self.conn.execute(
                    "SELECT * FROM lightning_channels WHERE status=? ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM lightning_channels ORDER BY created_at DESC"
                ).fetchall()
            return [Database._lightning_channel_row(dict(r)) for r in rows]

    @staticmethod
    def _lightning_channel_row(row: Dict) -> Dict:
        row["capacity"] = money_abs(row.get("capacity"), field="capacity")
        row["balance1"] = money_abs(row.get("balance1"), field="balance1")
        row["balance2"] = money_abs(row.get("balance2"), field="balance2")
        row["fee_rate"] = parse_finite_number(row.get("fee_rate", 0), field="fee_rate")
        return row

    def save_lightning_payment(self, p: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO lightning_payments
                   (payment_id, channel_id, from_node, to_node, amount, fee,
                    status, payment_hash, timestamp)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    p["payment_id"],
                    p["channel_id"],
                    p["from_node"],
                    p["to_node"],
                    money_abs(p["amount"], field="amount"),
                    money_abs(p.get("fee", 0), field="fee"),
                    p.get("status", "completed"),
                    p.get("payment_hash", ""),
                    int(p.get("timestamp", 0)),
                ),
            )
            self.conn.commit()

    def get_lightning_payments(self, limit: int = 50) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM lightning_payments ORDER BY timestamp DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [Database._lightning_payment_row(dict(r)) for r in rows]

    @staticmethod
    def _lightning_payment_row(row: Dict) -> Dict:
        row["amount"] = money_abs(row.get("amount"), field="amount")
        row["fee"] = money_abs(row.get("fee", 0), field="fee")
        return row

    def save_lightning_htlc(self, h: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO lightning_htlcs
                   (htlc_id, channel_id, payment_hash, amount, expiry,
                    sender, receiver, status, preimage, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    h["htlc_id"],
                    h["channel_id"],
                    h["payment_hash"],
                    money_abs(h["amount"], field="amount"),
                    int(h["expiry"]),
                    h["sender"],
                    h["receiver"],
                    h.get("status", "pending"),
                    h.get("preimage", ""),
                    int(h.get("created_at", 0)),
                ),
            )
            self.conn.commit()

    def get_lightning_htlcs(self, channel_id: str = "", limit: int = 100) -> List[Dict]:
        with self.lock:
            if channel_id:
                rows = self.conn.execute(
                    "SELECT * FROM lightning_htlcs WHERE channel_id=? ORDER BY created_at DESC LIMIT ?",
                    (channel_id, int(limit)),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM lightning_htlcs ORDER BY created_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            return [Database._lightning_htlc_row(dict(r)) for r in rows]

    @staticmethod
    def _lightning_htlc_row(row: Dict) -> Dict:
        row["amount"] = money_abs(row.get("amount"), field="amount")
        return row

    def save_lightning_channel_state(self, st: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO lightning_channel_states
                   (channel_id, version, balance1, balance2, state_hash,
                    sig_node1, sig_node2, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    st["channel_id"],
                    int(st["version"]),
                    money_abs(st["balance1"], field="balance1"),
                    money_abs(st["balance2"], field="balance2"),
                    st["state_hash"],
                    st.get("sig_node1", ""),
                    st.get("sig_node2", ""),
                    int(st.get("updated_at", 0)),
                ),
            )
            self.conn.commit()

    def get_lightning_channel_state(self, channel_id: str) -> Optional[Dict]:
        with self.lock:
            row = self.conn.execute(
                """SELECT * FROM lightning_channel_states
                   WHERE channel_id=? ORDER BY version DESC LIMIT 1""",
                (channel_id,),
            ).fetchone()
            if not row:
                return None
            out = dict(row)
            out["balance1"] = money_abs(out.get("balance1"), field="balance1")
            out["balance2"] = money_abs(out.get("balance2"), field="balance2")
            return out

    # ── Plasma L2 (Wave 40 persistence) ─────────────────────────────────────

    def save_plasma_deposit(self, dep: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO plasma_deposits
                   (deposit_id, from_addr, amount, main_tx_hash, created_at, status)
                   VALUES (?,?,?,?,?,?)""",
                (
                    dep["id"],
                    dep["from"],
                    money_abs(dep["amount"], field="amount"),
                    dep.get("main_tx_hash", ""),
                    int(dep.get("created_at", 0)),
                    dep.get("status", "confirmed"),
                ),
            )
            self.conn.commit()

    def get_plasma_deposits(self, limit: int = 200) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM plasma_deposits ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            out = []
            for r in rows:
                out.append({
                    "id": r["deposit_id"],
                    "from": r["from_addr"],
                    "amount": money_abs(r["amount"], field="amount"),
                    "main_tx_hash": r["main_tx_hash"],
                    "created_at": r["created_at"],
                    "status": r["status"],
                })
            return out

    def save_plasma_block(self, block: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO plasma_blocks
                   (block_id, block_hash, parent_hash, transactions,
                    total_amount, tx_count, created_at, merkle_root, tx_root)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    int(block["block_id"]),
                    block["block_hash"],
                    block["parent_hash"],
                    json.dumps(block.get("transactions", [])),
                    money_abs(block.get("total_amount", 0), field="total_amount"),
                    int(block.get("transaction_count", block.get("tx_count", 0))),
                    int(block.get("created_at", 0)),
                    block.get("merkle_root", ""),
                    block.get("tx_root", block.get("merkle_root", "")),
                ),
            )
            self.conn.commit()

    def get_plasma_blocks(self, limit: int = 20) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM plasma_blocks ORDER BY block_id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            out = []
            for r in rows:
                txs = self._loads_json(r["transactions"] or "[]", context="plasma_txs", default=[])
                out.append({
                    "block_id": r["block_id"],
                    "block_hash": r["block_hash"],
                    "parent_hash": r["parent_hash"],
                    "transactions": txs,
                    "total_amount": money_abs(r["total_amount"], field="total_amount"),
                    "transaction_count": r["tx_count"],
                    "created_at": r["created_at"],
                })
            return sorted(out, key=lambda b: b["block_id"])

    def save_plasma_exit(self, ex: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO plasma_exits
                   (exit_id, deposit_id, user_addr, amount, created_at, status)
                   VALUES (?,?,?,?,?,?)""",
                (
                    ex["id"],
                    ex["deposit_id"],
                    ex["user"],
                    money_abs(ex["amount"], field="amount"),
                    int(ex.get("created_at", 0)),
                    ex.get("status", "pending"),
                ),
            )
            self.conn.commit()

    def get_plasma_exits(self, limit: int = 100) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM plasma_exits ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            out = []
            for r in rows:
                out.append({
                    "id": r["exit_id"],
                    "deposit_id": r["deposit_id"],
                    "user": r["user_addr"],
                    "amount": money_abs(r["amount"], field="amount"),
                    "created_at": r["created_at"],
                    "status": r["status"],
                })
            return out

    # ── Crypto Will (Wave 41 persistence) ───────────────────────────────────

    def save_crypto_will(self, will: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO crypto_wills
                   (will_id, owner, heir, amount, assets, execution_time,
                    created_at, status, witnesses)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    will["will_id"],
                    will["owner"],
                    will["heir"],
                    money_abs(will["amount"], field="amount"),
                    json.dumps(will.get("assets", {})),
                    int(will.get("execution_time", 0)),
                    int(will.get("created_at", 0)),
                    will.get("status", "pending"),
                    json.dumps(will.get("witnesses", [])),
                ),
            )
            self.conn.commit()

    def get_crypto_wills(self, owner: str = "", status: str = "", limit: int = 100) -> List[Dict]:
        with self.lock:
            q = "SELECT * FROM crypto_wills WHERE 1=1"
            params: list = []
            if owner:
                q += " AND (owner=? OR heir=?)"
                params.extend([owner, owner])
            if status:
                q += " AND status=?"
                params.append(status)
            q += " ORDER BY created_at DESC LIMIT ?"
            params.append(int(limit))
            rows = self.conn.execute(q, params).fetchall()
            out = []
            for r in rows:
                assets = self._loads_json(r["assets"] or "{}", context="will_assets", default={})
                witnesses = self._loads_json(r["witnesses"] or "[]", context="will_witnesses", default=[])
                out.append({
                    "will_id": r["will_id"],
                    "owner": r["owner"],
                    "heir": r["heir"],
                    "amount": money_abs(r["amount"], field="amount"),
                    "assets": assets,
                    "execution_time": r["execution_time"],
                    "created_at": r["created_at"],
                    "status": r["status"],
                    "witnesses": witnesses,
                })
            return out

    def delete_crypto_will(self, will_id: str) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM crypto_wills WHERE will_id=?", (will_id,))
            self.conn.commit()

    # ── WASM VM (Wave 42 persistence) ─────────────────────────────────────────

    def save_wasm_contract(self, contract: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO wasm_contracts
                   (address, code, owner, name, created_at, call_count, storage_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    contract["address"],
                    contract.get("code", ""),
                    contract["owner"],
                    contract.get("name", ""),
                    int(contract.get("created_at", 0)),
                    int(contract.get("call_count", 0)),
                    json.dumps(contract.get("storage", {})),
                ),
            )
            self.conn.commit()

    def get_wasm_contracts(self, limit: int = 200) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM wasm_contracts ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            out = []
            for r in rows:
                storage = self._loads_json(r["storage_json"] or "{}", context="wasm_storage", default={})
                out.append({
                    "address": r["address"],
                    "code": r["code"],
                    "owner": r["owner"],
                    "name": r["name"],
                    "created_at": r["created_at"],
                    "call_count": r["call_count"],
                    "storage": storage,
                })
            return out

    def get_wasm_contract(self, address: str) -> Optional[Dict]:
        with self.lock:
            row = self.conn.execute(
                "SELECT * FROM wasm_contracts WHERE address=?", (address,)
            ).fetchone()
            if not row:
                return None
            storage = self._loads_json(row["storage_json"] or "{}", context="wasm_storage", default={})
            return {
                "address": row["address"],
                "code": row["code"],
                "owner": row["owner"],
                "name": row["name"],
                "created_at": row["created_at"],
                "call_count": row["call_count"],
                "storage": storage,
            }

    def save_wasm_event(self, event: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO wasm_events
                   (event_id, contract_addr, event_type, payload, timestamp)
                   VALUES (?,?,?,?,?)""",
                (
                    event["event_id"],
                    event.get("contract_addr", ""),
                    event.get("event_type", event.get("type", "")),
                    json.dumps(event.get("payload", event)),
                    int(event.get("timestamp", 0)),
                ),
            )
            self.conn.commit()

    def get_wasm_events(self, limit: int = 100) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM wasm_events ORDER BY timestamp DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            out = []
            for r in rows:
                payload = self._loads_json(r["payload"] or "{}", context="wasm_event", default={})
                out.append({
                    "event_id": r["event_id"],
                    "contract_addr": r["contract_addr"],
                    "event_type": r["event_type"],
                    "payload": payload,
                    "timestamp": r["timestamp"],
                })
            return out

    # ── AI Agents (Wave 43 persistence) ─────────────────────────────────────

    def save_ai_agent(self, agent: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO ai_agents
                   (agent_id, name, owner, agent_type, status, created_at,
                    last_action, performance_score, total_profit, actions_count,
                    strategy_json, memory_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    agent["agent_id"],
                    agent["name"],
                    agent["owner"],
                    agent.get("agent_type", "transformer"),
                    agent.get("status", "active"),
                    int(agent.get("created_at", 0)),
                    int(agent.get("last_action", 0)),
                    parse_finite_number(agent.get("performance_score", 0), field="performance_score"),
                    money_abs(agent.get("total_profit", 0), field="total_profit"),
                    int(agent.get("actions_count", 0)),
                    json.dumps(agent.get("strategy", {})),
                    json.dumps(agent.get("memory", [])),
                ),
            )
            self.conn.commit()

    def get_ai_agents(self, owner: str = "", limit: int = 200) -> List[Dict]:
        with self.lock:
            if owner:
                rows = self.conn.execute(
                    "SELECT * FROM ai_agents WHERE owner=? ORDER BY created_at DESC LIMIT ?",
                    (owner, int(limit)),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM ai_agents ORDER BY created_at DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            out = []
            for r in rows:
                strategy = self._loads_json(r["strategy_json"] or "{}", context="ai_strategy", default={})
                memory = self._loads_json(r["memory_json"] or "[]", context="ai_memory", default=[])
                out.append({
                    "agent_id": r["agent_id"],
                    "name": r["name"],
                    "owner": r["owner"],
                    "agent_type": r["agent_type"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "last_action": r["last_action"],
                    "performance_score": parse_finite_number(
                        r["performance_score"], field="performance_score"
                    ),
                    "total_profit": money_abs(r["total_profit"], field="total_profit"),
                    "actions_count": r["actions_count"],
                    "strategy": strategy,
                    "memory": memory,
                })
            return out

    def get_ai_agent(self, agent_id: str) -> Optional[Dict]:
        rows = self.get_ai_agents(limit=500)
        for r in rows:
            if r["agent_id"] == agent_id:
                return r
        return None

    # ── MEV simulations (Wave 44 persistence) ───────────────────────────────

    def save_mev_simulation(self, sim: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO mev_simulations
                   (sim_id, sim_type, profit, payload, created_at)
                   VALUES (?,?,?,?,?)""",
                (
                    sim["sim_id"],
                    sim.get("sim_type", sim.get("type", "")),
                    money_abs(sim.get("profit", 0), field="profit"),
                    json.dumps(sim.get("payload", sim)),
                    int(sim.get("created_at", 0)),
                ),
            )
            self.conn.commit()

    def get_mev_simulations(self, limit: int = 100) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM mev_simulations ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            out = []
            for r in rows:
                payload = self._loads_json(r["payload"] or "{}", context="mev_sim", default={})
                out.append({
                    "sim_id": r["sim_id"],
                    "sim_type": r["sim_type"],
                    "profit": money_abs(r["profit"], field="profit"),
                    "payload": payload,
                    "created_at": r["created_at"],
                })
            return out

    # ── Reorg assessments (Wave 45 persistence) ─────────────────────────────

    def save_reorg_assessment(self, assess: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO reorg_assessments
                   (assess_id, kind, payload, created_at)
                   VALUES (?,?,?,?)""",
                (
                    assess["assess_id"],
                    assess.get("kind", ""),
                    json.dumps({k: v for k, v in assess.items() if k != "assess_id"}),
                    int(assess.get("timestamp", assess.get("created_at", 0))),
                ),
            )
            self.conn.commit()

    def get_reorg_assessments(self, limit: int = 100) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM reorg_assessments ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            out = []
            for r in rows:
                payload = self._loads_json(r["payload"] or "{}", context="reorg_assess", default={})
                out.append({
                    "assess_id": r["assess_id"],
                    "kind": r["kind"],
                    "timestamp": r["created_at"],
                    **(payload if isinstance(payload, dict) else {}),
                })
            return out

    # ── NFT marketplace (Wave 46 persistence) ─────────────────────────────────

    def save_nft_token(self, token: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT OR REPLACE INTO nft_tokens
                   (token_id, name, description, image_url, owner, creator,
                    price, for_sale, created_at, metadata)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    token["token_id"],
                    token.get("name", ""),
                    token.get("description", ""),
                    token.get("image_url", ""),
                    token.get("owner", ""),
                    token.get("creator", ""),
                    money_abs(token.get("price", 0), field="price"),
                    1 if token.get("for_sale") else 0,
                    int(token.get("created_at", 0)),
                    json.dumps(token.get("metadata") or {}),
                ),
            )
            self.conn.commit()

    def get_nft_tokens(self) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM nft_tokens ORDER BY created_at").fetchall()
            out = []
            for r in rows:
                meta = self._loads_json(r["metadata"] or "{}", context="nft_token_meta", default={})
                out.append({
                    "token_id": r["token_id"],
                    "name": r["name"],
                    "description": r["description"],
                    "image_url": r["image_url"],
                    "owner": r["owner"],
                    "creator": r["creator"],
                    "price": money_abs(r["price"], field="price"),
                    "for_sale": bool(r["for_sale"]),
                    "created_at": r["created_at"],
                    "metadata": meta,
                })
            return out

    def save_nft_offer(self, offer: Dict) -> None:
        with self.lock:
            payload = {k: v for k, v in offer.items() if k != "offer_id"}
            self.conn.execute(
                """INSERT OR REPLACE INTO nft_offers
                   (offer_id, token_id, bidder, price, expires_at, status, created_at, payload)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    offer["offer_id"],
                    offer.get("token_id", ""),
                    offer.get("bidder", ""),
                    money_abs(offer.get("price", 0), field="price"),
                    int(offer.get("expires_at", 0)),
                    offer.get("status", "pending"),
                    int(offer.get("created_at", 0)),
                    json.dumps(payload),
                ),
            )
            self.conn.commit()

    def get_nft_offers(self) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM nft_offers ORDER BY created_at DESC").fetchall()
            out = []
            for r in rows:
                payload = self._loads_json(r["payload"] or "{}", context="nft_offer", default={})
                row = {"offer_id": r["offer_id"], **(payload if isinstance(payload, dict) else {})}
                row["price"] = money_abs(r["price"], field="price")
                out.append(row)
            return out

    def save_nft_auction(self, auction: Dict) -> None:
        with self.lock:
            aid = auction["auction_id"]
            payload = {k: v for k, v in auction.items() if k != "auction_id"}
            for field in ("start_price", "reserve_price", "current_bid"):
                if field in payload and payload[field] is not None:
                    payload[field] = money_abs(payload[field], field=field)
            self.conn.execute(
                """INSERT OR REPLACE INTO nft_auctions
                   (auction_id, token_id, seller, status, ends_at, payload, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    aid,
                    auction.get("token_id", ""),
                    auction.get("seller", ""),
                    auction.get("status", "active"),
                    int(auction.get("ends_at", 0)),
                    json.dumps(payload),
                    int(auction.get("created_at", 0)),
                ),
            )
            self.conn.commit()

    def get_nft_auctions(self) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM nft_auctions ORDER BY created_at DESC").fetchall()
            out = []
            for r in rows:
                payload = self._loads_json(r["payload"] or "{}", context="nft_auction", default={})
                row = {"auction_id": r["auction_id"], **(payload if isinstance(payload, dict) else {})}
                for field in ("start_price", "reserve_price", "current_bid"):
                    if field in row and row[field] is not None:
                        row[field] = money_abs(row[field], field=field)
                out.append(row)
            return out

    def save_nft_sale(self, sale: Dict) -> None:
        with self.lock:
            self.conn.execute(
                """INSERT INTO nft_sales
                   (token_id, from_addr, to_addr, price, sale_type, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    sale.get("token_id", ""),
                    sale.get("from", sale.get("from_addr", "")),
                    sale.get("to", sale.get("to_addr", "")),
                    money_abs(sale.get("price", 0), field="price"),
                    sale.get("type", sale.get("sale_type", "buy")),
                    int(sale.get("timestamp", sale.get("created_at", 0))),
                ),
            )
            self.conn.commit()

    def get_nft_sales(self, limit: int = 100) -> List[Dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM nft_sales ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [
                {
                    "token_id": r["token_id"],
                    "from": r["from_addr"],
                    "to": r["to_addr"],
                    "price": money_abs(r["price"], field="price"),
                    "type": r["sale_type"],
                    "timestamp": r["created_at"],
                }
                for r in rows
            ]

    # ── Метаданные (токеномика, конфиг) ─────────────────────────────────────

    def set_meta(self, key: str, value: Any) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            self.conn.commit()

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self.lock:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)
            ).fetchone()
            if not row:
                return default
            raw = row["value"]
            try:
                return json.loads(raw)
            except Exception as exc:
                text = raw if isinstance(raw, str) else str(raw or "")
                stripped = text.strip()
                # Corrupt JSON object/array/string → fail-closed default.
                # Legacy plain-string meta is not JSON.
                if stripped[:1] in "{\"[":
                    self._json_decode_failures += 1
                    logger.warning(
                        "[DB] corrupt meta %s (decode_failures=%s): %s",
                        key,
                        self._json_decode_failures,
                        exc,
                    )
                    return default
                return text if text else default

    def get_cached_total_supply(self) -> Optional[float]:
        """Poll path must not SUM accounts. SQLite has no O(1) supply meta."""
        return None

    def get_cached_total_burned(self) -> Optional[float]:
        """Poll path: last burn_stats row only. None if the table is empty."""
        from runtime.amount import money_abs

        with self.lock:
            row = self.conn.execute(
                "SELECT total_burned FROM burn_stats ORDER BY block_height DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            return money_abs(row["total_burned"] if row else 0, field="total_burned")

    def get_total_supply(self) -> float:
        """Sum of account balances (prefer satoshi column when present)."""
        from runtime.amount import from_satoshi_float

        with self.lock:
            row = self.conn.execute(
                """SELECT COALESCE(SUM(
                       CASE WHEN balance_satoshi IS NOT NULL THEN balance_satoshi
                            ELSE CAST(ROUND(balance * 1000000) AS INTEGER) END
                   ), 0) as total_sat FROM accounts"""
            ).fetchone()
            total_sat = int(row["total_sat"] if row else 0)
            return from_satoshi_float(total_sat)

    # ── Статистика ───────────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        with self.lock:
            height = self.get_chain_tip()
            tx_count = self.conn.execute(
                "SELECT COUNT(*) as c FROM transactions"
            ).fetchone()["c"]
            account_count = self.conn.execute(
                "SELECT COUNT(*) as c FROM accounts"
            ).fetchone()["c"]
            return {
                "height": height,
                "total_transactions": tx_count,
                "total_accounts": account_count,
                "total_burned": self.get_total_burned(),
                "total_supply": self.get_total_supply(),
                "engine": self.engine,
                "json_decode_failures": int(self._json_decode_failures),
            }

    # ── Утилиты ──────────────────────────────────────────────────────────────

    def backup_to(self, dest_path: str) -> bool:
        """Online-бэкап SQLite через встроенный backup API."""
        with self.lock:
            dest_dir = os.path.dirname(dest_path)
            if dest_dir:
                os.makedirs(dest_dir, exist_ok=True)
            try:
                dest = sqlite3.connect(dest_path)
                self.conn.backup(dest)
                dest.close()
                return True
            except Exception as e:
                print(f"[DB] backup_to error: {e}")
                return False

    def close(self):
        with self.lock:
            conn = getattr(self, "conn", None)
            if conn is None:
                return
            try:
                conn.close()
            finally:
                self.conn = None


class BlockchainDB(Database):
    """Legacy API used by v47 tests."""

    def __del__(self):
        try:
            self.close()
        except Exception as exc:
            logger.warning("BlockchainDB.__del__ close failed: %s", exc)

    def get_latest_block_number(self) -> int:
        return self.get_chain_tip()

    def get_block(self, block_hash: str) -> Optional[Dict]:
        return self.get_block_by_hash(block_hash)

    def save_metadata(self, key: str, value: Any) -> None:
        self.set_meta(key, value)

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self.get_meta(key, default)

    def get_stats(self) -> Dict:
        stats = super().get_stats()
        stats["total_blocks"] = stats.get("height", 0)
        return stats
