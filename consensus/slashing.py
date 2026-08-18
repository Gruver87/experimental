# consensus/slashing.py - Complete slashing engine
from typing import Dict, Set, Optional, List
from dataclasses import dataclass
from datetime import datetime
from collections import defaultdict
import json
import logging

from crypto import native

logger = logging.getLogger("abs.slashing")

@dataclass
class SlashEvent:
    validator: str
    reason: str
    epoch: int
    timestamp: datetime
    penalty: int

class SlashingEngine:
    """Validator slashing mechanism"""
    
    PENALTIES = {
        "double_vote": 100,
        "double_proposal": 200,
        "offline": 10,
        "invalid_proposal": 50,
        "surround_vote": 75
    }
    
    def __init__(self):
        self.votes: Dict[str, Dict[int, str]] = {}
        # height → validator → block_hash (hash-idempotent; conflict slashes)
        self.proposals: Dict[int, Dict[str, str]] = defaultdict(dict)
        self.slashed: Set[str] = set()
        self.events: List[SlashEvent] = []
        self.missed_attestations: Dict[str, int] = defaultdict(int)
        # Stake tracking (used by engine_slashing.py)
        self._stakes: Dict[str, int] = {}
        self._on_slash_callback = None

    # --- Methods required by engine_slashing.py ---

    def register_validator(self, validator_id: str, stake: int = 100):
        """Register a validator with stake."""
        self._stakes[validator_id] = stake

    def add_vote(self, validator_id: str, slot: int, block_hash: str) -> bool:
        """
        Register attestation vote for a slot.
        Double-vote = two different block hashes in the same slot (not same epoch).
        Returns True if vote accepted, False if validator is slashed.
        """
        if validator_id in self.slashed:
            return False
        return self.record_vote(validator_id, slot, block_hash)

    def get_stake(self, validator_id: str) -> int:
        """Get validator stake (0 if slashed)."""
        if validator_id in self.slashed:
            return 0
        return self._stakes.get(validator_id, 0)

    def get_total_active_stake(self) -> int:
        """Total stake of non-slashed validators."""
        return sum(
            stake for vid, stake in self._stakes.items()
            if vid not in self.slashed
        )
        
    def record_vote(self, validator: str, slot: int, block_hash: str) -> bool:
        """Record validator attestation; slash only on conflicting votes in one slot."""
        if validator in self.slashed:
            return False

        if validator not in self.votes:
            self.votes[validator] = {}

        prior = self.votes[validator].get(slot)
        if native.native_available() and hasattr(native, "slash_check_double_vote"):
            try:
                raw = native.slash_check_double_vote(
                    str(block_hash),
                    None if prior is None else str(prior),
                )
                result = json.loads(raw)
                if not result.get("accept", False):
                    self._slash(validator, str(result.get("slash") or "double_vote"), slot)
                    return False
                if prior is None:
                    self.votes[validator][slot] = block_hash
                return True
            except (json.JSONDecodeError, TypeError, ValueError, OSError, RuntimeError) as exc:
                logger.warning("native slash_check_double_vote failed; Python path: %s", exc)

        if slot in self.votes[validator]:
            if self.votes[validator][slot] != block_hash:
                self._slash(validator, "double_vote", slot)
                return False
            return True

        self.votes[validator][slot] = block_hash
        return True
    
    def record_proposal(self, validator: str, height: int, block_hash: str) -> bool:
        """Record a proposal. Same hash at the same height is not double-proposal.

        Catch-up retries and concurrent PathA of the canonical block must not
        slash the only miner. Conflicting hashes at one height still slash.
        An already-slashed validator may still land canonical catch-up blocks
        (slash is a penalty, not an import firewall).
        """
        digest = str(block_hash or "")
        slot = self.proposals[height]
        prior = slot.get(validator)

        # Same-hash proposal retry is not double_proposal.
        if prior is not None and prior == digest:
            return True

        if prior is not None and prior != digest:
            if validator not in self.slashed:
                if native.native_available() and hasattr(
                    native, "slash_check_double_proposal"
                ):
                    try:
                        raw = native.slash_check_double_proposal(True)
                        result = json.loads(raw)
                        if not result.get("accept", False):
                            self._slash(
                                validator,
                                str(result.get("slash") or "double_proposal"),
                                height // 32,
                            )
                            return False
                    except (json.JSONDecodeError, TypeError, ValueError, OSError, RuntimeError) as exc:
                        logger.warning(
                            "native slash_check_double_proposal failed; Python path: %s",
                            exc,
                        )
                self._slash(validator, "double_proposal", height // 32)
            return False

        if native.native_available() and hasattr(native, "slash_check_double_proposal"):
            try:
                raw = native.slash_check_double_proposal(False)
                result = json.loads(raw)
                if not result.get("accept", False):
                    self._slash(
                        validator,
                        str(result.get("slash") or "double_proposal"),
                        height // 32,
                    )
                    return False
            except (json.JSONDecodeError, TypeError, ValueError, OSError, RuntimeError) as exc:
                logger.warning(
                    "native slash_check_double_proposal failed; Python path: %s",
                    exc,
                )
        slot[validator] = digest
        return True
    
    def record_missed_attestation(self, validator: str):
        """Record missed attestation"""
        if validator not in self.slashed:
            self.missed_attestations[validator] += 1
            
            if self.missed_attestations[validator] > 50:
                self._slash(validator, "offline", 0)
    
    def add_proposal(self, validator: str, height: int, block_hash: str) -> bool:
        return self.record_proposal(validator, height, block_hash)

    def report_invalid_proposal(self, validator: str, height: int, detail: str = ""):
        self._slash(validator, "invalid_proposal", height // 32)

    def get_summary(self) -> dict:
        return {"total_slashed": len(self.slashed), **self.get_stats()}
    
    def _slash(self, validator: str, reason: str, epoch: int):
        """Slash validator"""
        if validator in self.slashed:
            return
        
        penalty = self.PENALTIES.get(reason, 50)
        self.slashed.add(validator)
        
        event = SlashEvent(
            validator=validator,
            reason=reason,
            epoch=epoch,
            timestamp=datetime.now(),
            penalty=penalty
        )
        self.events.append(event)
        
        print(f"   ⚡ SLASH: {validator[:16]}... | {reason} | penalty={penalty}")
        if self._on_slash_callback:
            try:
                self._on_slash_callback(validator, reason, epoch, penalty)
            except Exception as e:
                print(f"   FAIL: slash callback for {validator[:16]}...: {e}")
                raise
    
    def register_slash_callback(self, callback) -> None:
        self._on_slash_callback = callback
    
    def is_slashed(self, validator: str) -> bool:
        return validator in self.slashed
    
    def get_slashed_count(self) -> int:
        return len(self.slashed)
    
    def get_events(self) -> List[SlashEvent]:
        return self.events.copy()
    
    def clear_epoch(self, epoch: int):
        """Clear old epoch data"""
        for validator in list(self.votes.keys()):
            if epoch in self.votes[validator]:
                del self.votes[validator][epoch]
    
    def get_stats(self) -> dict:
        slashed_stake = sum(self._stakes.get(v, 0) for v in self.slashed)
        active_stake = self.get_total_active_stake()
        return {
            "slashed_count": len(self.slashed),
            "slashed_validators": len(self.slashed),
            "slashed_stake": slashed_stake,
            "active_stake": active_stake,
            "total_validators": len(self._stakes),
            "total_events": len(self.events),
            "by_reason": {reason: len([e for e in self.events if e.reason == reason])
                         for reason in self.PENALTIES}
        }
