#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Absolute Blockchain — ядро цепочки блоков.

Содержит:
  - Transaction     : структура транзакции (c ECDSA подписью)
  - Block           : структура блока (c state_root + canonical hash)
  - Blockchain      : основная логика (burn mechanism, StateEngine, BlockValidator)

Интегрирует из всех трёх систем:
  - System A: Transaction/Block/burn/genesis (основа)
  - System C: StateEngine (детерминированный state_root)
  - blockchain/canonical_serializer.py: детерминированный хэш блока
  - execution/block_validator.py: валидация блоков из P2P
"""

import json
import time
import threading
import logging
from typing import List, Dict, Optional, Any

from crypto import native
from storage.database import Database
from storage.factory import open_storage
from storage.ports import StoragePort
from storage.types import StorageError, TipMeta
from runtime.config import Config
from runtime.tokenomics import genesis_balances, get_tokenomics_summary, MAX_SUPPLY_ABS
from kernel.event_bus import EventBus
from execution.state_root import compute_db_state_root
from core.components import (
    NullZkGateway,
    StateService,
    TxPipeline,
    build_zk_gateway,
)

_logger = logging.getLogger("Blockchain")

# --- System C: StateEngine (детерминированные state transitions) ---
try:
    from execution.state_engine import StateEngine
    _STATE_ENGINE_AVAILABLE = True
except ImportError:
    _STATE_ENGINE_AVAILABLE = False

# --- CanonicalSerializer (детерминированный хэш) ---
try:
    from blockchain.canonical_serializer import CanonicalSerializer
    _CANONICAL_AVAILABLE = True
except ImportError:
    _CANONICAL_AVAILABLE = False

# --- BlockValidator (валидация P2P-блоков) ---
try:
    from execution.block_validator import BlockValidator
    _BLOCK_VALIDATOR_AVAILABLE = True
except ImportError:
    _BLOCK_VALIDATOR_AVAILABLE = False


# ── Структуры данных ─────────────────────────────────────────────────────────

class Transaction:
    """Транзакция в сети Absolute (с поддержкой ECDSA-подписи)."""

    def __init__(
        self,
        from_addr: str,
        to_addr: str,
        value: float,
        nonce: int = 0,
        gas: int = 21_000,
        data: str = "",
        tx_hash: str = "",
        signature: str = "",
        public_key: str = "",
        timestamp: int = 0,
    ):
        self.from_addr = from_addr
        self.to_addr = to_addr
        self.value = value
        self.nonce = nonce
        self.gas = gas
        self.data = data
        self.signature = signature
        self.public_key = public_key
        self.timestamp = timestamp or int(time.time())
        self.hash = tx_hash or self._compute_hash()

        # Заполняется при включении в блок
        self.block_height: int = 0
        self.gas_used: int = gas
        self.fee: float = 0.0
        self.burned: float = 0.0
        # Receipt status: set to 1 only after successful apply (omit → fail-closed 0).
        self.status: Optional[int] = None

    def _compute_hash(self) -> str:
        raw = f"{self.from_addr}{self.to_addr}{self.value}{self.nonce}{self.gas}{self.data}{self.timestamp}"
        return native.transaction_hash(
            self.from_addr,
            self.to_addr,
            self.value,
            self.nonce,
            self.gas,
            self.data,
            self.timestamp,
        )

    def to_dict(self) -> Dict:
        out = {
            "hash": self.hash,
            "from_addr": self.from_addr,
            "to_addr": self.to_addr,
            "value": self.value,
            "nonce": self.nonce,
            "gas": self.gas,
            "gas_used": self.gas_used,
            "fee": self.fee,
            "burned": self.burned,
            "data": self.data,
            "signature": self.signature,
            "public_key": self.public_key,
            "timestamp": self.timestamp,
            "block_height": self.block_height,
        }
        if self.status is not None:
            out["status"] = int(self.status)
        return out

    @classmethod
    def from_dict(cls, d: Dict) -> "Transaction":
        from runtime.amount import parse_rpc_value_abs

        tx = cls(
            from_addr=d.get("from_addr", d.get("from", "")),
            to_addr=d.get("to_addr", d.get("to", "")),
            value=parse_rpc_value_abs(d.get("value", d.get("amount", 0)), field="value"),
            nonce=int(d.get("nonce", 0)),
            gas=int(d.get("gas", 21_000)),
            data=d.get("data", d.get("tx_data", "")),
            tx_hash=d.get("hash", d.get("tx_hash", "")),
            signature=d.get("signature", ""),
            public_key=d.get("public_key", ""),
            timestamp=int(d.get("timestamp", 0)),
        )
        tx.fee = parse_rpc_value_abs(d.get("fee", 0.0), field="fee")
        tx.burned = parse_rpc_value_abs(d.get("burned", 0.0), field="burned")
        tx.block_height = int(d.get("block_height", 0))
        if "status" in d and d.get("status") is not None:
            tx.status = int(d.get("status"))
        return tx

    def __repr__(self) -> str:
        return f"Tx({self.hash[:10]}... {self.from_addr[:8]}->{self.to_addr[:8]} {self.value} ABS)"


class Block:
    """Блок в цепочке Absolute (с state_root и canonical hash)."""

    def __init__(
        self,
        height: int,
        parent_hash: str,
        miner: str,
        transactions: Optional[List[Transaction]] = None,
        timestamp: int = 0,
        block_hash: str = "",
        extra_data: str = "",
        state_root: str = "",
    ):
        self.height = height
        self.parent_hash = parent_hash
        self.miner = miner
        self.transactions: List[Transaction] = transactions or []
        self.timestamp = timestamp or int(time.time())
        self.extra_data = extra_data
        self.state_root = state_root  # deterministic state root (System C)
        self.tx_root = self._compute_tx_root()

        # Вычисляемые поля
        self.tx_count = len(self.transactions)
        self.gas_used: int = sum(tx.gas_used for tx in self.transactions)
        self.total_burned: float = sum(tx.burned for tx in self.transactions)

        self.hash = block_hash or self._compute_hash()

    def _compute_tx_root(self) -> str:
        """Merkle root транзакций блока (для SPV / light client)."""
        from crypto.merkle import merkle_root

        items = [tx.hash for tx in self.transactions] if self.transactions else []
        return merkle_root(items) if items else merkle_root(["empty"])

    def _compute_hash(self) -> str:
        """Детерминированный хэш блока через CanonicalSerializer."""
        if not _CANONICAL_AVAILABLE:
            raise RuntimeError("canonical block hash unavailable (CanonicalSerializer missing)")
        block_dict = {
            "height": self.height,
            "parent_hash": self.parent_hash,
            "miner": self.miner,
            "timestamp": self.timestamp,
            "extra_data": self.extra_data,
            "state_root": self.state_root,
            "transactions": [
                {"hash": tx.hash, "from": tx.from_addr, "to": tx.to_addr,
                 "amount": tx.value, "fee": tx.fee, "nonce": tx.nonce,
                 "timestamp": tx.timestamp}
                for tx in sorted(self.transactions, key=lambda t: t.hash)
            ],
        }
        return native.block_canonical_hash(block_dict)

    def to_dict(self) -> Dict:
        return {
            "height": self.height,
            "hash": self.hash,
            "parent_hash": self.parent_hash,
            "miner": self.miner,
            "timestamp": self.timestamp,
            "tx_count": self.tx_count,
            "gas_used": self.gas_used,
            "total_burned": self.total_burned,
            "extra_data": self.extra_data,
            "state_root": self.state_root,
            "tx_root": self.tx_root,
            "transactions": [tx.to_dict() for tx in self.transactions],
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Block":
        txs = [Transaction.from_dict(t) for t in d.get("transactions", [])]
        blk = cls(
            height=int(d.get("height", d.get("number", 0))),
            parent_hash=d.get("parent_hash", "0" * 64),
            miner=d.get("miner", d.get("proposer", "")),
            transactions=txs,
            timestamp=d.get("timestamp", 0),
            block_hash=d.get("hash", d.get("block_hash", "")),
            extra_data=d.get("extra_data", ""),
            state_root=d.get("state_root", ""),
        )
        blk.total_burned = float(d.get("total_burned", 0.0))
        return blk

    def __repr__(self) -> str:
        return (
            f"Block(#{self.height} hash={self.hash[:10]}... "
            f"txs={self.tx_count} burned={self.total_burned:.4f})"
        )


# ── Основная логика ───────────────────────────────────────────────────────────

class Blockchain:
    """
    Ядро блокчейна: создание/добавление блоков, применение транзакций,
    механизм сжигания, genesis.

    Включает:
    - StateEngine (System C) для детерминированного state_root
    - BlockValidator (System C) для валидации P2P-блоков
    - CanonicalSerializer для детерминированного хэша
    """

    GENESIS_HASH = "0" * 64

    def __init__(
        self,
        config: Config,
        db: Optional[Database] = None,
        bus: Optional[EventBus] = None,
        storage: Optional[StoragePort] = None,
    ):
        self.config = config
        try:
            from runtime.state_root_encoding import bind_tip_encoding_config

            bind_tip_encoding_config(config)
        except Exception as exc:
            _logger.error("bind_tip_encoding_config failed: %s", exc)
            mode = str(getattr(config, "deployment_mode", "") or "").lower()
            if bool(getattr(config, "is_production", False)) or mode in (
                "prod",
                "production",
            ):
                raise
        self.bus = bus
        if storage is None:
            if db is None:
                raise ValueError("Blockchain requires storage= or db=")
            storage = open_storage(db)
        self.storage: StoragePort = storage
        self.lock = threading.RLock()
        self.require_signatures = False

        # --- System C: StateEngine ---
        if _STATE_ENGINE_AVAILABLE:
            self.state_engine = StateEngine()
            self._init_state_engine()
            print("[Blockchain] StateEngine: enabled (deterministic state_root)")
        else:
            self.state_engine = None

        # --- System C: BlockValidator ---
        if _BLOCK_VALIDATOR_AVAILABLE and self.state_engine:
            self.block_validator = BlockValidator(self.state_engine, None)
            print("[Blockchain] BlockValidator: enabled")
        else:
            self.block_validator = None

        self.pool_locks = None  # runtime.pool_locks.PoolLockManager
        self.consensus_adapter = None  # wired from main.NodeOrchestrator
        self.evm = None  # execution.evm_adapter.EVMAdapter
        self._state_root_baseline = 0

        # Facade components (validation / state / ZK) — ADR sprint decomposition
        self.zk_gateway = NullZkGateway()
        self.tx_pipeline = TxPipeline(
            config=self.config,
            storage=self.storage,
            zk_gateway=self.zk_gateway,
            get_pool_locks=lambda: self.pool_locks,
            get_evm=lambda: self.evm,
        )
        self.state_service = StateService(self)

        # ADR 0010 — L1 bridge port (DI only; no tip/UoW coupling)
        from bridge.ports import NullBridgePort

        self.bridge = NullBridgePort()

        # ADR 0011 — query façade for API reads (DI only)
        from api.ports import NullQueryFacade

        self.query_facade = NullQueryFacade()

        self._ensure_genesis()
        h = self.get_height()
        cutoff = int(getattr(self.config, "state_root_legacy_cutoff_height", 0) or 0)
        self._state_root_baseline = max(cutoff, h)

    def attach_bridge(self, port) -> None:
        """Wire optional L1 BridgePort (NodeOrchestrator owns start/stop lifecycle)."""
        from bridge.ports import NullBridgePort

        self.bridge = port if port is not None else NullBridgePort()

    def attach_query_facade(self, port) -> None:
        """Wire QueryFacadePort for RPC/REST reads (ADR 0011)."""
        from api.ports import NullQueryFacade

        self.query_facade = port if port is not None else NullQueryFacade()

    def attach_zk_system(self, system, *, enabled: bool = True) -> None:
        """Wire optional ZKProofSystem into the facade (called from NodeOrchestrator)."""
        self.zk_gateway = build_zk_gateway(system, enabled=enabled)
        self.tx_pipeline.zk_gateway = self.zk_gateway

    @property
    def db(self):
        """Deprecated compat façade for API/P2P/tests — underlying store via unwrap()."""
        unwrap = getattr(self.storage, "unwrap", None)
        if callable(unwrap):
            return unwrap()
        return self.storage

    @db.setter
    def db(self, value: Any) -> None:
        """Allow tests to swap the underlying store; re-wrap as StoragePort."""
        if value is None:
            raise ValueError("db cannot be None")
        if hasattr(value, "unwrap") and hasattr(value, "begin_block_commit"):
            self.storage = value
        else:
            self.storage = open_storage(value, repair_on_open=False)
        if getattr(self, "tx_pipeline", None) is not None:
            self.tx_pipeline.storage = self.storage

    def _native_apply_fail_closed(self) -> bool:
        """Prod / require_native_crypto: never silently fall back after native apply failure."""
        if bool(getattr(self.config, "require_native_crypto", False)):
            return True
        mode = str(getattr(self.config, "deployment_mode", "dev") or "dev").lower()
        return mode in ("prod", "production")

    def _init_state_engine(self):
        """Инициализирует StateEngine из данных genesis или текущего состояния БД."""
        if not self.state_engine:
            return
        # Followers must not mint a local alloc root — wait for leader genesis
        # import so wire state_root matches the mesh tip.
        if (
            getattr(self.config, "follower_genesis_sync", False)
            and self.storage.get_last_block() is None
        ):
            return
        founder = (
            getattr(self.config, "founder_address", "")
            or self.config.miner_address
            or ""
        )
        genesis_alloc = genesis_balances(founder or None)
        if self.config.miner_address and self.config.miner_address not in genesis_alloc:
            genesis_alloc[self.config.miner_address] = int(
                getattr(self.config, "min_stake", 1000)
            )
        self.state_engine.create_genesis(genesis_alloc)

    # ── Genesis ──────────────────────────────────────────────────────────────

    def _ensure_genesis(self):
        if getattr(self.config, "follower_genesis_sync", False) and self.storage.get_last_block() is None:
            # Prefer shared ceremony artifact before waiting on unstable P2P wire.
            if self.try_import_genesis_artifact():
                return
            print("[Blockchain] follower_genesis_sync: waiting for leader genesis via P2P")
            return
        if self.storage.get_last_block() is None:
            founder = self._resolve_genesis_founder()
            alloc = genesis_balances(founder or None)
            initials = getattr(self.config, "founder_initials", "D.U.P.")
            total_minted = 0
            for addr, amount in alloc.items():
                amount_abs = int(amount)
                self.storage.set_balance(addr, amount_abs)
                total_minted += amount_abs
            state_root = self._compute_state_root_from_db()
            genesis = Block(
                height=0,
                parent_hash=self.GENESIS_HASH,
                miner="genesis",
                timestamp=self.config.resolve_genesis_timestamp(),
                extra_data=(
                    f"{self.config.network_name} Genesis | "
                    f"max_supply={MAX_SUPPLY_ABS:,} ABS | founder={initials} {self.config.founder_percent}%"
                ),
                state_root=state_root,
            )
            genesis.hash = genesis._compute_hash()
            self.storage.save_block(genesis.to_dict())
            try:
                self.storage.set_meta("tokenomics", get_tokenomics_summary(founder or None))
                self.storage.set_meta("genesis_alloc_applied", True)
                self.storage.set_meta("genesis_founder", founder)
            except Exception as _gen_meta_err:
                print(f"[Blockchain] genesis meta write failed: {_gen_meta_err}")
                if getattr(self.config, "is_production", False):
                    raise
            print(
                f"[Blockchain] Genesis block created "
                f"(minted={total_minted:,.0f} {self.config.coin_symbol}, "
                f"max_supply={MAX_SUPPLY_ABS:,}, founder={initials} "
                f"{getattr(self.config, 'founder_percent', 17.4)}%)"
            )
            self._export_genesis_artifact(genesis.to_dict())
        else:
            self._align_genesis_state_root_if_needed()
            # Re-publish artifact for followers when shared file is missing/stale.
            try:
                last = self.storage.get_block(0) or self.storage.get_last_block()
                if last and int(last.get("height", last.get("number", -1)) or -1) == 0:
                    self._export_genesis_artifact(last)
            except Exception as exc:
                print(f"[Blockchain] genesis artifact re-export skipped: {exc}")

    def _export_genesis_artifact(self, block_dict: Dict) -> None:
        """Publish minted genesis #0 to shared ceremony artifact path (followers)."""
        try:
            from sync.genesis_artifact import export_genesis_block, resolve_artifact_path

            path = resolve_artifact_path(self.config)
            if not path:
                return
            ceremony_hash = ""
            try:
                import os

                ceremony_hash = str(os.environ.get("GENESIS_CEREMONY_HASH", "") or "")
            except Exception:
                ceremony_hash = ""
            founder = ""
            try:
                founder = str(self.storage.get_meta("genesis_founder") or "").strip()
            except Exception as exc:
                print(f"[Blockchain] genesis_founder meta read failed: {exc}")
                founder = ""
            if not founder:
                founder = self._resolve_genesis_founder()
            if export_genesis_block(
                path,
                block_dict,
                ceremony_hash=ceremony_hash,
                chain_id=int(getattr(self.config, "chain_id", 0) or 0),
                founder_address=founder,
            ):
                print(f"[Blockchain] genesis artifact exported → {path}")
        except Exception as exc:
            print(f"[Blockchain] genesis artifact export skipped: {exc}")

    def try_import_genesis_artifact(self) -> bool:
        """Empty-tip follower: import genesis #0 from shared ceremony artifact."""
        if self.storage.get_last_block() is not None:
            return True
        try:
            from sync.genesis_artifact import load_genesis_artifact, resolve_artifact_path

            path = resolve_artifact_path(self.config)
            art = load_genesis_artifact(path) if path else None
            if not art:
                return False
            founder = str(art.get("founder_address") or "").strip()
            if not founder:
                try:
                    from runtime.validator_loader import manifest_founder_address

                    manifest = getattr(self.config, "validators_manifest_path", "") or ""
                    founder = manifest_founder_address(manifest)
                except Exception as exc:
                    print(f"[Blockchain] manifest founder resolve failed: {exc}")
                    founder = ""
            if founder:
                try:
                    self.config.founder_address = founder
                except Exception as exc:
                    print(f"[Blockchain] founder_address bind failed: {exc}")
                try:
                    self.storage.set_meta("genesis_founder", founder)
                except Exception as exc:
                    print(f"[Blockchain] genesis_founder meta write failed: {exc}")
                    if getattr(self.config, "is_production", False):
                        raise
            print(f"[Blockchain] importing genesis from artifact {path}")
            return bool(self.import_block(art["block"]))
        except Exception as exc:
            print(f"[Blockchain] genesis artifact import failed: {exc}")
            return False

    def _resolve_genesis_founder(self) -> str:
        """Same founder resolution as _ensure_genesis (replay must match mint)."""
        return (
            getattr(self.config, "founder_address", "")
            or self.config.miner_address
            or ""
        )

    def _pinned_genesis_founder(self) -> str:
        """Founder used when genesis was minted — must not follow per-node wallets."""
        try:
            pinned = self.storage.get_meta("genesis_founder")
            if pinned:
                return str(pinned).strip()
        except Exception as exc:
            _logger.debug("genesis_founder meta read failed: %s", exc)
        try:
            tok = self.storage.get_meta("tokenomics")
            if isinstance(tok, dict):
                addr = str((tok.get("founder") or {}).get("address", "") or "").strip()
                if addr:
                    return addr
        except Exception as exc:
            _logger.debug("tokenomics founder meta read failed: %s", exc)
        manifest = getattr(self.config, "validators_manifest_path", "") or ""
        if manifest:
            try:
                from runtime.validator_loader import manifest_founder_address

                addr = manifest_founder_address(manifest)
                if addr:
                    return addr
            except Exception as exc:
                _logger.debug("manifest founder resolve failed: %s", exc)
        return self._resolve_genesis_founder()

    def _align_block_state_root_metadata(self, height: int, state_root: str) -> bool:
        """Repair stale state_root/hash when live account state is already canonical.

        Prod fail-closed: refuse rewrites above genesis (height 0) unless
        ``allow_state_root_rewrite`` is explicitly enabled (dev/recovery only).
        """
        h = int(height)
        allow = bool(getattr(self.config, "allow_state_root_rewrite", False))
        is_prod = bool(getattr(self.config, "is_production", False))
        if is_prod and h > 0 and not allow:
            live = str(state_root or "").strip()
            print(
                f"[Blockchain] REFUSED state_root rewrite at #{h} "
                f"(prod fail-closed; live={live[:16]}…)"
            )
            return False
        blk = self.storage.get_block(h)
        if not blk:
            return False
        live = str(state_root or "").strip()
        if not live or str(blk.get("state_root") or "").strip() == live:
            return True
        row = dict(blk)
        row["state_root"] = live
        block = Block.from_dict(row)
        row["hash"] = block._compute_hash()
        self.storage.save_block(row)
        print(f"[Blockchain] Block #{h} state_root aligned ({live[:16]}…)")
        return True

    def _sync_tip_state_root_metadata(self) -> bool:
        """Ensure tip block header state_root matches live DB (metadata only)."""
        h = self.get_height()
        if h < 0:
            return True
        live = str(self._compute_state_root_from_db() or "").strip()
        if not live:
            return True
        blk = self.storage.get_block(h)
        if not blk:
            return True
        if str(blk.get("state_root") or "").strip() == live:
            return True
        return self._align_block_state_root_metadata(h, live)

    def _align_genesis_state_root_if_needed(self) -> None:
        """Fix genesis header when tip is still 0 (minted state vs empty state_root)."""
        if self.get_height() != 0:
            return
        blk = self.storage.get_block(0)
        if not blk:
            return
        live = self._compute_state_root_from_db()
        if (blk.get("state_root") or "") == live:
            return
        self._align_block_state_root_metadata(0, live)

    def set_state_root_baseline(self, height: int) -> None:
        """Blocks at or below baseline may use legacy warn-on-drift on P2P import."""
        self._state_root_baseline = int(height)

    def _state_root_check_mode(
        self, block_height: int, peer_root: str, preserve_peer: bool
    ) -> str:
        """Returns strict | legacy_warn | skip for peer state_root verification."""
        if not getattr(self.config, "verify_peer_state_root", True):
            return "skip"
        peer_root = str(peer_root or "").strip()
        if not peer_root:
            return "skip"
        if len(peer_root) < 64:
            return "legacy_warn"
        if preserve_peer:
            if getattr(self.config, "state_root_strict_p2p", True):
                if block_height <= self._state_root_baseline:
                    return "legacy_warn"
                return "strict"
            return "legacy_warn"
        if block_height <= self._state_root_baseline:
            return "legacy_warn"
        return "strict"

    def get_state_root_policy(self) -> Dict:
        from runtime.state_root_encoding import state_root_encoding_status

        return {
            "verify_peer_state_root": bool(
                getattr(self.config, "verify_peer_state_root", True)
            ),
            "state_root_strict_p2p": bool(
                getattr(self.config, "state_root_strict_p2p", True)
            ),
            "legacy_cutoff_height": int(
                getattr(self.config, "state_root_legacy_cutoff_height", 0) or 0
            ),
            "baseline_height": int(self._state_root_baseline),
            "policy": (
                "strict_p2p"
                if getattr(self.config, "state_root_strict_p2p", True)
                else "legacy_warn"
            ),
            "encoding": state_root_encoding_status(self.config),
        }

    # ── Создание блока ───────────────────────────────────────────────────────

    def create_block(self, transactions: List[Transaction], proposer: str) -> Block:
        """Собирает новый блок: валидирует txs, state применяется в add_block()."""
        with self.lock:
            last = self.storage.get_last_block()
            height = last["height"] + 1 if last else 1
            parent_hash = last["hash"] if last else self.GENESIS_HASH

            applied_txs = []
            nonce_cursor: Dict[str, int] = {}

            for tx in transactions:
                check = self._validate_tx_for_block(tx, nonce_cursor)
                if check["valid"]:
                    applied_txs.append(tx)
                    nonce_cursor[tx.from_addr] = tx.nonce + 1

            parent_ts = int(last["timestamp"]) if last else 0
            block_ts = max(int(time.time()), parent_ts + 1)

            return Block(
                height=height,
                parent_hash=parent_hash,
                miner=proposer,
                transactions=applied_txs,
                timestamp=block_ts,
                extra_data=f"v{self.config.node_version}",
            )

    # ── Canonical persist via StoragePort UoW (ADR 0006 D–E) ─────────────────

    def _persist_canonical_via_storage(
        self,
        block: "Block",
        tx_dicts: List[Dict],
        *,
        expected_parent: str,
        expected_tip_height: int,
    ) -> None:
        """Stage block + txs + tip through StoragePort; join open ``db.atomic()`` batch.

        Account mutations already applied via ``balance_delta`` / native apply inside
        the same outer atomic — UoW does not re-write state deltas here.
        Raises ``StorageError`` subclasses on CAS / disk / engine failure.
        """
        uow = self.storage.begin_block_commit(
            expected_parent=str(expected_parent or ""),
            expected_tip_height=int(expected_tip_height),
        )
        try:
            uow.write_block(block.to_dict())
            uow.write_transactions(list(tx_dicts or []))
            uow.set_tip(
                TipMeta(
                    height=int(block.height),
                    head_hash=str(block.hash or ""),
                    state_root=str(getattr(block, "state_root", "") or ""),
                )
            )
            uow.commit()
        except StorageError:
            try:
                uow.abort()
            except Exception as abort_exc:
                print(f"[Blockchain] UoW abort failed after StorageError: {abort_exc}")
            raise
        except Exception as persist_exc:
            print(f"[Blockchain] canonical persist failed: {persist_exc}")
            try:
                uow.abort()
            except Exception as abort_exc:
                print(f"[Blockchain] UoW abort failed after persist error: {abort_exc}")
            raise

    # ── Добавление блока ─────────────────────────────────────────────────────

    def add_block(self, block: Block, preserve_peer_hash: bool = False) -> bool:
        """Валидирует, выполняет все txs + reward атомарно, сохраняет в БД."""
        peer_hash = block.hash if preserve_peer_hash else None
        with self.lock:
            if self.storage.get_block(block.height):
                return False

            validation = self._validate_block_structure(block)
            if not validation["valid"]:
                print(f"[Blockchain] Reject block #{block.height}: {validation.get('error')}")
                return False

            proposer_check = self._verify_block_proposer(
                block, allow_slashed=bool(preserve_peer_hash)
            )
            if not proposer_check["valid"]:
                print(f"[Blockchain] Reject block #{block.height}: {proposer_check.get('error')}")
                return False

            signature_check = self._verify_block_tx_signatures(block)
            if not signature_check["valid"]:
                print(f"[Blockchain] Reject block #{block.height}: {signature_check.get('error')}")
                return False

            peer_state_root = block.state_root if preserve_peer_hash and block.state_root else None
            slashing = self._resolve_slashing_core()
            computed_root = None
            peer_root_for_audit = None

            last_before = self.storage.get_last_block()
            if last_before:
                expected_parent = str(last_before.get("hash") or "")
                expected_tip_height = int(last_before.get("height") or 0)
            else:
                expected_parent = str(block.parent_hash or self.GENESIS_HASH)
                expected_tip_height = 0

            try:
                with self.storage.atomic():
                    # Leader ``_ensure_genesis`` mints alloc balances and saves the
                    # block without ``apply_block_mutations`` / block reward. Followers
                    # seed the same alloc then must not credit miner="genesis".
                    skip_mutations = (
                        bool(preserve_peer_hash)
                        and int(block.height) == 0
                        and not list(block.transactions or [])
                        and str(block.miner or "") == "genesis"
                    )
                    if skip_mutations:
                        block_burned = 0.0
                    else:
                        applied = self.state_service.apply_block_mutations(
                            block, preserve_peer_hash=preserve_peer_hash
                        )
                        if not applied.success:
                            raise RuntimeError(applied.error or "state_apply_failed")
                        # ApplyBlockResult.burned is satoshi; block.total_burned stays ABS display.
                        from runtime.amount import from_satoshi_float

                        block_burned = float(from_satoshi_float(int(applied.burned or 0)))

                    block.total_burned = block_burned
                    # Always via facade method so monkeypatches (tests) apply.
                    computed_root = self._compute_state_root_from_db()
                    if peer_state_root:
                        mode = self._state_root_check_mode(
                            block.height, peer_state_root, preserve_peer_hash
                        )
                        peer_root = str(peer_state_root).strip()
                        if mode != "skip" and peer_root != computed_root:
                            if mode == "strict" or skip_mutations:
                                peer_root_for_audit = peer_root
                                raise RuntimeError(
                                    f"state_root_mismatch expected={peer_root[:16]} "
                                    f"computed={computed_root[:16]}"
                                )
                            print(
                                f"[Blockchain] WARN #{block.height} state_root drift "
                                f"(peer={peer_root[:12]}… computed={computed_root[:12]}…) — legacy"
                            )
                    if skip_mutations and peer_state_root:
                        block.state_root = str(peer_state_root).strip()
                    else:
                        block.state_root = computed_root
                    canonical_hash = block._compute_hash()
                    if peer_hash:
                        if peer_hash != canonical_hash:
                            raise RuntimeError(
                                f"block_hash_mismatch expected={peer_hash[:16]} "
                                f"computed={canonical_hash[:16]}"
                            )
                        block.hash = peer_hash
                    else:
                        block.hash = canonical_hash

                    if slashing and block.miner and block.miner != "genesis":
                        if not slashing.record_proposal(block.miner, block.height, block.hash):
                            raise RuntimeError("double_proposal")

                    tx_dicts = []
                    for tx in block.transactions:
                        tx.block_height = block.height
                        tx_dicts.append(tx.to_dict())

                    self._persist_canonical_via_storage(
                        block,
                        tx_dicts,
                        expected_parent=expected_parent,
                        expected_tip_height=expected_tip_height,
                    )
            except Exception as e:
                if (
                    peer_root_for_audit
                    and computed_root
                    and hasattr(self.storage, "record_state_root_mismatch")
                ):
                    try:
                        self.storage.record_state_root_mismatch(
                            block.height,
                            peer_root_for_audit,
                            computed_root,
                            source="p2p" if preserve_peer_hash else "local",
                            proposer=block.miner,
                        )
                    except Exception as _mismatch_err:
                        print(
                            f"[Blockchain] record_state_root_mismatch failed "
                            f"#{block.height}: {_mismatch_err}"
                        )
                print(f"[Blockchain] Block execution failed #{block.height}: {e}")
                return False

            if self.bus:
                self.bus.emit("block.new", block.to_dict())
            return True

    def _seed_follower_genesis_balances(self, peer_block: Dict) -> None:
        """Seed empty-tip balances so imported genesis #0 replays to peer state_root/hash.

        Leader mints balances in ``_ensure_genesis`` (not as txs). Followers must
        apply the same alloc before ``add_block(..., preserve_peer_hash=True)``.
        Never use the local validator wallet as founder — that diverges state_root.
        """
        if self.storage.get_last_block() is not None:
            return
        founder = ""
        # Prefer founder embedded by leader export / pin / ceremony manifest.
        try:
            founder = str(self.storage.get_meta("genesis_founder") or "").strip()
        except Exception as exc:
            print(f"[Blockchain] genesis_founder meta read failed: {exc}")
            founder = ""
        if not founder:
            try:
                from runtime.validator_loader import manifest_founder_address

                manifest = getattr(self.config, "validators_manifest_path", "") or ""
                founder = manifest_founder_address(manifest)
            except Exception as exc:
                print(f"[Blockchain] manifest founder resolve failed: {exc}")
                founder = ""
        if not founder and not getattr(self.config, "follower_genesis_sync", False):
            founder = str(getattr(self.config, "founder_address", "") or "").strip()
            if not founder:
                founder = self._resolve_genesis_founder()
        alloc = genesis_balances(founder or None)
        for addr, amount in alloc.items():
            self.storage.set_balance(addr, int(amount))
        try:
            self.storage.set_meta("genesis_founder", founder or "")
            self.storage.set_meta("tokenomics", get_tokenomics_summary(founder or None))
            self.storage.set_meta("genesis_alloc_applied", True)
        except Exception as exc:
            print(f"[Blockchain] genesis seed meta failed: {exc}")
        peer_root = str(peer_block.get("state_root") or "").strip()
        computed = self._compute_state_root_from_db()
        if peer_root and computed != peer_root:
            print(
                f"[Blockchain] genesis seed state_root still mismatches "
                f"(founder={(founder or '')[:12]}… peer={peer_root[:16]} "
                f"local={computed[:16]})"
            )

    def import_block(self, block_dict: Dict) -> bool:
        """Импортирует блок от P2P-пира с полным replay состояния."""
        normalized = self._normalize_block_dict(block_dict)
        height = int(normalized.get("height", normalized.get("number", 0)))
        with self.lock:
            existing = self.storage.get_block(height)
            if existing and height == 0 and existing.get("hash") != normalized.get("hash"):
                self.storage.truncate_all_blocks()
            elif existing:
                return False

            if self.block_validator:
                last = self.storage.get_last_block()
                valid, msg = self.block_validator.validate_block(
                    normalized, last, strict_timestamp=False
                )
                if not valid:
                    print(f"[Blockchain] import_block rejected: {msg}")
                    return False

            last = self.storage.get_last_block()
            expected_parent = last["hash"] if last else self.GENESIS_HASH
            start_height = last["height"] if last else -1
            if not native.validate_imported_block_chain(
                [normalized], expected_parent, start_height
            ):
                print("[Blockchain] import_block rejected: invalid peer hash/parent chain")
                return False

            if height == 0 and last is None:
                self._seed_follower_genesis_balances(normalized)

            try:
                return self.add_block(Block.from_dict(normalized), preserve_peer_hash=True)
            except Exception as e:
                print(f"[Blockchain] import_block error: {e}")
                return False

    def _normalize_block_dict(self, block_dict: Dict) -> Dict:
        b = dict(block_dict)
        if "height" not in b and "number" in b:
            b["height"] = b["number"]
        if "miner" not in b and "proposer" in b:
            b["miner"] = b["proposer"]
        txs = []
        for tx in b.get("transactions", []):
            t = dict(tx)
            if "from_addr" not in t and "from" in t:
                t["from_addr"] = t["from"]
            if "to_addr" not in t and "to" in t:
                t["to_addr"] = t["to"]
            if "value" not in t and "amount" in t:
                t["value"] = t["amount"]
            txs.append(t)
        b["transactions"] = txs
        return b

    def _validate_tx_for_block(self, tx: Transaction, nonce_cursor: Dict[str, int]) -> Dict:
        return self.tx_pipeline.validate_for_block_cursor(tx, nonce_cursor).as_dict()

    def _apply_block_reward(self, proposer: str, in_atomic: bool = False) -> float:
        return self.state_service.apply_block_reward(proposer, in_atomic=in_atomic)

    def _compute_state_root_from_db(self) -> str:
        return self.state_service.compute_state_root()

    # ── Native simple-block apply / reorg assist ─────────────────────────────

    @staticmethod
    def _tx_is_simple(tx) -> bool:
        return StateService._tx_is_simple(tx)

    def _block_transactions_are_simple(self, transactions) -> bool:
        return self.state_service._block_transactions_are_simple(transactions)

    def _block_transactions_are_all_evm(self, transactions) -> bool:
        return self.state_service._block_transactions_are_all_evm(transactions)

    def _block_transactions_are_mixed(self, transactions) -> bool:
        return self.state_service._block_transactions_are_mixed(transactions)

    def _collect_addrs_for_simple_block(self, block: "Block") -> set:
        return self.state_service._collect_addrs_for_simple_block(block)

    def _accounts_sat_snapshot(self, addresses) -> Dict[str, Dict[str, int]]:
        return self.state_service._accounts_sat_snapshot(addresses)

    def _writeback_accounts_sat(self, accounts: Dict[str, Any]) -> None:
        return self.state_service._writeback_accounts_sat(accounts)

    def _apply_simple_block_native(self, block: "Block") -> float:
        return self.state_service._apply_simple_block_native(block)

    def _run_evm_host_only(self, tx: "Transaction", block_height: int) -> Dict:
        return self.state_service._run_evm_host_only(tx, block_height)

    def _apply_evm_host_block_native(self, block: "Block") -> float:
        return self.state_service._apply_evm_host_block_native(block)

    def _apply_mixed_block_native(self, block: "Block") -> float:
        return self.state_service._apply_mixed_block_native(block)

    def _blocks_range_are_simple(self, from_h: int, to_h: int) -> bool:
        return self.state_service._blocks_range_are_simple(from_h, to_h)

    def _replay_simple_range_native(self, ancestor_height: int, alloc: Dict[str, Any]) -> float:
        return self.state_service._replay_simple_range_native(ancestor_height, alloc)

    # ── Применение транзакции ────────────────────────────────────────────────

    def _apply_transaction(
        self, tx: Transaction, block_height: int, proposer: str = None, in_atomic: bool = False
    ) -> Dict:
        return self.state_service.apply_transaction(
            tx, block_height, proposer, in_atomic=in_atomic
        )

    # ── Валидация ────────────────────────────────────────────────────────────

    def validate_transaction(
        self, tx: Transaction, *, expected_nonce: Optional[int] = None
    ) -> Dict:
        if expected_nonce is None:
            return self.tx_pipeline.validate_for_mempool(tx).as_dict()
        return self.tx_pipeline.validate_for_block(tx, expected_nonce=int(expected_nonce)).as_dict()

    def _is_evm_deploy_tx(self, tx: Transaction) -> bool:
        return self.tx_pipeline._is_evm_deploy_tx(tx)

    def _validate_evm_deploy_bytecode(self, tx: Transaction) -> Dict:
        return self.tx_pipeline._validate_evm_deploy_bytecode(tx).as_dict()

    def _verify_tx_signature(self, tx: Transaction) -> Dict:
        return self.tx_pipeline.verify_tx_signature(tx).as_dict()

    def _verify_block_tx_signatures(self, block: Block) -> Dict:
        return self.tx_pipeline.verify_signatures(block).as_dict()

    def _verify_block_proposer(
        self, block: Block, *, allow_slashed: bool = False
    ) -> Dict:
        """Slashing + authorized proposer checks before block execution.

        ``allow_slashed`` is set for P2P catch-up (``preserve_peer_hash``):
        a local slash penalty must not partition the node off the canonical
        chain of the (only) miner.
        """
        proposer = block.miner or ""
        if not proposer or proposer == "genesis":
            return {"valid": True}

        slashing = self._resolve_slashing_core()
        if slashing:
            if proposer in slashing.slashed and not allow_slashed:
                return {"valid": False, "error": "proposer_slashed"}

        if not getattr(self.config, "enforce_proposer", True):
            return {"valid": True}

        validators = self.storage.get_validators(active_only=True) if hasattr(self.storage, "get_validators") else []
        if len(validators) <= 1:
            return {"valid": True}

        allowed = {v["address"].lower() for v in validators}
        for addr in (self.config.miner_address, self.config.signing_address):
            if addr:
                allowed.add(addr.lower())
        if proposer.lower() not in allowed:
            return {"valid": False, "error": "unauthorized_proposer"}
        return {"valid": True}

    def _resolve_slashing_core(self):
        """Return underlying SlashingEngine from consensus adapter."""
        adapter = self.consensus_adapter
        if not adapter:
            return None
        engine = getattr(adapter, "slashing_engine", None)
        if engine is None:
            return None
        if hasattr(engine, "slashing"):
            return engine.slashing
        if hasattr(engine, "slashed"):
            return engine
        return None

    def find_ancestor_height(self, parent_hash: str) -> Optional[int]:
        """Local height of parent_hash (fork common ancestor lookup)."""
        if not parent_hash or parent_hash == self.GENESIS_HASH:
            return 0
        blk = self.get_block_by_hash(parent_hash)
        if blk:
            return int(blk.get("height", blk.get("number", 0)))
        return None

    def reorg_to_ancestor(self, ancestor_height: int) -> bool:
        """Rollback blocks above ancestor and replay state from genesis allocation."""
        floor = 0
        adapter = self.consensus_adapter
        if adapter and hasattr(adapter, "get_finalized_floor_height"):
            floor = int(adapter.get_finalized_floor_height() or 0)
        if floor > 0 and int(ancestor_height) < floor:
            print(
                f"[Blockchain] Reorg denied: height #{ancestor_height} "
                f"is below finalized floor #{floor}"
            )
            return False

        from runtime.tokenomics import genesis_balances

        with self.lock:
            tip = self.get_height()
            if ancestor_height > tip:
                return True

            founder = self._pinned_genesis_founder()
            alloc = genesis_balances(founder or None)

            try:
                repair_meta: tuple[int, str] | None = None
                with self.storage.atomic():
                    cut = int(ancestor_height)
                    replay_only = cut >= tip
                    if not replay_only:
                        self.storage.reorg_truncate_above(cut)

                    self.storage.reset_accounts_from_alloc(alloc, _in_atomic=True)

                    native_replayed = False
                    if (
                        ancestor_height >= 1
                        and native.native_available()
                        and hasattr(native, "blockchain_replay_simple_blocks")
                        and self._blocks_range_are_simple(1, ancestor_height)
                    ):
                        try:
                            self._replay_simple_range_native(ancestor_height, alloc)
                            native_replayed = True
                        except Exception as native_exc:
                            if self._native_apply_fail_closed():
                                raise
                            _logger.debug(
                                "[Blockchain] native reorg replay fallback: %s", native_exc
                            )

                    if not native_replayed:
                        for h in range(1, ancestor_height + 1):
                            block_dict = self.storage.get_block(h)
                            if not block_dict:
                                raise RuntimeError(f"missing_block_at_replay_{h}")
                            block = Block.from_dict(block_dict)
                            for tx in block.transactions:
                                result = self._apply_transaction(
                                    tx, block.height, proposer=block.miner, in_atomic=True
                                )
                                if not result["success"]:
                                    raise RuntimeError(result.get("error", "replay_tx_failed"))
                            self._apply_block_reward(block.miner, in_atomic=True)

                    replay_root = self._compute_state_root_from_db()
                    ancestor_block = self.storage.get_block(cut)
                    if ancestor_block:
                        expected = str(ancestor_block.get("state_root") or "").strip()
                        if expected and expected != replay_root:
                            if replay_only:
                                repair_meta = (cut, replay_root)
                            else:
                                raise RuntimeError("reorg_state_root_mismatch")

                if repair_meta is not None:
                    self._align_block_state_root_metadata(repair_meta[0], repair_meta[1])

                action = "State replay" if replay_only else "Reorg"
                print(f"[Blockchain] {action} complete at height #{ancestor_height}")
                return True
            except Exception as e:
                print(f"[Blockchain] Reorg failed: {e}")
                return False

    def ensure_state_at_tip(self) -> bool:
        """Replay canonical chain if live balances drifted from tip block state_root."""
        with self.lock:
            h = self.get_height()
            tip_blk = self.storage.get_block(h)
            if not tip_blk:
                return True
            expected = str(tip_blk.get("state_root") or "").strip()
            if not expected:
                return True
            current = self._compute_state_root_from_db()
            if current == expected:
                return True
            if h == 0:
                self._align_genesis_state_root_if_needed()
                tip_blk = self.storage.get_block(0)
                expected = str((tip_blk or {}).get("state_root") or "").strip()
                return self._compute_state_root_from_db() == expected
            print(
                f"[Blockchain] State drift at tip #{h} "
                f"(live={current[:16]}… expected={expected[:16]}…) — replaying"
            )
            ok = self.reorg_to_ancestor(h)
            return ok

    def _validate_block_structure(self, block: Block) -> Dict:
        """Height/parent/hash checks before state execution."""
        last = self.storage.get_last_block()
        if last:
            expected_height = last["height"] + 1
            if block.height != expected_height:
                return {"valid": False, "error": f"height_mismatch (got {block.height}, expected {expected_height})"}
            if block.parent_hash != last["hash"]:
                return {"valid": False, "error": "parent_hash_mismatch"}
        elif block.height not in (0, 1):
            return {"valid": False, "error": "expected_genesis_height_0_or_1"}
        return {"valid": True}

    def validate_block(self, block: Block) -> Dict:
        """Полная структурная валидация блока (для P2P-синхронизации)."""
        base = self._validate_block_structure(block)
        if not base["valid"]:
            return base
        recomputed = block._compute_hash()
        if block.hash != recomputed:
            return {"valid": False, "error": "invalid_hash"}
        proposer = self._verify_block_proposer(block)
        if not proposer["valid"]:
            return proposer
        return {"valid": True}

    # ── Публичные геттеры ────────────────────────────────────────────────────

    def get_height(self) -> int:
        return self.storage.get_chain_tip()

    def get_balance(self, address: str) -> float:
        from runtime.state_truth import canonical_balance_abs

        return canonical_balance_abs(self.storage.unwrap(), address)

    def get_balance_satoshi(self, address: str) -> int:
        from runtime.state_truth import canonical_balance_satoshi

        return canonical_balance_satoshi(self.storage.unwrap(), address)

    def get_last_block(self) -> Optional[Dict]:
        return self.storage.get_last_block()

    def get_block(self, height: int) -> Optional[Dict]:
        return self.storage.get_block(height)

    def get_block_by_hash(self, block_hash: str) -> Optional[Dict]:
        return self.storage.get_block_by_hash(block_hash) if hasattr(self.storage, "get_block_by_hash") else None

    def truncate_to_height(self, height: int) -> int:
        """Drop blocks above height (keep genesis at 0). Used when joining a longer peer chain."""
        with self.lock:
            return self.storage.truncate_blocks_above(height)

    def get_transaction(self, tx_hash: str) -> Optional[Dict]:
        return self.storage.get_transaction(tx_hash)

    def get_state_root(self) -> str:
        """Last committed canonical root (header/meta). Does not rescan accounts.

        Apply/verify still call ``_compute_state_root_from_db``. HTTP /status, P2P
        solicit, and harness must not rehash full state on every poll.
        """
        store = self.storage
        if store is not None and hasattr(store, "get_live_state_root_meta"):
            try:
                root, _height = store.get_live_state_root_meta()
                root_s = str(root or "").strip()
                if root_s:
                    return root_s
            except (OSError, TypeError, ValueError, AttributeError):
                pass
        if store is not None and hasattr(store, "get_last_block"):
            try:
                last = store.get_last_block() or {}
                root_s = str((last or {}).get("state_root") or "").strip()
                if root_s:
                    return root_s
            except (OSError, TypeError, ValueError, AttributeError):
                pass
        # Empty committed root: return "" (fail-closed for HTTP/P2P). Never scan accounts.
        return ""

    def get_stats(self) -> Dict:
        db_stats = self.storage.get_stats()
        burn_stats = self.storage.get_burn_stats()
        chain_metrics = (
            self.storage.get_chain_metrics()
            if hasattr(self.storage, "get_chain_metrics")
            else {}
        )
        return {
            **db_stats,
            **burn_stats,
            **chain_metrics,
            "coin_symbol": self.config.coin_symbol,
            "chain_id": self.config.chain_id,
            "network": self.config.network_name,
            "max_supply": getattr(self.config, "max_supply", MAX_SUPPLY_ABS),
            "founder_initials": getattr(self.config, "founder_initials", "D.U.P."),
            "founder_percent": getattr(self.config, "founder_percent", 17.4),
            "founder_address": getattr(self.config, "founder_address", ""),
            "state_root": self.get_state_root(),
            "state_engine": self.state_engine is not None,
            "block_validator": self.block_validator is not None,
            "canonical_hash": _CANONICAL_AVAILABLE,
            "require_signatures": getattr(self, "require_signatures", False),
        }
