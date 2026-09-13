# core/components/zk_gateway.py — ZK boundary for Blockchain facade
"""ZkGatewayPort adapters (Null + features.zk wrap)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.components.ports import TxValidationResult, ZkGatewayPort


class NullZkGateway:
    """feature_zk=False — reject zk-marked txs, no proofs."""

    def enabled(self) -> bool:
        return False

    def validate_zk_tx(self, tx: Any) -> TxValidationResult:
        return TxValidationResult(valid=False, error="zk_disabled")

    def verify_proof(self, proof: Dict[str, Any], *, proof_type: str) -> bool:
        return False

    def system_info(self) -> Dict[str, Any]:
        return {"enabled": False, "backend": "null"}


class FeaturesZkGateway:
    """Thin adapter over ``features.zk.ZKProofSystem``."""

    def __init__(self, system: Any):
        self._system = system

    def enabled(self) -> bool:
        return self._system is not None

    def validate_zk_tx(self, tx: Any) -> TxValidationResult:
        if self._system is None:
            return TxValidationResult(valid=False, error="zk_unavailable")
        # Soft gate: zk txs carry proof in data/extra; absence is ok for non-zk txs.
        proof = getattr(tx, "zk_proof", None)
        if proof is None and isinstance(getattr(tx, "data", None), str):
            return TxValidationResult(valid=True, meta={"zk": "skipped"})
        if isinstance(proof, dict):
            ok = self.verify_proof(proof, proof_type=str(proof.get("proof_type") or "knowledge"))
            if not ok:
                return TxValidationResult(valid=False, error="zk_proof_invalid")
            return TxValidationResult(valid=True, meta={"zk": True})
        return TxValidationResult(valid=True)

    def verify_proof(self, proof: Dict[str, Any], *, proof_type: str) -> bool:
        if self._system is None:
            return False
        try:
            from features.zk import ZKProof

            zp = ZKProof.from_dict(proof) if isinstance(proof, dict) else proof
            ptype = str(proof_type or getattr(zp, "proof_type", "") or "knowledge")
            if ptype == "range":
                return bool(self._system.verify_range(zp))
            if ptype == "balance":
                amount = int(proof.get("amount", 0) or 0) if isinstance(proof, dict) else 0
                return bool(self._system.verify_balance(zp, amount))
            public_value = (
                int(proof.get("public_value", 0) or 0) if isinstance(proof, dict) else 0
            )
            return bool(self._system.verify_knowledge(zp, public_value))
        except Exception:
            return False

    def system_info(self) -> Dict[str, Any]:
        if self._system is None:
            return {"enabled": False, "backend": "features.zk"}
        info: Dict[str, Any] = {}
        if hasattr(self._system, "get_system_info"):
            try:
                info = dict(self._system.get_system_info() or {})
            except Exception as exc:
                # Wave M: probe failure must not paint ZK enabled.
                return {
                    "enabled": False,
                    "backend": "features.zk",
                    "error": str(exc),
                }
        info["enabled"] = True
        info["backend"] = "features.zk"
        return info


def build_zk_gateway(system: Optional[Any] = None, *, enabled: bool = True) -> ZkGatewayPort:
    if not enabled or system is None:
        return NullZkGateway()
    return FeaturesZkGateway(system)
