# bridge/validators.py — ADR 0010 inbound message validation
"""Receipt + replay + optional ZK — never mutates balances."""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from bridge.ports import (
    InboundEnvelope,
    L1RpcPort,
    ValidationResult,
)
from runtime.amount import money_abs


def compute_replay_key(from_chain: str, event_tx_hash: str, log_index: int = 0) -> str:
    material = f"{str(from_chain).strip().lower()}:{str(event_tx_hash).strip()}:{int(log_index or 0)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class InboundMessageValidator:
    """Default inbound gate for L1 → ABS credits."""

    def __init__(
        self,
        *,
        config: Any,
        l1_rpc: Optional[L1RpcPort] = None,
        zk_gateway: Any = None,
    ):
        self.config = config
        self.l1_rpc = l1_rpc
        self.zk_gateway = zk_gateway

    def validate(self, envelope: InboundEnvelope) -> ValidationResult:
        chain = str(envelope.from_chain or "").strip().lower()
        to_addr = str(envelope.to_addr or "").strip()
        tx_hash = str(envelope.event_tx_hash or "").strip()
        try:
            amount = money_abs(envelope.amount, field="amount")
        except (TypeError, ValueError):
            return ValidationResult(ok=False, reason="invalid_amount")

        if not tx_hash or tx_hash in ("0", "0x0", "0x" + "0" * 64):
            return ValidationResult(ok=False, reason="empty_event_tx_hash")
        if not to_addr:
            return ValidationResult(ok=False, reason="missing_recipient")
        if not chain:
            return ValidationResult(ok=False, reason="missing_from_chain")
        if amount <= 0:
            return ValidationResult(ok=False, reason="invalid_amount")

        replay_key = compute_replay_key(chain, tx_hash, int(envelope.log_index or 0))

        # Receipt / confirmation gates when L1 RPC port is wired.
        require_proof = bool(getattr(self.config, "bridge_require_l1_proof", False))
        min_conf = int(getattr(self.config, "bridge_min_confirmations", 0) or 0)
        if self.l1_rpc is not None and (require_proof or min_conf > 0 or envelope.receipt is not None):
            receipt = envelope.receipt
            if receipt is None:
                receipt = self.l1_rpc.get_tx_receipt(chain, tx_hash)
            if receipt is None:
                return ValidationResult(
                    ok=False, reason="receipt_missing", replay_key=replay_key
                )
            if not self.l1_rpc.receipt_status_ok(receipt):
                return ValidationResult(
                    ok=False, reason="receipt_status_failed", replay_key=replay_key
                )
            # Bind receipt hash when present.
            rh = str(
                receipt.get("transactionHash")
                or receipt.get("tx_hash")
                or receipt.get("hash")
                or ""
            ).strip().lower()
            if rh and rh not in (tx_hash.lower(),):
                # allow 0x-prefix normalize
                if rh.removeprefix("0x") != tx_hash.lower().removeprefix("0x"):
                    return ValidationResult(
                        ok=False, reason="receipt_hash_mismatch", replay_key=replay_key
                    )
            if min_conf > 0:
                conf = int(self.l1_rpc.get_confirmations(chain, tx_hash) or 0)
                if conf < min_conf:
                    return ValidationResult(
                        ok=False,
                        reason=f"insufficient_confirmations:{conf}<{min_conf}",
                        replay_key=replay_key,
                    )

        require_zk = bool(getattr(self.config, "bridge_require_inbound_zk", False))
        feature_zk = bool(getattr(self.config, "feature_zk", False))
        if require_zk and feature_zk:
            gw = self.zk_gateway
            if gw is None or not getattr(gw, "enabled", lambda: False)():
                return ValidationResult(
                    ok=False, reason="zk_required_unavailable", replay_key=replay_key
                )
            proof = envelope.zk_proof
            if not proof:
                return ValidationResult(
                    ok=False, reason="zk_proof_missing", replay_key=replay_key
                )
            ptype = str(proof.get("proof_type") or "knowledge")
            if not gw.verify_proof(proof, proof_type=ptype):
                return ValidationResult(
                    ok=False, reason="zk_proof_invalid", replay_key=replay_key
                )

        return ValidationResult(ok=True, replay_key=replay_key)


class PassthroughInboundValidator:
    """Minimal validator: shape + replay key only (no L1/ZK)."""

    def validate(self, envelope: InboundEnvelope) -> ValidationResult:
        tx_hash = str(envelope.event_tx_hash or "").strip()
        if not tx_hash:
            return ValidationResult(ok=False, reason="empty_event_tx_hash")
        try:
            if money_abs(envelope.amount, field="amount") <= 0:
                return ValidationResult(ok=False, reason="invalid_amount")
        except (TypeError, ValueError):
            return ValidationResult(ok=False, reason="invalid_amount")
        if not str(envelope.to_addr or "").strip():
            return ValidationResult(ok=False, reason="missing_recipient")
        key = compute_replay_key(
            envelope.from_chain, tx_hash, int(envelope.log_index or 0)
        )
        return ValidationResult(ok=True, replay_key=key)

