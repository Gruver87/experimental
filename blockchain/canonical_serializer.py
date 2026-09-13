# blockchain/canonical_serializer.py
# Детерминированная сериализация для консенсуса

import json
from typing import Any


def _field_satoshi(tx: dict, sat_key: str, abs_key: str) -> int:
    """Prefer explicit satoshi field; else Decimal-path to_satoshi (not IEEE×1e6)."""
    raw_sat = tx.get(sat_key)
    if raw_sat is not None:
        return int(raw_sat)
    from runtime.amount import to_satoshi

    return int(to_satoshi(tx.get(abs_key, 0) or 0))


class CanonicalSerializer:
    """Детерминированная JSON сериализация - всегда одинаковый результат"""

    @staticmethod
    def serialize(obj: Any) -> str:
        """Сериализует объект в детерминированный JSON"""
        return json.dumps(
            CanonicalSerializer._canonicalize(obj),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @staticmethod
    def _canonicalize(obj: Any) -> Any:
        """Рекурсивная канонизация объекта"""
        if isinstance(obj, dict):
            return {
                k: CanonicalSerializer._canonicalize(v)
                for k, v in sorted(obj.items())
            }
        if isinstance(obj, list):
            return [CanonicalSerializer._canonicalize(item) for item in obj]
        if isinstance(obj, float):
            # Legacy float leaf → satoshi via Decimal path (not raw IEEE×1e6).
            from runtime.amount import to_satoshi

            return int(to_satoshi(obj))
        return obj

    @staticmethod
    def serialize_block(block: dict) -> str:
        """Сериализация блока для хэширования"""
        canonical_block = {
            "height": block.get("height"),
            "previous_hash": block.get("previous_hash", "0" * 64),
            "timestamp": block.get("timestamp", 0),
            "miner": block.get("miner", ""),
            "nonce": block.get("nonce", 0),
            "transactions": [
                {
                    "hash": tx.get("hash", tx.get("tx_hash", "")),
                    "from": tx.get("from", tx.get("from_addr", "")),
                    "to": tx.get("to", tx.get("to_addr", "")),
                    "amount_satoshi": _field_satoshi(tx, "amount_satoshi", "amount"),
                    "fee_satoshi": _field_satoshi(tx, "fee_satoshi", "fee"),
                    "nonce": tx.get("nonce", 0),
                    "timestamp": tx.get("timestamp", 0),
                }
                for tx in sorted(
                    block.get("transactions", []),
                    key=lambda x: x.get("hash", x.get("tx_hash", "")),
                )
            ],
        }
        return CanonicalSerializer.serialize(canonical_block)


canonical_serializer = CanonicalSerializer()
