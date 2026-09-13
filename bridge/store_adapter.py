# bridge/store_adapter.py — BridgeStorePort over legacy store / StoragePort.unwrap()
"""ADR 0010 storage edge for bridge debit/credit/refund."""

from __future__ import annotations

from typing import Any, Dict, Optional

from bridge.validators import compute_replay_key


class BridgeStoreAdapter:
    """Delegates to Rocks/SQLite/Hybrid store methods already in tree."""

    def __init__(self, store: Any):
        if store is None:
            raise ValueError("BridgeStoreAdapter requires a store")
        # StoragePort composite → unwrap to concrete engine
        unwrap = getattr(store, "unwrap", None)
        self._store = unwrap() if callable(unwrap) else store

    @property
    def raw(self) -> Any:
        return self._store

    def bridge_credit_key(
        self, from_chain: str, event_tx_hash: str, log_index: int = 0
    ) -> str:
        if hasattr(self._store, "bridge_credit_key"):
            return str(
                self._store.bridge_credit_key(from_chain, event_tx_hash, int(log_index or 0))
            )
        return compute_replay_key(from_chain, event_tx_hash, int(log_index or 0))

    def has_bridge_credit(self, credit_key: str) -> bool:
        if hasattr(self._store, "has_bridge_credit"):
            return bool(self._store.has_bridge_credit(credit_key))
        return False

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
        if hasattr(self._store, "debit_and_create_bridge_lock"):
            return self._store.debit_and_create_bridge_lock(
                from_addr=from_addr,
                amount=amount,
                burn_address=burn_address,
                burn_amount=burn_amount,
                to_chain=to_chain,
                to_addr=to_addr,
                net_amount=net_amount,
                tx_hash=tx_hash,
            )
        raise RuntimeError("debit_and_create_bridge_lock unavailable")

    def claim_and_credit_bridge_event(
        self,
        from_chain: str,
        event_tx_hash: str,
        recipient: str,
        amount: float,
        log_index: int = 0,
        abs_tx_hash: str = "",
    ) -> Dict[str, Any]:
        if hasattr(self._store, "claim_and_credit_bridge_event"):
            return dict(
                self._store.claim_and_credit_bridge_event(
                    from_chain=from_chain,
                    event_tx_hash=event_tx_hash,
                    recipient=recipient,
                    amount=amount,
                    log_index=int(log_index or 0),
                    abs_tx_hash=abs_tx_hash or "",
                )
            )
        raise RuntimeError("claim_and_credit_bridge_event unavailable")

    def refund_pending_bridge_lock(self, tx_hash: str) -> Dict[str, Any]:
        if hasattr(self._store, "refund_pending_bridge_lock"):
            return dict(self._store.refund_pending_bridge_lock(tx_hash))
        return {"refunded": False, "error": "refund_pending_bridge_lock unavailable"}

    def get_bridge_lock(self, lock_hash: str) -> Optional[Dict[str, Any]]:
        store = self._store
        if hasattr(store, "get_bridge_lock"):
            row = store.get_bridge_lock(lock_hash)
            return dict(row) if row else None
        # Fallback: scan get_bridge_locks
        if hasattr(store, "get_bridge_locks"):
            for row in store.get_bridge_locks(limit=500) or []:
                if str(row.get("tx_hash") or "") == str(lock_hash):
                    return dict(row)
        return None

    def confirm_bridge_lock_status(
        self, lock_hash: str, *, l1_tx_hash: str = ""
    ) -> Dict[str, Any]:
        """Confirm a pending lock. Wave L: never paint confirmed without a real transition."""
        store = self._store
        lock = self.get_bridge_lock(lock_hash)
        if not lock:
            return {"ok": False, "error": "lock_not_found"}
        if str(lock.get("status") or "") != "pending":
            return {
                "ok": False,
                "error": "illegal_transition",
                "status": lock.get("status"),
            }
        if not hasattr(store, "confirm_bridge_lock"):
            return {"ok": False, "error": "confirm_bridge_lock_unavailable"}
        try:
            store.confirm_bridge_lock(lock_hash)
        except Exception as exc:
            return {"ok": False, "error": f"confirm_failed:{exc}"}
        after = self.get_bridge_lock(lock_hash)
        if not after or str(after.get("status") or "") != "confirmed":
            return {"ok": False, "error": "confirm_did_not_persist"}
        return {"ok": True, "status": "confirmed", "l1_tx_hash": l1_tx_hash}
