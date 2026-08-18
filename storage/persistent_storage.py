# -*- coding: utf-8 -*-
"""Legacy persistent storage wrapper for v47 tests."""
import json
import logging
import os
import shutil
from typing import Any, Dict, Optional

from storage.database import BlockchainDB

logger = logging.getLogger("PersistentStorage")


class PersistentStorage:
    def __init__(self, directory: str):
        self.directory = directory
        os.makedirs(directory, exist_ok=True)
        self.db_path = os.path.join(directory, "chain.db")
        self.db = BlockchainDB(self.db_path)
        self._snapshot_path = os.path.join(directory, "snapshot.json")

    def save_account_state(self, address: str, balance: float, nonce: int = 0) -> None:
        self.db.save_account(address, balance, nonce)

    def get_balance(self, address: str) -> float:
        return self.db.get_balance(address)

    def get_nonce(self, address: str) -> int:
        return self.db.get_nonce(address)

    def get_account_state(self, address: str) -> Dict:
        from runtime.amount import account_balance_abs, account_satoshi

        row = self.db.get_account(address)
        if row:
            return {
                "balance": account_balance_abs(row),
                "balance_satoshi": account_satoshi(row),
                "nonce": int(row.get("nonce", 0)),
            }
        return {"balance": 0.0, "balance_satoshi": 0, "nonce": 0}

    def update_balance(self, address: str, delta: float) -> float:
        # Delegate to DB dual-write path (satoshi + float); do not bump nonce here.
        return self.db.update_balance(address, delta)

    def save_block(self, block: Dict) -> bool:
        return self.db.save_block(block)

    def get_latest_block_number(self) -> int:
        return self.db.get_latest_block_number()

    def save_metadata(self, key: str, value: str) -> bool:
        self.db.save_metadata(key, value)
        return True

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self.db.get_metadata(key, default)

    def recover_from_crash(self) -> bool:
        return os.path.isfile(self.db_path)

    def create_snapshot(self, head_hash: str, height: int) -> bool:
        payload = {"head_hash": head_hash, "height": height}
        with open(self._snapshot_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        return True

    def restore_from_snapshot(self) -> Optional[Dict]:
        if not os.path.isfile(self._snapshot_path):
            return None
        with open(self._snapshot_path, encoding="utf-8") as f:
            return json.load(f)

    def chain_exists(self) -> bool:
        return self.get_latest_block_number() > 0

    def backup(self, backup_dir: str) -> bool:
        os.makedirs(backup_dir, exist_ok=True)
        dest = os.path.join(backup_dir, "chain.db")
        if os.path.isfile(self.db_path):
            shutil.copy2(self.db_path, dest)
            return True
        return False

    def close(self) -> None:
        self.db.close()

    def __del__(self):
        try:
            self.close()
        except Exception as exc:
            logger.warning("PersistentStorage.__del__ close failed: %s", exc)
