# consensus/lmd.py
"""
LMD Table — Latest Message Driven
Only tracks latest attestation per validator
Strict slot-based overwrite

Weight aggregation prefers abs_native.lmd_compute_weights when available.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional, Tuple

from crypto import native

logger = logging.getLogger("abs.lmd")


def _native_required() -> bool:
    return bool(native.native_crypto_status(required=False).get("required"))


def _native_fb(op: str, exc: BaseException) -> None:
    logger.warning("native %s failed; Python path: %s", op, exc)
    if _native_required():
        raise exc


class LMDTable:
    """
    Strict LMD: only latest attestation per validator
    Slot-based: newer slot always overwrites older
    """

    def __init__(self):
        # validator -> (block_hash, slot)
        self.latest_vote: Dict[str, Tuple[str, int]] = {}
        self.validator_stake: Dict[str, int] = {}

    def add_validator(self, validator: str, stake: int = 100):
        self.validator_stake[validator] = stake

    def update(self, validator: str, block_hash: str, slot: int) -> bool:
        """Update latest vote for validator (strict LMD)"""
        if validator not in self.validator_stake:
            return False

        current = self.latest_vote.get(validator)

        # LMD rule: only update if slot is newer
        if current is None or slot > current[1]:
            self.latest_vote[validator] = (block_hash, slot)
            return True
        return False

    def get_weights(self) -> Dict[str, int]:
        """
        Calculate block weights from latest votes
        Each vote contributes validator's stake to its block
        """
        if native.native_available() and hasattr(native, "lmd_compute_weights"):
            try:
                votes = {
                    v: [block_hash, int(slot)]
                    for v, (block_hash, slot) in self.latest_vote.items()
                }
                stakes = {v: int(s) for v, s in self.validator_stake.items()}
                raw = native.lmd_compute_weights(
                    json.dumps(votes, separators=(",", ":"), ensure_ascii=False),
                    json.dumps(stakes, separators=(",", ":"), ensure_ascii=False),
                )
                parsed = json.loads(raw)
                return {str(k): int(v) for k, v in parsed.items()}
            except Exception as exc:
                _native_fb("lmd_compute_weights", exc)

        weights = {}
        for validator, (block_hash, _) in self.latest_vote.items():
            stake = self.validator_stake.get(validator, 0)
            weights[block_hash] = weights.get(block_hash, 0) + stake
        return weights

    def get_validator_vote(self, validator: str) -> Optional[Tuple[str, int]]:
        return self.latest_vote.get(validator)

    def get_stats(self) -> dict:
        return {
            "validators": len(self.validator_stake),
            "active_votes": len(self.latest_vote),
            "total_stake": sum(self.validator_stake.values()),
            "blocks_with_votes": len(self.get_weights()),
            "native_weights": bool(
                native.native_available() and hasattr(native, "lmd_compute_weights")
            ),
        }
