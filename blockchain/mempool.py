#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mempool — пул неподтверждённых транзакций с приоритетом по комиссии.

Интегрирует:
  - Базовая сортировка по fee (System A)
  - Валидация адресов и сумм через middleware/validators.py
  - ECDSA проверка подписи через crypto/wallet.py
  - ADR 0021 phase-2: fee-sorted store may live in Rust (Python validates)
"""

import time
import threading
import logging
from collections.abc import Mapping
from typing import Any, Dict, Iterator, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# --- Input validation (middleware/validators.py) ---
try:
    from middleware.validators import validate_address, validate_amount, validate_tx_data
    _VALIDATORS_AVAILABLE = True
except ImportError:
    _VALIDATORS_AVAILABLE = False

# --- ECDSA signature verification (crypto/wallet.py) ---
try:
    from crypto.wallet import verify_transaction_signature, verify_transaction_signatures_batch
    _ECDSA_AVAILABLE = True
except ImportError:
    _ECDSA_AVAILABLE = False


@dataclass
class MempoolTransaction:
    """Транзакция в мемпуле.

    Dual-write: ``fee`` ABS float for wire/display; ``fee_satoshi`` integer is
    the canonical sort / min-fee / eviction key (ADR 0021 fee migration).
    """
    tx_hash: str
    from_addr: str
    to_addr: str
    amount: float
    fee: float
    nonce: int = 0
    signature: str = ""
    public_key: str = ""
    data: str = ""
    gas: int = 21_000
    timestamp: float = field(default_factory=time.time)
    fee_satoshi: int = -1

    def __post_init__(self) -> None:
        if int(self.fee_satoshi) < 0:
            from runtime.amount import to_satoshi

            self.fee_satoshi = int(to_satoshi(self.fee))

    def has_valid_signature(self) -> bool:
        """ECDSA check; when require_signatures is on, empty signature fails."""
        require = getattr(self, "require_signatures", False)
        if not self.signature:
            return not require
        if not self.public_key:
            return False
        if not _ECDSA_AVAILABLE:
            return False
        try:
            tx_dict = {
                "from": self.from_addr,
                "to": self.to_addr,
                "value": int(self.amount) if self.amount == int(self.amount) else self.amount,
                "nonce": self.nonce,
                "chain_id": getattr(self, "_chain_id", None) or getattr(self, "chain_id", 1),
                "signature": self.signature,
                "public_key": self.public_key,
                "data": self.data or "",
                "gas_limit": int(self.gas or 21_000),
            }
            return verify_transaction_signature(tx_dict)
        except RuntimeError:
            # Wave R: ECDSA unavailable must not paint as invalid signature.
            raise
        except Exception as exc:
            logger.warning("mempool signature verify error: %s", exc)
            return False


def _validate_mempool_tx(tx: MempoolTransaction, min_fee_satoshi: int) -> Tuple[bool, str]:
    """
    Полная валидация транзакции перед добавлением в мемпул.
    Использует middleware/validators.py если доступен.
    Min-fee gate is satoshi-integer (not float ABS).
    """
    if not tx.tx_hash:
        return False, "missing_hash"
    fee_sat = int(getattr(tx, "fee_satoshi", -1))
    if fee_sat < 0:
        from runtime.amount import to_satoshi

        fee_sat = int(to_satoshi(tx.fee))
        tx.fee_satoshi = fee_sat
    if fee_sat < int(min_fee_satoshi):
        return False, f"fee_too_low (min_satoshi={int(min_fee_satoshi)})"

    if _VALIDATORS_AVAILABLE:
        # Validate addresses
        valid, err = validate_address(tx.from_addr)
        if not valid:
            # Allow non-0x addresses (internal/genesis) with basic check
            if len(tx.from_addr) < 5:
                return False, f"invalid_from: {err}"

        valid, err = validate_address(tx.to_addr)
        if not valid:
            if len(tx.to_addr) < 5:
                return False, f"invalid_to: {err}"

        # Validate amount (zero-value allowed for contract deploy/call)
        if tx.amount < 0:
            return False, "negative_amount"
        if tx.amount > 0:
            valid, err = validate_amount(tx.amount, min_amount=0.0)
            if not valid:
                return False, f"invalid_amount: {err}"

    elif tx.amount < 0:
        return False, "negative_amount"

    return True, "ok"


def _mempool_tx_verify_dict(tx: MempoolTransaction, chain_id: int) -> Dict:
    return {
        "from": tx.from_addr,
        "to": tx.to_addr,
        "value": int(tx.amount) if tx.amount == int(tx.amount) else tx.amount,
        "nonce": tx.nonce,
        "chain_id": chain_id,
        "signature": tx.signature,
        "public_key": tx.public_key,
        "data": tx.data or "",
        "gas_limit": int(tx.gas or 21_000),
    }


def _tx_to_store_dict(tx: MempoolTransaction) -> Dict[str, Any]:
    from runtime.amount import from_satoshi_float, to_satoshi

    fee_sat = int(getattr(tx, "fee_satoshi", -1))
    if fee_sat < 0:
        fee_sat = int(to_satoshi(tx.fee))
        tx.fee_satoshi = fee_sat
    amount_sat = int(getattr(tx, "amount_satoshi", -1)) if hasattr(tx, "amount_satoshi") else -1
    if amount_sat < 0:
        amount_sat = int(to_satoshi(tx.amount))
        if hasattr(tx, "amount_satoshi"):
            tx.amount_satoshi = amount_sat
    # Wave R: ABS floats derived from satoshi (no raw float() money invent).
    return {
        "tx_hash": str(tx.tx_hash),
        "from_addr": str(tx.from_addr),
        "to_addr": str(tx.to_addr),
        "amount": from_satoshi_float(amount_sat),
        "amount_satoshi": int(amount_sat),
        "fee": from_satoshi_float(fee_sat),
        "fee_satoshi": int(fee_sat),
        "nonce": int(tx.nonce or 0),
        "signature": str(tx.signature or ""),
        "public_key": str(tx.public_key or ""),
        "data": str(tx.data or ""),
        "gas": int(tx.gas or 21_000),
        "timestamp": float(tx.timestamp or 0.0),
    }


def _tx_from_store_dict(raw: Dict[str, Any]) -> MempoolTransaction:
    from runtime.amount import from_satoshi_float, money_abs, to_satoshi

    raw_fee_sat = raw.get("fee_satoshi")
    if raw_fee_sat is None:
        fee_sat = int(to_satoshi(money_abs(raw.get("fee") or 0, field="fee")))
    else:
        fee_sat = int(raw_fee_sat)
    raw_amt_sat = raw.get("amount_satoshi")
    if raw_amt_sat is None:
        amount_sat = int(to_satoshi(money_abs(raw.get("amount") or 0, field="amount")))
    else:
        amount_sat = int(raw_amt_sat)
    return MempoolTransaction(
        tx_hash=str(raw.get("tx_hash") or ""),
        from_addr=str(raw.get("from_addr") or ""),
        to_addr=str(raw.get("to_addr") or ""),
        amount=from_satoshi_float(amount_sat),
        fee=from_satoshi_float(fee_sat),
        nonce=int(raw.get("nonce") or 0),
        signature=str(raw.get("signature") or ""),
        public_key=str(raw.get("public_key") or ""),
        data=str(raw.get("data") or ""),
        gas=int(raw.get("gas") or 21_000),
        timestamp=float(raw.get("timestamp") or 0.0),
        fee_satoshi=fee_sat,
    )


class _NativeTxMap(Mapping):
    """Read-only mapping over Rust store for ``mempool.transactions.get`` callers."""

    def __init__(self, pool: "Mempool") -> None:
        self._pool = pool

    def __getitem__(self, key: str) -> MempoolTransaction:
        tx = self._pool.get_transaction(str(key))
        if tx is None:
            raise KeyError(key)
        return tx

    def __iter__(self) -> Iterator[str]:
        # Lock order: Python RLock first, then Rust Mutex (via hashes()).
        with self._pool.lock:
            store = self._pool._native_store
            if store is None:
                return iter(list(self._pool._py_txs.keys()))
            try:
                return iter(list(store.hashes()))
            except Exception as exc:
                self._pool._demote_store(f"hashes:{exc}")
                return iter(list(self._pool._py_txs.keys()))

    def __len__(self) -> int:
        return self._pool.get_size()

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        tx = self._pool.get_transaction(str(key))
        return default if tx is None else tx


class Mempool:
    """Пул транзакций с сортировкой по комиссии и полной валидацией.

    ADR 0021 phase-2: pending set may be ``abs_native.MempoolStore`` (Rust).
    Signature / chain validation stays in Python. Lock order: this ``RLock``
    first, then Rust store Mutex — never reverse. On Rust store faults: demote
    to Python dict (fail-closed for process health; pending set migrated).
    """

    def __init__(self, max_size: int = 10000, min_fee: float = 0.0001):
        from runtime.amount import to_satoshi

        # Legacy tests call Mempool(config, db). Accept Config-like first arg.
        if not isinstance(max_size, int):
            cfg = max_size
            max_size = int(getattr(cfg, "mempool_max_size", 10_000) or 10_000)
            try:
                if callable(getattr(cfg, "base_fee", None)):
                    min_fee = float(cfg.base_fee()) * 0.5
                elif getattr(cfg, "min_fee", None) is not None:
                    min_fee = float(cfg.min_fee)
                else:
                    min_fee = float(min_fee)
            except (TypeError, ValueError):
                min_fee = 0.0001

        self._py_txs: Dict[str, MempoolTransaction] = {}
        self.max_size = int(max_size)
        self.min_fee = float(min_fee)
        self.min_fee_satoshi = int(to_satoshi(self.min_fee))
        self.lock = threading.RLock()
        self._rejected_count = 0
        self._demote_count = 0
        self._demote_reason = ""
        self._store_demoted = False
        self.blockchain = None
        self.chain_id = 1
        self.require_signatures = False
        self._native_store = None
        self._store_backend = "python"
        try:
            from crypto.native import create_mempool_store

            store = create_mempool_store(max_size=max_size, min_fee=min_fee)
            if store is not None:
                self._native_store = store
                self._store_backend = "rust"
        except Exception as exc:
            logger.warning("mempool native store unavailable: %s", exc)
            self._native_store = None
            self._store_backend = "python"

    @property
    def transactions(self) -> Mapping:
        """Pending map. Rust backend exposes a Mapping view (get/contains)."""
        if self._native_store is not None:
            return _NativeTxMap(self)
        return self._py_txs

    def set_blockchain(self, blockchain) -> None:
        """Attach live chain for nonce/balance/signature checks."""
        self.blockchain = blockchain
        if blockchain and getattr(blockchain, "config", None):
            self.chain_id = blockchain.config.chain_id
            self.require_signatures = getattr(
                blockchain.config, "require_signatures", False
            )

    def _demote_store(self, reason: str) -> None:
        """Drop Rust store; migrate pending txs into Python dict. Caller holds lock."""
        store = self._native_store
        if store is None and self._store_backend == "python":
            return
        logger.warning("mempool demote rust store → python (%s)", reason)
        self._demote_count = int(getattr(self, "_demote_count", 0) or 0) + 1
        self._demote_reason = str(reason or "demoted")
        self._store_demoted = True
        migrated = 0
        if store is not None:
            try:
                rows = list(store.get_sorted(int(self.max_size), 0))
                for raw in rows:
                    tx = _tx_from_store_dict(dict(raw))
                    if tx.tx_hash and tx.tx_hash not in self._py_txs:
                        self._py_txs[tx.tx_hash] = tx
                        migrated += 1
            except Exception as exc:
                logger.error("mempool store migrate on demote failed: %s", exc)
        self._native_store = None
        self._store_backend = "python"
        try:
            from runtime.native_capabilities import NativeFamily, get_registry

            get_registry().demote(NativeFamily.MEMPOOL_STORE, str(reason or "demoted"))
        except Exception as exc:
            logger.warning("mempool store registry demote failed: %s", exc)
        logger.warning("mempool store demoted; migrated=%s pending=%s", migrated, len(self._py_txs))

    def _store_put(self, tx: MempoolTransaction) -> bool:
        if self._native_store is not None:
            try:
                return bool(self._native_store.insert(_tx_to_store_dict(tx)))
            except Exception as exc:
                self._demote_store(f"insert:{exc}")
        if tx.tx_hash in self._py_txs:
            return False
        if len(self._py_txs) >= self.max_size:
            self._cleanup_python()
        if len(self._py_txs) >= self.max_size:
            return False
        self._py_txs[tx.tx_hash] = tx
        return True

    def add(
        self,
        tx: MempoolTransaction,
        signature_preverified: bool = False,
        chain_prevalidated: bool = False,
    ) -> bool:
        """Добавить транзакцию с полной валидацией.

        v1.3.143: chain_prevalidated skips a second blockchain.validate_transaction
        when the P2P path already validated (sig-before-DB). Soft DoS honesty only.
        """
        with self.lock:
            if self.has_transaction(tx.tx_hash):
                return False

            # Full validation (min-fee in satoshi)
            valid, reason = _validate_mempool_tx(tx, self.min_fee_satoshi)
            if not valid:
                self._rejected_count += 1
                return False

            tx._chain_id = self.chain_id
            tx.require_signatures = self.require_signatures

            # ECDSA signature check
            if not signature_preverified and not tx.has_valid_signature():
                self._rejected_count += 1
                return False

            if self.blockchain and not chain_prevalidated:
                from core.blockchain import Transaction
                chain_tx = Transaction(
                    from_addr=tx.from_addr,
                    to_addr=tx.to_addr,
                    value=tx.amount,
                    nonce=tx.nonce,
                    gas=int(getattr(tx, "gas", 0) or 0) or self.blockchain.config.base_gas_price,
                    data=getattr(tx, "data", "") or "",
                    tx_hash=tx.tx_hash,
                    signature=tx.signature,
                    public_key=tx.public_key,
                )
                tx._chain_id = self.chain_id
                check = self.blockchain.validate_transaction(chain_tx)
                if not check.get("valid"):
                    self._rejected_count += 1
                    return False

            if not self._store_put(tx):
                self._rejected_count += 1
                return False
            return True

    def verify_signatures_batch(self, txs: List[MempoolTransaction]) -> List[bool]:
        """Batch ECDSA gate for gossip/import bursts via native secp256k1."""
        results = [False for _ in txs]
        if not txs:
            return results

        require = self.require_signatures
        verify_payloads: List[Dict] = []
        verify_indexes: List[int] = []

        for index, tx in enumerate(txs):
            tx._chain_id = self.chain_id
            tx.require_signatures = require
            if not tx.signature:
                results[index] = not require
                continue
            if not tx.public_key:
                results[index] = False
                continue
            verify_payloads.append(_mempool_tx_verify_dict(tx, self.chain_id))
            verify_indexes.append(index)

        if verify_payloads and _ECDSA_AVAILABLE:
            verified = verify_transaction_signatures_batch(verify_payloads)
            for index, ok in zip(verify_indexes, verified):
                results[index] = bool(ok)

        return results

    def add_batch(
        self,
        txs: List[MempoolTransaction],
        *,
        chain_prevalidated: bool = False,
    ) -> Tuple[int, int, List[str]]:
        """Add many txs with one native signature batch verify pass.

        v1.3.143: chain_prevalidated skips second validate_transaction when the
        caller already validated each tx (P2P wire build path).
        """
        if not txs:
            return 0, 0, []

        signature_flags = self.verify_signatures_batch(txs)
        added = 0
        rejected = 0
        accepted_hashes: List[str] = []
        for tx, signature_ok in zip(txs, signature_flags):
            if not signature_ok:
                with self.lock:
                    self._rejected_count += 1
                rejected += 1
                continue
            if self.add(
                tx,
                signature_preverified=True,
                chain_prevalidated=chain_prevalidated,
            ):
                added += 1
                accepted_hashes.append(tx.tx_hash)
            else:
                rejected += 1
        return added, rejected, accepted_hashes

    def add_raw(self, tx: MempoolTransaction) -> bool:
        """Добавить транзакцию без строгой валидации адресов (для internal/genesis txs)."""
        with self.lock:
            if self.has_transaction(tx.tx_hash):
                return False
            fee_sat = int(getattr(tx, "fee_satoshi", -1))
            if fee_sat < 0:
                from runtime.amount import to_satoshi

                fee_sat = int(to_satoshi(tx.fee))
                tx.fee_satoshi = fee_sat
            if fee_sat < int(self.min_fee_satoshi):
                return False
            return self._store_put(tx)

    def get(self, limit: int = 100, min_fee: float = 0) -> List[MempoolTransaction]:
        """Получить транзакции для майнинга (сортировка по fee_satoshi)."""
        from runtime.amount import to_satoshi

        min_fee_sat = int(to_satoshi(min_fee)) if min_fee else 0
        with self.lock:
            if self._native_store is not None:
                try:
                    rows = list(self._native_store.get_sorted(int(limit), int(min_fee_sat)))
                    return [_tx_from_store_dict(dict(r)) for r in rows]
                except Exception as exc:
                    self._demote_store(f"get_sorted:{exc}")
            sorted_txs = sorted(
                self._py_txs.values(),
                key=lambda x: int(getattr(x, "fee_satoshi", 0) or 0),
                reverse=True
            )
            return [
                tx for tx in sorted_txs
                if int(getattr(tx, "fee_satoshi", 0) or 0) >= min_fee_sat
            ][:limit]

    def get_sorted_transactions(self) -> List[Dict]:
        """Возвращает транзакции в формате dict (для BlockBuilder System C)."""
        with self.lock:
            if self._native_store is not None:
                try:
                    rows = list(self._native_store.get_sorted(self.max_size, 0))
                    return [
                        {
                            "hash": str(r.get("tx_hash") or ""),
                            "from": str(r.get("from_addr") or ""),
                            "to": str(r.get("to_addr") or ""),
                            "value": float(r.get("amount") or 0.0),
                            "gasPrice": float(r.get("fee") or 0.0),
                            "gas": int(r.get("gas") or 21000),
                            "nonce": int(r.get("nonce") or 0),
                            "data": str(r.get("data") or ""),
                            "timestamp": float(r.get("timestamp") or 0.0),
                            "fee_satoshi": int(r.get("fee_satoshi") or 0),
                        }
                        for r in rows
                    ]
                except Exception as exc:
                    self._demote_store(f"get_sorted_tx:{exc}")
            sorted_txs = sorted(
                self._py_txs.values(),
                key=lambda x: int(getattr(x, "fee_satoshi", 0) or 0),
                reverse=True
            )
            return [
                {
                    "hash": tx.tx_hash,
                    "from": tx.from_addr,
                    "to": tx.to_addr,
                    "value": tx.amount,
                    "gasPrice": tx.fee,
                    "gas": tx.gas or 21000,
                    "nonce": tx.nonce,
                    "data": tx.data or "",
                    "timestamp": tx.timestamp,
                    "fee_satoshi": int(getattr(tx, "fee_satoshi", 0) or 0),
                }
                for tx in sorted_txs
            ]

    def remove(self, tx_hash: str) -> bool:
        """Удалить транзакцию."""
        with self.lock:
            if self._native_store is not None:
                try:
                    return bool(self._native_store.remove(str(tx_hash)))
                except Exception as exc:
                    self._demote_store(f"remove:{exc}")
            return self._py_txs.pop(tx_hash, None) is not None

    def has_transaction(self, tx_hash: str) -> bool:
        with self.lock:
            if self._native_store is not None:
                try:
                    return bool(self._native_store.contains(str(tx_hash)))
                except Exception as exc:
                    self._demote_store(f"contains:{exc}")
            return tx_hash in self._py_txs

    def get_transaction(self, tx_hash: str) -> Optional[MempoolTransaction]:
        with self.lock:
            if self._native_store is not None:
                try:
                    raw = self._native_store.get(str(tx_hash))
                    if raw is None:
                        return None
                    return _tx_from_store_dict(dict(raw))
                except Exception as exc:
                    self._demote_store(f"get:{exc}")
            return self._py_txs.get(tx_hash)

    def get_size(self) -> int:
        with self.lock:
            if self._native_store is not None:
                try:
                    return int(self._native_store.size())
                except Exception as exc:
                    self._demote_store(f"size:{exc}")
            return len(self._py_txs)

    def get_stats(self) -> dict:
        with self.lock:
            if self._native_store is not None:
                try:
                    size = int(self._native_store.size())
                    total_fees, avg_fee = self._native_store.fee_stats()
                    return {
                        "size": size,
                        "total_fees": float(total_fees),
                        "avg_fee": float(avg_fee) if size else 0,
                        "rejected": self._rejected_count,
                        "validators_available": _VALIDATORS_AVAILABLE,
                        "ecdsa_available": _ECDSA_AVAILABLE,
                        "store_backend": self._store_backend,
                        "store_demoted": bool(self._store_demoted),
                        "demote_count": int(self._demote_count),
                        "demote_reason": str(self._demote_reason or ""),
                        "min_fee_satoshi": int(self.min_fee_satoshi),
                    }
                except Exception as exc:
                    self._demote_store(f"fee_stats:{exc}")
            if not self._py_txs:
                return {
                    "size": 0,
                    "total_fees": 0,
                    "avg_fee": 0,
                    "rejected": self._rejected_count,
                    "store_backend": self._store_backend,
                    "store_demoted": bool(self._store_demoted),
                    "demote_count": int(self._demote_count),
                    "demote_reason": str(self._demote_reason or ""),
                    "min_fee_satoshi": int(self.min_fee_satoshi),
                }
            fees = [tx.fee for tx in self._py_txs.values()]
            return {
                "size": len(self._py_txs),
                "total_fees": sum(fees),
                "avg_fee": sum(fees) / len(fees),
                "rejected": self._rejected_count,
                "validators_available": _VALIDATORS_AVAILABLE,
                "ecdsa_available": _ECDSA_AVAILABLE,
                "store_backend": self._store_backend,
                "store_demoted": bool(self._store_demoted),
                "demote_count": int(self._demote_count),
                "demote_reason": str(self._demote_reason or ""),
                "min_fee_satoshi": int(self.min_fee_satoshi),
            }

    def _cleanup_python(self):
        """Удалить 10% самых дешёвых транзакций (Python store, by fee_satoshi)."""
        if len(self._py_txs) < self.max_size * 0.8:
            return
        sorted_txs = sorted(
            self._py_txs.values(),
            key=lambda x: int(getattr(x, "fee_satoshi", 0) or 0),
        )
        to_remove = int(len(self._py_txs) * 0.1)
        for tx in sorted_txs[:to_remove]:
            del self._py_txs[tx.tx_hash]

    def _cleanup(self):
        """Back-compat alias; Rust store cleans inside insert."""
        if self._native_store is None:
            self._cleanup_python()
