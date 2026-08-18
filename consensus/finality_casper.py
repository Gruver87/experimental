# consensus/finality_casper.py
"""
Casper FFG Finality — Two-Step Rule
Epoch N is finalized ONLY when epoch N+1 is also justified

Hot path prefers abs_native FFG kernels with Python fallback.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Set, Optional

from crypto import native

logger = logging.getLogger("abs.ffg")


def _native_required() -> bool:
    return bool(native.native_crypto_status(required=False).get("required"))


def _native_fb(op: str, exc: BaseException) -> None:
    logger.warning("native %s failed; Python path: %s", op, exc)
    if _native_required():
        raise exc


class CasperFinality:
    """
    Correct Casper FFG implementation:
    - Justified epochs are tracked as a set
    - Epoch N becomes finalized when epoch N+1 is justified
    - Finality requires 2 consecutive justified epochs
    """

    def __init__(self, threshold_ratio: float = 2 / 3):
        self.threshold_ratio = threshold_ratio
        self.epoch_votes: Dict[int, Dict[str, int]] = {}
        self.total_stake = 0

        self.justified_epochs: Set[int] = set()
        self.finalized_epochs: Set[int] = set()
        self.justified_blocks: Dict[int, str] = {}

    def set_total_stake(self, total_stake: int):
        self.total_stake = total_stake

    def add_vote(self, epoch: int, block_hash: str, weight: int):
        """Add validator vote and evaluate justification/finalization"""
        if epoch not in self.epoch_votes:
            self.epoch_votes[epoch] = {}
        if native.native_available() and hasattr(native, "ffg_accumulate_vote"):
            try:
                updated = native.ffg_accumulate_vote(
                    json.dumps(
                        self.epoch_votes[epoch],
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                    str(block_hash),
                    int(weight),
                )
                self.epoch_votes[epoch] = {
                    str(k): int(v) for k, v in json.loads(updated).items()
                }
            except Exception as exc:
                _native_fb("ffg_accumulate_vote", exc)
                self.epoch_votes[epoch][block_hash] = (
                    self.epoch_votes[epoch].get(block_hash, 0) + weight
                )
        else:
            self.epoch_votes[epoch][block_hash] = (
                self.epoch_votes[epoch].get(block_hash, 0) + weight
            )

        self._evaluate(epoch)
        return True

    def _get_threshold(self) -> int:
        if native.native_available() and hasattr(native, "ffg_threshold"):
            try:
                return int(native.ffg_threshold(int(self.total_stake), 2, 3))
            except Exception as exc:
                _native_fb("ffg_threshold", exc)
        return int(self.total_stake * self.threshold_ratio)

    def _get_best_block(self, epoch: int) -> Optional[tuple]:
        if epoch not in self.epoch_votes:
            return None
        if native.native_available() and hasattr(native, "ffg_best_checkpoint"):
            try:
                best = native.ffg_best_checkpoint(
                    json.dumps(
                        self.epoch_votes[epoch],
                        separators=(",", ":"),
                        ensure_ascii=False,
                    )
                )
                if best is None:
                    return None
                return (str(best[0]), int(best[1]))
            except Exception as exc:
                _native_fb("ffg_best_checkpoint", exc)
        return max(self.epoch_votes[epoch].items(), key=lambda x: x[1])

    def _justify_epoch(self, epoch: int, block_hash: str):
        if epoch not in self.justified_epochs:
            self.justified_epochs.add(epoch)
            self.justified_blocks[epoch] = block_hash

    def _try_finalize(self, epoch: int):
        prev_epoch = epoch - 1
        if prev_epoch in self.justified_epochs and prev_epoch not in self.finalized_epochs:
            self.finalized_epochs.add(prev_epoch)

    def _evaluate(self, epoch: int):
        if (
            native.native_available()
            and hasattr(native, "ffg_evaluate_epoch")
            and epoch in self.epoch_votes
        ):
            try:
                raw = native.ffg_evaluate_epoch(
                    int(epoch),
                    json.dumps(
                        self.epoch_votes[epoch],
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ),
                    int(self.total_stake),
                    json.dumps(sorted(self.justified_epochs)),
                    json.dumps(sorted(self.finalized_epochs)),
                    2,
                    3,
                )
                result = json.loads(raw)
                if result.get("justified_block") and epoch not in self.justified_epochs:
                    self._justify_epoch(epoch, str(result["justified_block"]))
                if result.get("finalize_prev"):
                    self._try_finalize(epoch)
                return
            except Exception as exc:
                _native_fb("ffg_evaluate_epoch", exc)

        best = self._get_best_block(epoch)
        if not best:
            return

        block_hash, weight = best
        threshold = self._get_threshold()

        if weight >= threshold:
            self._justify_epoch(epoch, block_hash)
            self._try_finalize(epoch)

    def update(self, epoch: int) -> dict:
        self._evaluate(epoch)
        return self.get_state(epoch)

    def get_state(self, epoch: int) -> dict:
        return {
            "epoch": epoch,
            "justified": epoch in self.justified_epochs,
            "finalized": epoch in self.finalized_epochs,
            "justified_block": self.justified_blocks.get(epoch),
            "justified_epochs": sorted(list(self.justified_epochs)),
            "finalized_epochs": sorted(list(self.finalized_epochs)),
            "native_ffg": bool(
                native.native_available() and hasattr(native, "ffg_evaluate_epoch")
            ),
        }

    def is_finalized(self, block_number: int, epoch_mgr) -> bool:
        epoch = epoch_mgr.get_epoch(block_number)
        return epoch in self.finalized_epochs

    def get_finalized_epochs(self) -> Set[int]:
        return self.finalized_epochs

    def get_justified_epochs(self) -> Set[int]:
        return self.justified_epochs

    def get_stats(self) -> dict:
        return {
            "total_stake": self.total_stake,
            "justified_epochs": len(self.justified_epochs),
            "finalized_epochs": len(self.finalized_epochs),
            "justified_list": sorted(list(self.justified_epochs)),
            "finalized_list": sorted(list(self.finalized_epochs)),
            "native_ffg": bool(
                native.native_available() and hasattr(native, "ffg_evaluate_epoch")
            ),
        }
