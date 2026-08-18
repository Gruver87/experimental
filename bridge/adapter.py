# bridge/adapter.py — RustBridgeAdapter (ADR 0010 BridgePort)
"""Wraps legacy RustBridge behind BridgePort + inbound validator gate."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from bridge.ports import (
    BridgeOpResult,
    InboundEnvelope,
    InboundStatus,
    LockStatus,
    NullBridgePort,
)
from bridge.state_machine import inbound_status_from_claim
from bridge.store_adapter import BridgeStoreAdapter
from bridge.validators import InboundMessageValidator, PassthroughInboundValidator


class LiveL1Rpc:
    """L1RpcPort backed by bridge.l1_rpc helpers."""

    def get_tx_receipt(self, chain: str, tx_hash: str) -> Optional[Dict[str, Any]]:
        from bridge.l1_rpc import _rpc_call, chain_rpc_url

        url = chain_rpc_url(chain)
        if not url or not tx_hash:
            return None
        try:
            receipt = _rpc_call(url, "eth_getTransactionReceipt", [tx_hash])
            return dict(receipt) if receipt else None
        except Exception:
            return None

    def get_confirmations(self, chain: str, tx_hash: str) -> int:
        from bridge.l1_rpc import chain_rpc_url, get_tx_confirmations

        url = chain_rpc_url(chain)
        conf = get_tx_confirmations(url, tx_hash) if url else None
        return int(conf or 0)

    def receipt_status_ok(self, receipt: Dict[str, Any]) -> bool:
        from bridge.l1_rpc import _receipt_status_ok

        return bool(_receipt_status_ok(receipt or {}))


class RustBridgeAdapter:
    """
    BridgePort over RustBridge.

    - Inbound: validate → then legacy claim/credit (no credit on reject).
    - Outbound / confirm / refund: delegate to RustBridge.
    - Legacy positional confirm_incoming still accepted for HTTP/relayer.
    """

    def __init__(
        self,
        inner: Any,
        *,
        validator: Any = None,
        store: Any = None,
        l1_rpc: Any = None,
    ):
        if inner is None:
            raise ValueError("RustBridgeAdapter requires an inner bridge")
        self._inner = inner
        self.store = store or BridgeStoreAdapter(getattr(inner, "db", None))
        self.l1_rpc = l1_rpc
        self.validator = validator or PassthroughInboundValidator()
        # Expose common duck-typed attrs used by HTTP / health
        self.config = getattr(inner, "config", None)
        self.db = getattr(inner, "db", None)
        self.bus = getattr(inner, "bus", None)

    @property
    def _mode(self) -> str:
        return str(getattr(self._inner, "_mode", "") or "")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def start(self):
        return self._inner.start()

    def stop(self) -> None:
        return self._inner.stop()

    def lock_and_bridge(
        self, from_addr, to_chain, to_addr, amount, **kwargs
    ) -> BridgeOpResult:
        raw = self._inner.lock_and_bridge(
            from_addr, to_chain, to_addr, amount, **kwargs
        )
        return self._wrap_lock(raw)

    def confirm_incoming(self, *args, **kwargs) -> BridgeOpResult:
        envelope = self._coerce_envelope(*args, **kwargs)
        vr = self.validator.validate(envelope)
        if not vr.ok:
            if self.bus:
                try:
                    self.bus.emit(
                        "bridge.inbound_rejected",
                        {
                            "reason": vr.reason,
                            "replay_key": vr.replay_key,
                            "event_tx_hash": envelope.event_tx_hash,
                            "from_chain": envelope.from_chain,
                        },
                    )
                except Exception:
                    pass
            return BridgeOpResult(
                ok=False,
                status=InboundStatus.REJECTED.value,
                detail={
                    "confirmed": False,
                    "error": vr.reason,
                    "reason": vr.reason,
                    "replay_key": vr.replay_key,
                },
            )

        abs_tx = envelope.abs_tx_hash or envelope.event_tx_hash
        l1_tx = str(
            envelope.oracle_meta.get("l1_tx_hash")
            or (
                envelope.event_tx_hash
                if envelope.abs_tx_hash
                and envelope.event_tx_hash
                and envelope.abs_tx_hash != envelope.event_tx_hash
                else ""
            )
            or ""
        ).strip()
        raw = self._inner.confirm_incoming(
            abs_tx,
            envelope.to_addr,
            float(envelope.amount),
            envelope.from_chain,
            l1_tx_hash=l1_tx,
            log_index=int(envelope.log_index or 0),
        )
        return self._wrap_inbound(raw)

    def confirm_lock(self, abs_lock_hash: str, l1_tx_hash: str = "") -> BridgeOpResult:
        raw = self._inner.confirm_lock(abs_lock_hash, l1_tx_hash=l1_tx_hash)
        if isinstance(raw, dict) and raw.get("confirmed"):
            return BridgeOpResult(
                ok=True, status=LockStatus.CONFIRMED.value, detail=dict(raw)
            )
        err = (raw or {}).get("error", "confirm_lock_failed") if isinstance(raw, dict) else "confirm_lock_failed"
        return BridgeOpResult(ok=False, status="failed", detail={"error": err, **(raw or {})})

    def refund(self, abs_lock_hash: str, reason: str = "") -> BridgeOpResult:
        raw = self._inner.refund(abs_lock_hash)
        if isinstance(raw, dict) and raw.get("refunded"):
            detail = dict(raw)
            if reason:
                detail["reason"] = reason
            return BridgeOpResult(ok=True, status=LockStatus.REFUNDED.value, detail=detail)
        err = (raw or {}).get("error", "refund_failed") if isinstance(raw, dict) else "refund_failed"
        return BridgeOpResult(ok=False, status="failed", detail={"error": err, **(raw or {})})

    def get_stats(self) -> Dict[str, Any]:
        stats = dict(self._inner.get_stats() or {})
        stats.setdefault("enabled", True)
        stats.setdefault("backend", "rust_adapter")
        stats["port"] = "BridgePort"
        return stats

    @staticmethod
    def _coerce_envelope(*args, **kwargs) -> InboundEnvelope:
        if args and isinstance(args[0], InboundEnvelope):
            return args[0]
        # Legacy: confirm_incoming(tx_hash, recipient, amount, from_chain, ...)
        tx_hash = str(args[0] if len(args) > 0 else kwargs.get("tx_hash", "") or "")
        recipient = str(args[1] if len(args) > 1 else kwargs.get("recipient", "") or "")
        amount = float(args[2] if len(args) > 2 else kwargs.get("amount", 0) or 0)
        from_chain = str(
            args[3] if len(args) > 3 else kwargs.get("from_chain", "ethereum") or "ethereum"
        )
        l1_tx = str(kwargs.get("l1_tx_hash", "") or "").strip()
        log_index = int(kwargs.get("log_index", 0) or 0)
        event_tx = l1_tx or tx_hash
        meta = dict(kwargs.get("oracle_meta") or {})
        if l1_tx:
            meta.setdefault("l1_tx_hash", l1_tx)
        return InboundEnvelope(
            from_chain=from_chain,
            to_addr=recipient,
            amount=amount,
            event_tx_hash=event_tx,
            log_index=log_index,
            receipt=kwargs.get("receipt"),
            zk_proof=kwargs.get("zk_proof"),
            oracle_meta=meta,
            abs_tx_hash=tx_hash if l1_tx and l1_tx != tx_hash else "",
        )

    @staticmethod
    def _wrap_lock(raw: Any) -> BridgeOpResult:
        if not isinstance(raw, dict):
            return BridgeOpResult(ok=False, status="failed", detail={"error": "invalid_response"})
        if raw.get("error"):
            return BridgeOpResult(ok=False, status="failed", detail=dict(raw))
        status = str(raw.get("status") or LockStatus.PENDING.value)
        return BridgeOpResult(ok=True, status=status, detail=dict(raw))

    @staticmethod
    def _wrap_inbound(raw: Any) -> BridgeOpResult:
        if not isinstance(raw, dict):
            return BridgeOpResult(ok=False, status=InboundStatus.REJECTED.value, detail={"error": "invalid_response"})
        if raw.get("error") and not raw.get("confirmed"):
            return BridgeOpResult(
                ok=False,
                status=InboundStatus.REJECTED.value,
                detail=dict(raw),
            )
        if raw.get("duplicate"):
            return BridgeOpResult(
                ok=True, status=InboundStatus.DUPLICATE.value, detail=dict(raw)
            )
        if raw.get("confirmed") or raw.get("credited"):
            status = inbound_status_from_claim(
                {
                    "duplicate": bool(raw.get("duplicate")),
                    "credited": True,
                }
            )
            return BridgeOpResult(ok=True, status=status.value, detail=dict(raw))
        return BridgeOpResult(
            ok=False,
            status=InboundStatus.REJECTED.value,
            detail=dict(raw) if raw else {"error": "rejected"},
        )


def build_bridge_port(
    config: Any,
    db: Any,
    bus: Any = None,
    *,
    zk_gateway: Any = None,
) -> Union[NullBridgePort, RustBridgeAdapter, Any]:
    """Factory used by NodeOrchestrator — Null / Fake / Rust adapter."""
    if not bool(getattr(config, "bridge_enabled", False)):
        return NullBridgePort()

    mode = str(getattr(config, "bridge_mode", "rust") or "rust").lower()
    if mode == "fake":
        from bridge.fake_evm_bridge import FakeEvmBridge

        return FakeEvmBridge(config, zk_gateway=zk_gateway)

    from bridge.abs_bridge import RustBridge

    store = BridgeStoreAdapter(db)
    # Prefer store.raw for RustBridge (same concrete engine)
    inner = RustBridge(config, store.raw, bus)
    # Swap db to store adapter surface when methods are present
    inner.db = store.raw

    l1_rpc = LiveL1Rpc()
    validator = InboundMessageValidator(
        config=config, l1_rpc=l1_rpc, zk_gateway=zk_gateway
    )
    return RustBridgeAdapter(
        inner, validator=validator, store=store, l1_rpc=l1_rpc
    )


def normalize_bridge_http_result(result: Any) -> Dict[str, Any]:
    """HTTP helper: BridgeOpResult → legacy dict."""
    if hasattr(result, "as_legacy_dict"):
        return result.as_legacy_dict()
    if isinstance(result, dict):
        return result
    if result is True:
        return {"success": True}
    if result is False or result is None:
        return {"success": False}
    flagged = getattr(result, "success", None)
    if flagged is True or flagged is False:
        out = {"success": flagged}
        err = getattr(result, "error", None)
        if err:
            out["error"] = str(err)
        return out
    return {"success": False, "error": "bridge_result_not_boolean"}
