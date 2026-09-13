# execution/block_validator.py
"""
Block Validator — validates blocks before import
"""

import time
from typing import Dict, Optional, Tuple


class BlockValidator:
    """Validates block structure before state replay in Blockchain.add_block."""

    def __init__(self, state_engine, mempool):
        self.state = state_engine
        self.mempool = mempool

    def validate_block(
        self,
        block: dict,
        parent_block: Optional[dict] = None,
        strict_timestamp: bool = True,
    ) -> Tuple[bool, str]:
        b = self._normalize(block)
        height = b["number"]

        for field in ("number", "parent_hash", "timestamp", "miner", "transactions"):
            if field not in b:
                return False, f"Missing field: {field}"

        if height > 1 and not parent_block:
            return False, "Parent block not found"

        if parent_block and b["parent_hash"] != parent_block.get("hash"):
            return False, "Parent hash mismatch"

        if parent_block:
            parent_h = parent_block.get("height", parent_block.get("number", 0))
            if height != parent_h + 1:
                return False, f"Invalid block number: {height}"

        if b["timestamp"] > int(time.time()) + 120:
            return False, "Timestamp too far in future"

        if parent_block:
            parent_ts = int(parent_block.get("timestamp", 0) or 0)
            child_ts = int(b["timestamp"] or 0)
            if strict_timestamp:
                if child_ts <= parent_ts:
                    return False, "Timestamp not increasing"
            elif child_ts < parent_ts:
                return False, "Timestamp regressed"

        for tx in b.get("transactions", []):
            valid, msg = self._validate_transaction_shape(tx)
            if not valid:
                return False, f"Invalid transaction {tx.get('hash', '?')}: {msg}"

        if b.get("tx_root") and b.get("transactions"):
            computed = self._compute_tx_root(b["transactions"])
            expected = b["tx_root"]
            if computed != expected and computed[: len(expected)] != expected:
                return False, f"Tx root mismatch: expected {computed}"

        return True, ""

    def _normalize(self, block: dict) -> dict:
        b = dict(block)
        if "number" not in b:
            b["number"] = b.get("height", 0)
        if "height" not in b:
            b["height"] = b["number"]
        if "miner" not in b:
            b["miner"] = b.get("proposer", "")
        if "proposer" not in b:
            b["proposer"] = b["miner"]
        txs = []
        for tx in b.get("transactions", []):
            t = dict(tx)
            t.setdefault("from", t.get("from_addr", ""))
            t.setdefault("to", t.get("to_addr", ""))
            t.setdefault("value", t.get("amount", 0))
            t.setdefault("hash", t.get("tx_hash", ""))
            txs.append(t)
        b["transactions"] = txs
        return b

    def _validate_transaction_shape(self, tx: dict) -> Tuple[bool, str]:
        for field in ("hash", "from", "to", "nonce"):
            if field not in tx or tx[field] in ("", None):
                alt = {"from": "from_addr", "to": "to_addr", "hash": "tx_hash"}.get(field)
                if not alt or alt not in tx:
                    return False, f"Missing field: {field}"
        # Wave L: satoshi gate — refuse unparseable / negative (no float compare).
        from runtime.amount import to_satoshi

        try:
            value_sat = int(to_satoshi(tx.get("value", tx.get("amount", 0))))
        except (TypeError, ValueError):
            return False, "Unparseable value"
        if value_sat < 0:
            return False, "Negative value"
        return True, ""

    def _compute_tx_root(self, transactions: list) -> str:
        from crypto.merkle import merkle_root

        items = [
            tx.get("hash", tx.get("tx_hash", ""))
            for tx in transactions
        ] if transactions else []
        return merkle_root(items) if items else merkle_root(["empty"])
