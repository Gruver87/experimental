# consensus/finality_beacon.py
"""
Beacon Chain Finality Engine — Correct Casper FFG
- Checkpoint-based finality
- Event-driven justification and finalization
- No backward inconsistencies
Hot path prefers abs_native FFG kernels with Python fallback.
"""

from typing import Dict, Optional, Set
import json
import logging

from crypto import native

logger = logging.getLogger("abs.ffg")


def _native_required() -> bool:
    return bool(native.native_crypto_status(required=False).get("required"))


def _native_fb(op: str, exc: BaseException) -> None:
    logger.warning("native %s failed; Python path: %s", op, exc)
    if _native_required():
        raise exc


class BeaconFinality:
    """
    Ethereum-style Beacon Chain finality:
    - Checkpoints are epochs
    - Epoch N becomes justified with 2/3 majority
    - Epoch N becomes finalized when epoch N+1 is justified
    """

    def __init__(self, epoch_size: int = 3, threshold_ratio: float = 2/3):
        self.epoch_size = epoch_size
        self.threshold_ratio = threshold_ratio
        self.total_stake = 0
        
        # Checkpoint votes: epoch -> block -> weight
        self.votes: Dict[int, Dict[str, int]] = {}
        
        # State
        self.justified_checkpoint: Optional[int] = None
        self.justified_block: Optional[str] = None
        self.finalized_checkpoint: Optional[int] = None
        self.finalized_block: Optional[str] = None
        
        # History
        self.justified_epochs: Set[int] = set()
        self.finalized_epochs: Set[int] = set()
        self.justified_blocks: Dict[int, str] = {}

    def set_total_stake(self, total_stake: int):
        self.total_stake = total_stake

    def _get_epoch(self, block_number: int) -> int:
        if native.native_available() and hasattr(native, "fe_epoch"):
            try:
                return int(native.fe_epoch(int(block_number), int(self.epoch_size)))
            except Exception as exc:
                _native_fb("fe_epoch", exc)
        return block_number // self.epoch_size

    def _get_threshold(self) -> int:
        if native.native_available() and hasattr(native, "ffg_threshold"):
            try:
                return int(native.ffg_threshold(int(self.total_stake), 2, 3))
            except Exception as exc:
                _native_fb("ffg_threshold", exc)
        return int(self.total_stake * self.threshold_ratio)

    def _get_best_checkpoint(self, epoch: int) -> Optional[tuple]:
        """Returns (block_hash, weight) for best checkpoint in epoch"""
        if epoch not in self.votes:
            return None
        if native.native_available() and hasattr(native, "ffg_best_checkpoint"):
            try:
                best = native.ffg_best_checkpoint(
                    json.dumps(self.votes[epoch], separators=(",", ":"), ensure_ascii=False)
                )
                if best is None:
                    return None
                return (str(best[0]), int(best[1]))
            except Exception as exc:
                _native_fb("ffg_best_checkpoint", exc)
        return max(self.votes[epoch].items(), key=lambda x: x[1])

    def add_vote(self, validator_id: str, block_hash: str, slot: int, weight: int):
        """
        Add validator vote and trigger finality evaluation.
        Called every time a validator attests.
        """
        epoch = self._get_epoch(slot)

        if epoch not in self.votes:
            self.votes[epoch] = {}

        if native.native_available() and hasattr(native, "ffg_accumulate_vote"):
            try:
                updated = native.ffg_accumulate_vote(
                    json.dumps(self.votes[epoch], separators=(",", ":"), ensure_ascii=False),
                    str(block_hash),
                    int(weight),
                )
                self.votes[epoch] = {str(k): int(v) for k, v in json.loads(updated).items()}
            except Exception as exc:
                _native_fb("ffg_accumulate_vote", exc)
                self.votes[epoch][block_hash] = self.votes[epoch].get(block_hash, 0) + weight
        else:
            self.votes[epoch][block_hash] = self.votes[epoch].get(block_hash, 0) + weight

        self._evaluate(epoch)
        return True

    def _evaluate(self, epoch: int):
        """Evaluate justification and finalization for checkpoint"""
        if native.native_available() and hasattr(native, "ffg_evaluate_epoch") and epoch in self.votes:
            try:
                raw = native.ffg_evaluate_epoch(
                    int(epoch),
                    json.dumps(self.votes[epoch], separators=(",", ":"), ensure_ascii=False),
                    int(self.total_stake),
                    json.dumps(sorted(self.justified_epochs)),
                    json.dumps(sorted(self.finalized_epochs)),
                    2,
                    3,
                )
                result = json.loads(raw)
                if result.get("justified_block") and epoch not in self.justified_epochs:
                    block_hash = str(result["justified_block"])
                    self.justified_epochs.add(epoch)
                    self.justified_blocks[epoch] = block_hash
                    self.justified_checkpoint = epoch
                    self.justified_block = block_hash
                if result.get("finalize_prev"):
                    prev_epoch = epoch - 1
                    if (
                        prev_epoch in self.justified_epochs
                        and prev_epoch not in self.finalized_epochs
                    ):
                        self.finalized_epochs.add(prev_epoch)
                        self.finalized_checkpoint = prev_epoch
                        self.finalized_block = self.justified_blocks.get(prev_epoch)
                return
            except Exception as exc:
                _native_fb("ffg_evaluate_epoch", exc)

        best = self._get_best_checkpoint(epoch)
        if not best:
            return

        block_hash, weight = best
        threshold = self._get_threshold()

        if weight >= threshold:
            if epoch not in self.justified_epochs:
                self.justified_epochs.add(epoch)
                self.justified_blocks[epoch] = block_hash

                self.justified_checkpoint = epoch
                self.justified_block = block_hash

                prev_epoch = epoch - 1
                if prev_epoch in self.justified_epochs and prev_epoch not in self.finalized_epochs:
                    self.finalized_epochs.add(prev_epoch)
                    self.finalized_checkpoint = prev_epoch
                    self.finalized_block = self.justified_blocks.get(prev_epoch)

    def is_justified(self, epoch: int) -> bool:
        return epoch in self.justified_epochs

    def is_finalized(self, block_number: int) -> bool:
        """Check if a block is in a finalized epoch"""
        epoch = self._get_epoch(block_number)
        return epoch in self.finalized_epochs

    def get_state(self) -> dict:
        return {
            "justified_checkpoint": self.justified_checkpoint,
            "justified_block": self.justified_block,
            "finalized_checkpoint": self.finalized_checkpoint,
            "finalized_block": self.finalized_block,
            "justified_epochs": sorted(list(self.justified_epochs)),
            "finalized_epochs": sorted(list(self.finalized_epochs))
        }

    def get_stats(self) -> dict:
        return {
            "total_stake": self.total_stake,
            "justified_epochs": len(self.justified_epochs),
            "finalized_epochs": len(self.finalized_epochs),
            "justified_list": sorted(list(self.justified_epochs)),
            "finalized_list": sorted(list(self.finalized_epochs))
        }
