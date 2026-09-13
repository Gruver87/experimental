#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CONSENSUS ENGINE - PoS validators and attestations (stake in satoshi)."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from crypto import native
from runtime.amount import to_satoshi

NumberLike = Union[int, float, str]


@dataclass
class Validator:
    address: str
    stake: int  # Wave N: integer satoshi (not float ABS)
    is_active: bool = True
    attestations: int = 0
    blocks_proposed: int = 0


class ConsensusEngine:
    """PoS consensus with validators and attestations."""

    SLOTS_PER_EPOCH = 32
    SECONDS_PER_SLOT = 12

    def __init__(self):
        self.validators: Dict[str, Validator] = {}
        self.current_epoch = 0
        self.current_slot = 0
        self.attestations: Dict[int, List[str]] = defaultdict(list)
        self.finalized_checkpoints: List[int] = []

    def add_validator(self, address: str, stake: NumberLike) -> bool:
        if address in self.validators:
            return False
        try:
            stake_sat = max(0, int(to_satoshi(stake)))
        except (TypeError, ValueError):
            return False
        self.validators[address] = Validator(address, stake_sat)
        return True

    def get_total_stake(self) -> int:
        return sum(int(v.stake) for v in self.validators.values() if v.is_active)

    def select_proposer(self) -> Optional[Validator]:
        """Deterministic stake-weighted proposer for current slot (network-safe)."""
        payload = [
            (val.address, float(val.stake), val.is_active)
            for val in self.validators.values()
        ]
        address = native.consensus_stake_weighted_proposer(
            payload, self.current_epoch, self.current_slot
        )
        if not address:
            return None
        return self.validators.get(address)

    def get_committee(self, slot: int) -> List[Validator]:
        """Deterministic attestation committee for slot."""
        committee_size = max(1, len(self.validators) // 32)
        payload = [
            (val.address, float(val.stake), val.is_active)
            for val in self.validators.values()
        ]
        addresses = native.consensus_fisher_yates_committee(
            payload, slot, committee_size
        )
        return [self.validators[addr] for addr in addresses if addr in self.validators]

    def attest(self, validator_addr: str, slot: int, block_hash: str) -> bool:
        """Attest a block as validator."""
        if validator_addr not in self.validators:
            return False

        validator = self.validators[validator_addr]
        if not validator.is_active:
            return False

        validator.attestations += 1
        self.attestations[slot].append(validator_addr)
        return True

    def advance_slot(self) -> int:
        """Advance to the next slot."""
        self.current_slot += 1
        if self.current_slot % self.SLOTS_PER_EPOCH == 0:
            self.current_epoch += 1
            self._finalize_checkpoint()
        return self.current_slot

    def _finalize_checkpoint(self):
        """Finalize checkpoint (2/3+ attestations); no quorum when empty set."""
        total = len(self.validators)
        if total == 0:
            return

        for slot, attestors in self.attestations.items():
            if len(attestors) * 3 >= total * 2:
                self.finalized_checkpoints.append(slot)
                print(f"   Finalized checkpoint at slot {slot}")

    def get_stats(self) -> Dict[str, Any]:
        return {
            "epoch": self.current_epoch,
            "slot": self.current_slot,
            "validators": len(self.validators),
            "total_stake": self.get_total_stake(),
            "finalized_checkpoints": len(self.finalized_checkpoints),
        }


def test_consensus():
    print("Consensus Engine (PoS)")
    print("=" * 40)

    engine = ConsensusEngine()

    for i in range(10):
        engine.add_validator(f"0xvalidator_{i}", 100.0 + i * 50)

    print(f"   Validators: {len(engine.validators)}")
    print(f"   Total stake (satoshi): {engine.get_total_stake()}")

    for _ in range(5):
        proposer = engine.select_proposer()
        if proposer:
            print(f"   Slot {engine.current_slot}: proposer {proposer.address[:16]}...")
            engine.attest(proposer.address, engine.current_slot, "0xblock")
        engine.advance_slot()

    print(f"   Stats: {engine.get_stats()}")


if __name__ == "__main__":
    test_consensus()
