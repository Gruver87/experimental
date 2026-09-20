# storage/chain_storage.py
"""
Persistent storage for blocks and state (legacy JSON files).

Hot writes raise PersistError — never soft ``False`` (industrial fail-closed).
"""

import json
import os
import time
from typing import Optional, Dict, Any, List

from storage.types import PersistError


class ChainStorage:
    """Persistent blockchain storage"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.blocks_dir = os.path.join(data_dir, "blocks")
        self.state_dir = os.path.join(data_dir, "state")
        self.checkpoints_dir = os.path.join(data_dir, "checkpoints")

        os.makedirs(self.blocks_dir, exist_ok=True)
        os.makedirs(self.state_dir, exist_ok=True)
        os.makedirs(self.checkpoints_dir, exist_ok=True)

    def save_block(self, number: int, block: dict) -> bool:
        path = os.path.join(self.blocks_dir, f"{number}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(block, f, indent=2)
            return True
        except Exception as e:
            raise PersistError(
                f"Error saving block {number}: {e}",
                reason_code="persist_failed",
            ) from e

    def get_block(self, number: int) -> Optional[dict]:
        path = os.path.join(self.blocks_dir, f"{number}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def get_block_by_hash(self, block_hash: str) -> Optional[dict]:
        for filename in os.listdir(self.blocks_dir):
            if filename.endswith(".json"):
                with open(os.path.join(self.blocks_dir, filename), "r", encoding="utf-8") as f:
                    block = json.load(f)
                    if block.get("hash") == block_hash:
                        return block
        return None

    def get_latest_block(self) -> Optional[dict]:
        max_num = -1
        latest = None
        for filename in os.listdir(self.blocks_dir):
            if filename.endswith(".json"):
                try:
                    num = int(filename.replace(".json", ""))
                    if num > max_num:
                        max_num = num
                        with open(os.path.join(self.blocks_dir, filename), "r", encoding="utf-8") as f:
                            latest = json.load(f)
                except (ValueError, OSError, json.JSONDecodeError):
                    continue
        return latest

    def get_block_count(self) -> int:
        return len([f for f in os.listdir(self.blocks_dir) if f.endswith(".json")])

    def save_state(self, block_hash: str, state: dict) -> bool:
        path = os.path.join(self.state_dir, f"{block_hash}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            return True
        except Exception as e:
            raise PersistError(
                f"Error saving state {block_hash}: {e}",
                reason_code="persist_failed",
            ) from e

    def get_state(self, block_hash: str) -> Optional[dict]:
        path = os.path.join(self.state_dir, f"{block_hash}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def save_checkpoint(self, block_hash: str, checkpoint: dict) -> bool:
        path = os.path.join(self.checkpoints_dir, f"{block_hash}.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(checkpoint, f, indent=2)
            return True
        except Exception as e:
            raise PersistError(
                f"Error saving checkpoint {block_hash}: {e}",
                reason_code="persist_failed",
            ) from e

    def get_checkpoint(self, block_hash: str) -> Optional[dict]:
        path = os.path.join(self.checkpoints_dir, f"{block_hash}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def get_stats(self) -> dict:
        return {
            "total_blocks": self.get_block_count(),
            "state_snapshots": len(os.listdir(self.state_dir)) if os.path.exists(self.state_dir) else 0,
            "checkpoints": len(os.listdir(self.checkpoints_dir)) if os.path.exists(self.checkpoints_dir) else 0,
            "data_dir": self.data_dir,
        }

    def replace_chain(self, new_blocks: List[dict]) -> bool:
        """Replace entire chain backup atomically (temp dir -> swap)."""
        import shutil
        import tempfile

        if not isinstance(new_blocks, list):
            raise PersistError(
                "replace_chain requires a list of blocks",
                reason_code="persist_failed",
            )
        tmp_root = tempfile.mkdtemp(prefix="abs_chain_replace_", dir=self.data_dir)
        tmp_blocks = os.path.join(tmp_root, "blocks")
        os.makedirs(tmp_blocks, exist_ok=True)
        try:
            for block in new_blocks:
                number = int(block.get("number", block.get("height", -1)))
                if number < 0:
                    raise ValueError("block missing number/height")
                path = os.path.join(tmp_blocks, f"{number}.json")
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(block, f, indent=2)
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if not isinstance(loaded, dict):
                    raise ValueError(f"invalid block payload at {number}")
            backup = self.blocks_dir + ".prev"
            if os.path.isdir(backup):
                shutil.rmtree(backup)
            had_blocks = os.path.isdir(self.blocks_dir)
            if had_blocks:
                os.rename(self.blocks_dir, backup)
            try:
                os.rename(tmp_blocks, self.blocks_dir)
            except Exception:
                if had_blocks and os.path.isdir(backup) and not os.path.isdir(self.blocks_dir):
                    os.rename(backup, self.blocks_dir)
                raise
            if os.path.isdir(backup):
                shutil.rmtree(backup)
            print(f"[CHAIN] Chain replaced with {len(new_blocks)} blocks")
            return True
        except PersistError:
            raise
        except Exception as e:
            raise PersistError(
                f"Error replacing chain: {e}",
                reason_code="persist_failed",
            ) from e
        finally:
            if os.path.isdir(tmp_root):
                shutil.rmtree(tmp_root, ignore_errors=True)
