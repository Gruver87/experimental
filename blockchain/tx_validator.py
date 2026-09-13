# blockchain/tx_validator.py
# Legacy validator — prefer core.components.TxPipeline (Blockchain facade).
# Kept for older callers; new code should use Blockchain.validate_transaction.

import time
from typing import Dict, Tuple, Optional

from runtime.amount import SATOSHI_MULTIPLIER, to_satoshi


class TransactionValidator:
    """Полная валидация транзакций перед добавлением в блок или мемпул."""

    MAX_TRANSACTION_SIZE_BYTES = 100 * 1024
    MIN_TRANSACTION_FEE_SATOSHI = 1000
    MAX_TRANSACTION_AMOUNT_SATOSHI = 21_000_000 * SATOSHI_MULTIPLIER

    @classmethod
    def validate(
        cls,
        tx: dict,
        state_manager,
        mempool=None,
        chain_id: int = 1,
        require_signature: bool = False,
    ) -> Tuple[bool, str]:
        if not cls._validate_basic_fields(tx):
            return False, "Missing required fields (from, to, amount)"

        from_addr = tx.get("from", tx.get("from_addr", ""))
        to_addr = tx.get("to", tx.get("to_addr", ""))

        if not cls._validate_address(from_addr):
            return False, f"Invalid sender address: {from_addr}"
        if not cls._validate_address(to_addr):
            return False, f"Invalid receiver address: {to_addr}"

        amount_satoshi = tx.get(
            "amount_satoshi",
            to_satoshi(tx.get("amount", tx.get("value", 0))),
        )
        data = str(tx.get("data", tx.get("input", "")) or "").strip()
        zero_addr = "0x0000000000000000000000000000000000000000"
        is_evm_deploy = bool(data.replace("0x", "")) and to_addr.lower() == zero_addr
        if amount_satoshi <= 0 and not is_evm_deploy:
            return False, "Amount must be positive"
        if amount_satoshi > cls.MAX_TRANSACTION_AMOUNT_SATOSHI:
            return False, "Amount exceeds maximum"

        fee_satoshi = tx.get("fee_satoshi", to_satoshi(tx.get("fee", 0)))
        if fee_satoshi < cls.MIN_TRANSACTION_FEE_SATOSHI:
            return False, (
                f"Fee too low. Minimum: {cls.MIN_TRANSACTION_FEE_SATOSHI / SATOSHI_MULTIPLIER} ABS"
            )

        if len(str(tx)) > cls.MAX_TRANSACTION_SIZE_BYTES:
            return False, "Transaction too large"

        account = state_manager.get_account(from_addr)
        current_nonce = account.nonce if account else 0
        tx_nonce = int(tx.get("nonce", 0))
        if tx_nonce != current_nonce:
            return False, f"Invalid nonce. Expected: {current_nonce}, got: {tx_nonce}"

        balance_satoshi = state_manager.get_balance_satoshi(from_addr)
        total_cost = amount_satoshi + fee_satoshi
        if balance_satoshi < total_cost:
            return False, (
                f"Insufficient balance. Required: {total_cost / SATOSHI_MULTIPLIER} ABS, "
                f"Available: {balance_satoshi / SATOSHI_MULTIPLIER} ABS"
            )

        tx_hash = tx.get("hash", tx.get("tx_hash", ""))
        if mempool and tx_hash and mempool.has_transaction(tx_hash):
            return False, "Transaction already in mempool"

        signature = tx.get("signature", "")
        public_key = tx.get("public_key", "")
        eth_signed = bool(tx.get("eth_signed"))
        if require_signature and not signature and not eth_signed:
            return False, "Signature required"
        if eth_signed:
            try:
                ok = cls._verify_signature(tx, signature, chain_id)
            except RuntimeError as exc:
                return False, str(exc)
            if not ok:
                return False, "Invalid signature"
        elif signature:
            if not public_key:
                return False, "public_key required with signature"
            try:
                ok = cls._verify_signature(tx, signature, chain_id)
            except RuntimeError as exc:
                return False, str(exc)
            if not ok:
                return False, "Invalid signature"

        return True, "OK"

    @classmethod
    def _validate_basic_fields(cls, tx: dict) -> bool:
        has_from = "from" in tx or "from_addr" in tx
        has_to = "to" in tx or "to_addr" in tx
        has_amount = "amount" in tx or "value" in tx or "amount_satoshi" in tx
        return has_from and has_to and has_amount

    @classmethod
    def _validate_address(cls, address: str) -> bool:
        if not address or len(address) < 10:
            return False
        if address.startswith("0x") and len(address) != 42:
            return False
        return True

    @classmethod
    def _verify_signature(cls, tx: dict, signature: str, chain_id: int) -> bool:
        """Return True/False for crypto result; raise RuntimeError if verify unavailable.

        Wave P: probe/import/backend failures must not paint as Invalid signature.
        """
        if tx.get("eth_signed"):
            try:
                from crypto.eth_tx import verify_eth_transaction_dict
                return bool(verify_eth_transaction_dict(tx))
            except RuntimeError:
                raise
            except (ValueError, TypeError):
                return False
            except Exception as exc:
                raise RuntimeError(f"signature verify unavailable: {exc}") from exc
        try:
            from crypto.wallet import verify_transaction_signature
            from runtime.amount import from_satoshi_float

            raw_value = tx.get("value", tx.get("amount", 0))
            if tx.get("amount_satoshi") is not None or tx.get("value_satoshi") is not None:
                sat = int(tx.get("amount_satoshi", tx.get("value_satoshi")))
                value = from_satoshi_float(sat)
            else:
                try:
                    value = (
                        int(raw_value)
                        if float(raw_value) == int(float(raw_value))
                        else float(raw_value)
                    )
                except (TypeError, ValueError):
                    return False
            tx_dict = {
                "from": tx.get("from", tx.get("from_addr", "")),
                "to": tx.get("to", tx.get("to_addr", "")),
                "value": value,
                "nonce": int(tx.get("nonce", 0)),
                "chain_id": chain_id,
                "signature": signature,
                "public_key": tx.get("public_key", ""),
                "data": tx.get("data", tx.get("input", "")),
                "gas_limit": tx.get("gas_limit") or tx.get("gas", 21000),
            }
            return bool(verify_transaction_signature(tx_dict))
        except RuntimeError:
            raise
        except (ValueError, TypeError):
            return False
        except Exception as exc:
            raise RuntimeError(f"signature verify unavailable: {exc}") from exc
