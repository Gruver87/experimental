# blockchain/immutable_state.py
# Управление состоянием - ТОЛЬКО INT, DERIVED FROM CHAIN

import threading
from typing import Dict, Optional, List
from dataclasses import dataclass, field

from runtime.amount import SATOSHI_MULTIPLIER, to_satoshi, from_satoshi_float

@dataclass
class AccountState:
    """Состояние аккаунта - только int для балансов"""
    address: str
    balance_satoshi: int = 0
    nonce: int = 0
    last_block_height: int = 0
    is_validator: bool = False
    validator_stake_satoshi: int = 0
    
    @property
    def balance(self) -> float:
        """Только для отображения"""
        return from_satoshi_float(self.balance_satoshi)
    
    def to_dict(self) -> dict:
        return {
            'address': self.address,
            'balance_satoshi': self.balance_satoshi,
            'balance_abs': self.balance,
            'nonce': self.nonce,
            'is_validator': self.is_validator
        }

class ImmutableStateManager:
    """
    Управление состоянием - реконструируется из цепочки блоков
    Не может быть изменён напрямую, только через replay
    """
    
    def __init__(self):
        self._state: Dict[str, AccountState] = {}
        self._lock = threading.RLock()
        self._last_applied_height = -1
    
    def get_account(self, address: str, create: bool = True) -> Optional[AccountState]:
        """Получить аккаунт"""
        with self._lock:
            if address in self._state:
                return self._state[address]
            if create:
                self._state[address] = AccountState(address=address)
                return self._state[address]
            return None
    
    def get_balance_satoshi(self, address: str) -> int:
        """Получить баланс в сатоши"""
        acc = self.get_account(address, create=True)
        return acc.balance_satoshi if acc else 0
    
    def get_balance_abs(self, address: str) -> float:
        """Получить баланс в ABS (только для отображения)"""
        return self.get_balance_satoshi(address) / SATOSHI_MULTIPLIER

    def credit(self, address: str, amount_abs: float) -> None:
        """Начислить баланс (genesis / миграция)."""
        with self._lock:
            acc = self.get_account(address, create=True)
            acc.balance_satoshi += self.to_satoshi(amount_abs)

    def seed_from_balances(self, balances: dict) -> int:
        """Загрузить начальные балансы {address: amount_abs}. Возвращает число аккаунтов."""
        with self._lock:
            for addr, amount in balances.items():
                acc = self.get_account(addr, create=True)
                acc.balance_satoshi = self.to_satoshi(amount)
            return len(balances)

    def reconcile_from_store(self, store, addresses=None, *, fail_loud: bool = False) -> int:
        """Mirror canonical DB/Rocks satoshi into IMS shadow (post-block honesty)."""
        from runtime.state_truth import canonical_balance_satoshi

        with self._lock:
            if addresses is None:
                if hasattr(store, "get_all_accounts"):
                    addresses = [a.get("address", "") for a in store.get_all_accounts()]
                else:
                    addresses = list(self._state.keys())
            n = 0
            for addr in addresses:
                if not addr:
                    continue
                acc = self.get_account(addr, create=True)
                acc.balance_satoshi = canonical_balance_satoshi(store, addr)
                if hasattr(store, "get_nonce"):
                    try:
                        acc.nonce = int(store.get_nonce(addr))
                    except Exception as exc:
                        print(f"[ImmutableState] get_nonce failed for {addr}: {exc}")
                        if fail_loud:
                            raise
                n += 1
            return n

    def apply_transaction(self, tx: dict) -> bool:
        """
        Применить транзакцию к состоянию
        Детерминированно - одинаковый результат на всех нодах
        """
        with self._lock:
            from_addr = tx.get('from', tx.get('from_addr', ''))
            to_addr = tx.get('to', tx.get('to_addr', ''))
            amount_satoshi = tx.get(
                "amount_satoshi",
                to_satoshi(tx.get("amount", 0)),
            )
            fee_satoshi = tx.get(
                "fee_satoshi",
                to_satoshi(tx.get("fee", 0)),
            )
            
            from_acc = self.get_account(from_addr, create=True)
            to_acc = self.get_account(to_addr, create=True)
            
            # Проверка баланса
            total_cost = amount_satoshi + fee_satoshi
            if from_acc.balance_satoshi < total_cost:
                return False
            
            # Применяем
            from_acc.balance_satoshi -= total_cost
            to_acc.balance_satoshi += amount_satoshi
            
            # Комиссия сжигается (дефляция)
            # Без изменений - просто уходит из системы
            
            return True
    
    def get_total_supply_satoshi(self) -> int:
        """Общая эмиссия в сатоши"""
        with self._lock:
            return sum(acc.balance_satoshi for acc in self._state.values())
    
    def get_total_supply_abs(self) -> float:
        return self.get_total_supply_satoshi() / SATOSHI_MULTIPLIER
    
    def get_stats(self) -> dict:
        with self._lock:
            return {
                'total_accounts': len(self._state),
                'total_supply_satoshi': self.get_total_supply_satoshi(),
                'total_supply_abs': self.get_total_supply_abs(),
                'validators': len([a for a in self._state.values() if a.is_validator])
            }
    
    def to_dict(self) -> dict:
        """Экспорт состояния (для отладки)"""
        with self._lock:
            return {addr: acc.to_dict() for addr, acc in self._state.items()}
    
    @staticmethod
    def to_satoshi(abs_amount: float) -> int:
        return to_satoshi(abs_amount)

    @staticmethod
    def to_abs(satoshi: int) -> float:
        return from_satoshi_float(satoshi)


# Глобальный экземпляр
immutable_state = ImmutableStateManager()
