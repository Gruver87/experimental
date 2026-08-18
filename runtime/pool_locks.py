#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Управление блокировками пулов токеномики (ecosystem, treasury, staking).
Реальное enforcement в validate_transaction / _apply_transaction.
"""

from typing import Dict, Tuple, Any, Optional

from runtime.amount import money_abs
from runtime.tokenomics import build_allocations, MAX_SUPPLY_ABS

POOL_META_KEY = "pool_locks_state"
STAKING_RELEASE_EPOCHS = 100   # 100 эпох × 32 блока = полная разблокировка staking
DAO_VOTE_THRESHOLD = 0.51        # 51% валидаторов для unlock ecosystem/treasury


class PoolLockManager:
    """Контроль исходящих транзакций с системных пулов ABS."""

    def __init__(self, db, founder_address: str = "", epoch_size: int = 32):
        self.db = db
        self.founder_address = founder_address
        self.epoch_size = epoch_size
        self._ensure_state()

    def _ensure_state(self) -> None:
        state = self.db.get_meta(POOL_META_KEY)
        if state:
            return
        pools: Dict[str, dict] = {}
        for pool in build_allocations(self.founder_address or None):
            if pool.id not in ("ecosystem", "treasury", "staking"):
                continue
            pools[pool.address_key] = {
                "id": pool.id,
                "name": pool.name,
                "locked": pool.locked,
                "total": float(pool.amount_abs),
                "released": 0.0,
                "spent": 0.0,
                "dao_unlocked": False,
                "dao_votes": {},
            }
        self.db.set_meta(POOL_META_KEY, {
            "pools": pools,
            "staking_epochs_released": 0,
            "last_epoch": -1,
        })

    def _state(self) -> dict:
        return self.db.get_meta(POOL_META_KEY) or {"pools": {}}

    def _save(self, state: dict) -> None:
        self.db.set_meta(POOL_META_KEY, state)

    def get_locked_addresses(self) -> Dict[str, dict]:
        return dict(self._state().get("pools", {}))

    def is_system_pool(self, address: str) -> bool:
        return address in self.get_locked_addresses()

    def spendable_balance(self, address: str, db_balance: float) -> float:
        """Сколько ABS можно потратить с системного пула."""
        pools = self.get_locked_addresses()
        if address not in pools:
            return db_balance
        info = pools[address]
        if info["id"] == "staking":
            return max(0.0, info.get("released", 0.0) - info.get("spent", 0.0))
        if info["id"] in ("ecosystem", "treasury"):
            if not info.get("dao_unlocked"):
                return 0.0
            return max(0.0, info["total"] - info.get("spent", 0.0))
        return db_balance

    def is_outgoing_allowed(self, from_addr: str, amount: float, db_balance: float) -> Tuple[bool, str]:
        """Проверка перед включением транзакции в блок / мемпул."""
        pools = self.get_locked_addresses()
        if from_addr not in pools:
            return True, "ok"
        spendable = self.spendable_balance(from_addr, db_balance)
        if amount > spendable + 1e-9:
            info = pools[from_addr]
            if info["id"] in ("ecosystem", "treasury") and not info.get("dao_unlocked"):
                return False, f"{info['id']}_dao_locked: требуется голосование DAO"
            if info["id"] == "staking":
                return False, (
                    f"staking_locked: доступно {spendable:,.2f} ABS "
                    f"(released {info.get('released', 0):,.2f}, spent {info.get('spent', 0):,.2f})"
                )
            return False, f"pool_locked: spendable={spendable:,.2f}"
        return True, "ok"

    def record_outgoing(self, from_addr: str, amount: float) -> None:
        state = self._state()
        pools = state.get("pools", {})
        if from_addr not in pools:
            return
        pools[from_addr]["spent"] = pools[from_addr].get("spent", 0.0) + money_abs(
            amount, field="amount"
        )
        self._save(state)

    def catch_up_epochs(self, current_epoch: int) -> Dict[str, Any]:
        """Догоняет пропущенные эпохи при старте узла (миграция / рестарт)."""
        total_delta = 0.0
        for ep in range(max(0, current_epoch) + 1):
            r = self.on_epoch_boundary(ep)
            total_delta += r.get("staking_released_delta", 0.0)
        return {"epochs_caught_up": current_epoch + 1, "staking_released_total": total_delta}

    def on_epoch_boundary(self, epoch: int) -> Dict[str, Any]:
        """
        На границе эпохи разблокирует 1/STAKING_RELEASE_EPOCHS staking-пула.
        12.6% ABS → 100 эпох = ~278,460 ABS за эпоху.
        """
        state = self._state()
        if epoch <= state.get("last_epoch", -1):
            return {"epoch": epoch, "skipped": True}

        pools = state.get("pools", {})
        staking_addr = "0xstaking0000000000000000000000000000001"
        released_now = 0.0

        if staking_addr in pools:
            info = pools[staking_addr]
            total = info["total"]
            per_epoch = total / STAKING_RELEASE_EPOCHS
            epochs_done = state.get("staking_epochs_released", 0)
            if epochs_done < STAKING_RELEASE_EPOCHS:
                new_released = min(total, info.get("released", 0.0) + per_epoch)
                released_now = new_released - info.get("released", 0.0)
                info["released"] = new_released
                state["staking_epochs_released"] = epochs_done + 1

        state["last_epoch"] = epoch
        self._save(state)
        return {
            "epoch": epoch,
            "staking_released_delta": released_now,
            "staking_total_released": pools.get(staking_addr, {}).get("released", 0.0),
            "staking_epochs_done": state.get("staking_epochs_released", 0),
            "staking_epochs_total": STAKING_RELEASE_EPOCHS,
        }

    def dao_vote(self, pool_id: str, voter: str, validator_registry=None) -> Dict[str, Any]:
        """Голос валидатора за разблокировку ecosystem/treasury."""
        if pool_id not in ("ecosystem", "treasury"):
            return {"success": False, "error": "invalid_pool"}

        if validator_registry:
            if hasattr(validator_registry, "get_validator"):
                v = validator_registry.get_validator(voter)
                if not v:
                    for addr in getattr(validator_registry, "validators", {}):
                        if str(addr).lower() == voter.lower():
                            v = validator_registry.get_validator(addr)
                            voter = addr
                            break
                if not v:
                    return {"success": False, "error": "not_a_validator"}
            elif hasattr(validator_registry, "validators"):
                if voter not in validator_registry.validators:
                    return {"success": False, "error": "not_a_validator"}

        state = self._state()
        pools = state.get("pools", {})
        target_addr = None
        for addr, info in pools.items():
            if info.get("id") == pool_id:
                target_addr = addr
                break
        if not target_addr:
            return {"success": False, "error": "pool_not_found"}

        votes = pools[target_addr].setdefault("dao_votes", {})
        votes[voter] = True

        total_validators = 1
        if validator_registry:
            if hasattr(validator_registry, "validators"):
                total_validators = max(1, len(validator_registry.validators))
            elif hasattr(validator_registry, "get_all"):
                total_validators = max(1, len(validator_registry.get_all()))

        vote_count = len(votes)
        quorum = vote_count / total_validators >= DAO_VOTE_THRESHOLD
        if quorum:
            pools[target_addr]["dao_unlocked"] = True
            pools[target_addr]["locked"] = False

        self._save(state)
        return {
            "success": True,
            "pool": pool_id,
            "votes": vote_count,
            "validators": total_validators,
            "quorum_reached": quorum,
            "unlocked": pools[target_addr].get("dao_unlocked", False),
        }

    def get_status(self) -> Dict[str, Any]:
        state = self._state()
        pools = state.get("pools", {})
        result = []
        for addr, info in pools.items():
            spendable = self.spendable_balance(addr, info["total"])
            result.append({
                "address": addr,
                "id": info["id"],
                "name": info["name"],
                "total": info["total"],
                "released": info.get("released", 0.0),
                "spent": info.get("spent", 0.0),
                "spendable": spendable,
                "locked": info.get("locked", True) and spendable <= 0,
                "dao_unlocked": info.get("dao_unlocked", False),
                "dao_votes": len(info.get("dao_votes", {})),
            })
        return {
            "max_supply": MAX_SUPPLY_ABS,
            "staking_epochs_done": state.get("staking_epochs_released", 0),
            "staking_epochs_total": STAKING_RELEASE_EPOCHS,
            "epoch_size_blocks": self.epoch_size,
            "dao_threshold": DAO_VOTE_THRESHOLD,
            "pools": result,
        }
