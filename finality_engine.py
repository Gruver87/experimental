#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FINALITY ENGINE - Casper FFG финализация блоков"""

import json
import logging
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from collections import defaultdict

from crypto import native

logger = logging.getLogger("abs.finality")

@dataclass
class Checkpoint:
    epoch: int
    block_hash: str
    block_number: int
    votes: int = 0
    is_justified: bool = False
    is_finalized: bool = False

class FinalityEngine:
    """Casper FFG - финализация блоков через аттестации"""
    
    EPOCH_LENGTH = 32  # блоков в эпохе
    
    def __init__(self):
        self.checkpoints: Dict[int, Checkpoint] = {}
        self.votes: Dict[int, List[str]] = defaultdict(list)
        self.justified_checkpoints: List[int] = []
        self.finalized_checkpoints: List[int] = []
        self.current_epoch = 0
        self.active_validator_count = 1

    def set_active_validator_count(self, count: int) -> None:
        """Live validator set size for 2/3 quorum (not a hardcoded constant)."""
        self.active_validator_count = max(1, int(count or 1))
    
    def get_epoch(self, block_number: int) -> int:
        """Получение эпохи для блока"""
        if native.native_available() and hasattr(native, "fe_epoch"):
            try:
                return int(native.fe_epoch(int(block_number), int(self.EPOCH_LENGTH)))
            except Exception as exc:
                logger.warning("native fe_epoch failed; Python path: %s", exc)
        return block_number // self.EPOCH_LENGTH
    
    def create_checkpoint(self, block_number: int, block_hash: str) -> Checkpoint:
        """Создание чекпоинта для эпохи"""
        epoch = self.get_epoch(block_number)
        if epoch not in self.checkpoints:
            self.checkpoints[epoch] = Checkpoint(epoch, block_hash, block_number)
        return self.checkpoints[epoch]
    
    def add_attestation(self, validator: str, target_epoch: int, target_hash: str) -> bool:
        """Добавление аттестации от валидатора"""
        if target_epoch not in self.checkpoints:
            return False
        
        checkpoint = self.checkpoints[target_epoch]
        if checkpoint.block_hash != target_hash:
            return False
        
        if validator not in self.votes[target_epoch]:
            self.votes[target_epoch].append(validator)
            checkpoint.votes += 1
        
        # Проверяем justification (2/3 голосов от активного набора валидаторов)
        total_validators = max(1, self.active_validator_count)
        quorum = False
        if native.native_available() and hasattr(native, "fe_quorum_reached"):
            try:
                quorum = bool(
                    native.fe_quorum_reached(int(checkpoint.votes), int(total_validators))
                )
            except Exception as exc:
                logger.warning("native fe_quorum_reached failed; Python path: %s", exc)
                quorum = checkpoint.votes >= total_validators * 2 / 3
        else:
            quorum = checkpoint.votes >= total_validators * 2 / 3
        if quorum:
            if not checkpoint.is_justified:
                checkpoint.is_justified = True
                self.justified_checkpoints.append(target_epoch)
                print(f"   Justified checkpoint: epoch {target_epoch}")
        
        return True
    
    def finalize_checkpoint(self, epoch: int) -> bool:
        """Финализация чекпоинта (требует два последовательных justified)"""
        can = False
        if native.native_available() and hasattr(native, "fe_can_finalize"):
            try:
                can = bool(
                    native.fe_can_finalize(
                        int(epoch),
                        json.dumps(list(self.justified_checkpoints)),
                    )
                )
            except Exception as exc:
                logger.warning("native fe_can_finalize failed; Python path: %s", exc)
                can = (
                    epoch in self.justified_checkpoints
                    and (epoch - 1) in self.justified_checkpoints
                )
        else:
            can = (
                epoch in self.justified_checkpoints
                and (epoch - 1) in self.justified_checkpoints
            )
        if not can:
            return False

        if epoch not in self.checkpoints:
            return False

        checkpoint = self.checkpoints[epoch]
        if not checkpoint.is_finalized:
            checkpoint.is_finalized = True
            self.finalized_checkpoints.append(epoch)
            print(f"   FINALIZED checkpoint: epoch {epoch}, block #{checkpoint.block_number}")
            return True

        return False
    
    def process_block(self, block_number: int, block_hash: str, validator: str) -> Dict:
        """Обработка блока и обновление финализации"""
        epoch = self.get_epoch(block_number)
        self.create_checkpoint(block_number, block_hash)
        
        # Добавляем аттестацию от proposer
        self.add_attestation(validator, epoch, block_hash)
        
        # Пробуем финализировать предыдущие эпохи
        for e in range(self.current_epoch, epoch + 1):
            self.finalize_checkpoint(e)
        
        self.current_epoch = epoch
        
        return {
            "block_number": block_number,
            "epoch": epoch,
            "justified": self.justified_checkpoints.copy(),
            "finalized": self.finalized_checkpoints.copy(),
            "is_finalized": epoch in self.finalized_checkpoints
        }
    
    def get_finality_status(self, block_number: int) -> Dict:
        """Получение статуса финализации блока"""
        epoch = self.get_epoch(block_number)
        
        if epoch in self.finalized_checkpoints:
            return {"status": "finalized", "epoch": epoch, "confirmations": "✅ 2/3+ votes"}
        elif epoch in self.justified_checkpoints:
            return {"status": "justified", "epoch": epoch, "confirmations": "🟡 awaiting next epoch"}
        else:
            return {"status": "pending", "epoch": epoch, "confirmations": "⚪ awaiting attestations"}
    
    def get_stats(self) -> Dict:
        return {
            "current_epoch": self.current_epoch,
            "justified_checkpoints": len(self.justified_checkpoints),
            "finalized_checkpoints": len(self.finalized_checkpoints),
            "total_votes": sum(len(v) for v in self.votes.values())
        }

def test_finality():
    print("🔒 Finality Engine Test")
    print("=" * 40)
    
    engine = FinalityEngine()
    validators = [f"validator_{i}" for i in range(32)]
    
    # Симуляция 100 блоков
    for block in range(1, 101):
        validator = validators[block % len(validators)]
        result = engine.process_block(block, f"hash_{block}", validator)
        
        if block % 32 == 0:
            print(f"   📦 Block #{block}: epoch {result['epoch']}, finalized: {result['is_finalized']}")
    
    stats = engine.get_stats()
    print(f"\n   📊 Stats: {stats['finalized_checkpoints']} epochs finalized")
    
    # Проверка статуса
    status = engine.get_finality_status(95)
    print(f"   🎯 Block 95 status: {status['status']}")
    
    return True

if __name__ == "__main__":
    test_finality()
