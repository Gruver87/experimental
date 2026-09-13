# core/components/tx_pipeline.py — Mempool / block tx validation pipeline
"""Extracted from Blockchain.validate_transaction / signature gates."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from core.components.ports import TxValidationResult, ZkGatewayPort
from core.components.zk_gateway import NullZkGateway


class TxPipeline:
    """Mempool + block admit validation (signatures, nonce, funds, EVM deploy, ZK)."""

    def __init__(
        self,
        *,
        config: Any,
        storage: Any,
        zk_gateway: Optional[ZkGatewayPort] = None,
        get_pool_locks: Optional[Callable[[], Any]] = None,
        get_evm: Optional[Callable[[], Any]] = None,
    ):
        self.config = config
        self.storage = storage
        self.zk_gateway: ZkGatewayPort = zk_gateway or NullZkGateway()
        self._get_pool_locks = get_pool_locks or (lambda: None)
        self._get_evm = get_evm or (lambda: None)

    @property
    def pool_locks(self) -> Any:
        return self._get_pool_locks()

    @property
    def evm(self) -> Any:
        return self._get_evm()

    def validate_for_mempool(self, tx: Any) -> TxValidationResult:
        return self._validate(tx, expected_nonce=None)

    def validate_for_block(self, tx: Any, *, expected_nonce: int) -> TxValidationResult:
        return self._validate(tx, expected_nonce=int(expected_nonce))

    def _validate(
        self, tx: Any, *, expected_nonce: Optional[int]
    ) -> TxValidationResult:
        if not tx.from_addr or not tx.to_addr:
            return TxValidationResult(valid=False, error="missing_address")
        if tx.value < 0:
            return TxValidationResult(valid=False, error="negative_value")
        if tx.gas < self.config.base_gas_price:
            return TxValidationResult(valid=False, error="gas_too_low")

        require_sigs = bool(getattr(self.config, "require_signatures", False))
        # Cheap crypto refuse before state lookups — verify sig before
        # nonce/balance DB lookups (v1.3.143 / ADR 0021 phase 1).
        if require_sigs or bool(tx.signature):
            sig_check = self.verify_tx_signature(tx)
            if not sig_check.valid:
                return sig_check

        tip_nonce = self.storage.get_nonce(tx.from_addr)
        want_nonce = tip_nonce if expected_nonce is None else int(expected_nonce)
        balance_sat = int(self.storage.get_balance_satoshi(tx.from_addr))

        from runtime.amount import (
            can_afford_transfer_sat,
            from_satoshi_float,
            plan_transfer_fees_sat,
        )

        fee_plan = plan_transfer_fees_sat(
            tx.gas,
            self.config.gas_price_wei,
            self.config.burn_rate,
            tx.value,
        )
        value_sat = int(fee_plan["value_sat"])
        fee_sat = int(fee_plan["fee_sat"])
        total_cost_sat = int(fee_plan["total_cost_sat"])
        total_cost = from_satoshi_float(total_cost_sat)
        balance = from_satoshi_float(balance_sat)

        # ADR 0021 phase 1: optional Rust post-sig kernel on Python-built snapshot.
        # Fallback keeps historical Python nonce/balance refuse semantics.
        snapshot = {"nonce": int(want_nonce), "balance_sat": balance_sat}
        kernel_tx = {
            "from_addr": str(tx.from_addr),
            "to_addr": str(tx.to_addr),
            "nonce": int(tx.nonce),
            "value_sat": value_sat,
            "fee_sat": fee_sat,
            "gas_limit": int(getattr(tx, "gas", 0) or 0),
        }
        kernel = self._post_sig_kernel_check(snapshot, kernel_tx)
        if kernel is not None:
            if not kernel.valid:
                return kernel
        else:
            if tx.nonce != want_nonce:
                return TxValidationResult(
                    valid=False,
                    error=f"nonce_mismatch (got {tx.nonce}, expected {want_nonce})",
                )
            if not can_afford_transfer_sat(balance_sat, total_cost_sat):
                return TxValidationResult(valid=False, error="insufficient_funds")

        locks = self.pool_locks
        if locks:
            allowed, reason = locks.is_outgoing_allowed(
                tx.from_addr, total_cost, balance
            )
            if not allowed:
                return TxValidationResult(valid=False, error=str(reason))

        if not require_sigs and not tx.signature:
            sig_check = self.verify_tx_signature(tx)
            if not sig_check.valid:
                return sig_check

        deploy_check = self._validate_evm_deploy_bytecode(tx)
        if not deploy_check.valid:
            return deploy_check

        if self.zk_gateway.enabled() and getattr(tx, "zk_proof", None):
            zk = self.zk_gateway.validate_zk_tx(tx)
            if not zk.valid:
                return zk

        return TxValidationResult(valid=True)

    def _post_sig_kernel_check(
        self, snapshot: Dict[str, int], kernel_tx: Dict[str, Any]
    ) -> Optional[TxValidationResult]:
        """Run ADR 0021 Rust/Python kernel; None = caller must use legacy path."""
        try:
            from crypto import native

            if not hasattr(native, "mempool_validate_post_sig"):
                return None
            # Prefer native when available; Python mirror always exists.
            out = native.mempool_validate_post_sig(snapshot, kernel_tx)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "mempool_validate_post_sig failed — legacy path: %s", exc
            )
            return None
        if not isinstance(out, dict) or "accept" not in out:
            return None
        if out.get("accept"):
            return TxValidationResult(valid=True, meta={"mempool_kernel": "ok"})
        reason = str(out.get("reason") or "mempool_kernel_refuse")
        want = int(snapshot.get("nonce", 0))
        got = int(kernel_tx.get("nonce", -1))
        if reason == "nonce_mismatch":
            return TxValidationResult(
                valid=False,
                error=f"nonce_mismatch (got {got}, expected {want})",
                meta={"mempool_kernel": reason},
            )
        if reason == "insufficient_balance":
            return TxValidationResult(
                valid=False,
                error="insufficient_funds",
                meta={"mempool_kernel": reason},
            )
        return TxValidationResult(
            valid=False, error=reason, meta={"mempool_kernel": reason}
        )

    def _is_evm_deploy_tx(self, tx: Any) -> bool:
        if not tx.data or not self.evm:
            return False
        from execution.evm_precompiles import is_precompile

        if is_precompile(getattr(tx, "to_addr", "") or ""):
            return False
        target_acct = self.storage.get_account(tx.to_addr)
        if target_acct and target_acct.get("code"):
            return False
        deploy_data = (tx.data or "").strip()
        hex_body = deploy_data.replace("0x", "")
        return bool(deploy_data and len(hex_body) >= 4 and len(hex_body) % 2 == 0)

    def _validate_evm_deploy_bytecode(self, tx: Any) -> TxValidationResult:
        if not self._is_evm_deploy_tx(tx):
            return TxValidationResult(valid=True)
        # ADR 0021 phase 3: Rust admit kernel (Python validator callback fallback).
        try:
            from crypto import native

            out = native.mempool_admit_evm_deploy(str(tx.data or ""))
            if isinstance(out, dict) and "accept" in out:
                if out.get("accept"):
                    return TxValidationResult(
                        valid=True, meta={"mempool_admit_evm": "ok"}
                    )
                reason = str(out.get("reason") or "unsupported_evm_bytecode:invalid")
                return TxValidationResult(
                    valid=False,
                    error=reason,
                    meta={"mempool_admit_evm": reason},
                )
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning(
                "mempool_admit_evm_deploy failed — python validator: %s", exc
            )
        from execution.evm_bytecode_validator import validate_bytecode_hex

        v = validate_bytecode_hex(tx.data)
        if v.get("valid"):
            return TxValidationResult(valid=True)
        bad = v.get("unsupported") or []
        name = bad[0].get("name", "?") if bad else v.get("error", "invalid")
        return TxValidationResult(
            valid=False, error=f"unsupported_evm_bytecode:{name}"
        )

    def verify_tx_signature(self, tx: Any) -> TxValidationResult:
        require = getattr(self.config, "require_signatures", False)
        if not tx.signature:
            if require:
                return TxValidationResult(valid=False, error="missing_signature")
            return TxValidationResult(valid=True)
        if not tx.public_key:
            return TxValidationResult(valid=False, error="missing_public_key")
        try:
            from crypto.wallet import verify_transaction_signature

            tx_dict = {
                "from": tx.from_addr,
                "to": tx.to_addr,
                "value": int(tx.value) if tx.value == int(tx.value) else tx.value,
                "nonce": tx.nonce,
                "chain_id": self.config.chain_id,
                "signature": tx.signature,
                "public_key": tx.public_key,
                "data": tx.data or "",
                "gas_limit": tx.gas,
            }
            if not verify_transaction_signature(tx_dict):
                return TxValidationResult(valid=False, error="invalid_signature")
        except Exception as e:
            return TxValidationResult(
                valid=False, error=f"signature_check_failed: {e}"
            )
        return TxValidationResult(valid=True)

    def verify_signatures(self, block: Any) -> TxValidationResult:
        require = getattr(self.config, "require_signatures", False)
        signed_payloads = []
        signed_txs = []

        for tx in block.transactions:
            if not tx.signature:
                if require:
                    return TxValidationResult(
                        valid=False, error=f"missing_signature:{tx.hash}"
                    )
                continue
            if not tx.public_key:
                return TxValidationResult(
                    valid=False, error=f"missing_public_key:{tx.hash}"
                )
            signed_txs.append(tx)
            signed_payloads.append(
                {
                    "from": tx.from_addr,
                    "to": tx.to_addr,
                    "value": int(tx.value) if tx.value == int(tx.value) else tx.value,
                    "nonce": tx.nonce,
                    "chain_id": self.config.chain_id,
                    "signature": tx.signature,
                    "public_key": tx.public_key,
                    "data": tx.data or "",
                    "gas_limit": tx.gas,
                }
            )

        if not signed_payloads:
            return TxValidationResult(valid=True)

        try:
            from crypto.wallet import verify_transaction_signatures_batch

            results = verify_transaction_signatures_batch(signed_payloads)
        except Exception as e:
            return TxValidationResult(
                valid=False, error=f"signature_batch_failed: {e}"
            )

        for tx, ok in zip(signed_txs, results):
            if not ok:
                return TxValidationResult(
                    valid=False, error=f"invalid_signature:{tx.hash}"
                )

        return TxValidationResult(valid=True)

    def validate_for_block_cursor(
        self, tx: Any, nonce_cursor: Dict[str, int]
    ) -> TxValidationResult:
        expected = nonce_cursor.get(tx.from_addr, self.storage.get_nonce(tx.from_addr))
        if tx.nonce != expected:
            return TxValidationResult(valid=False, error="nonce_mismatch_in_block")
        return self.validate_for_block(tx, expected_nonce=int(expected))
