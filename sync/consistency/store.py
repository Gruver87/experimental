"""In-memory consistency store (single-writer); optional mirror callback."""

from __future__ import annotations

import threading
from typing import Callable, Optional

from sync.consistency.machine import ConsistencyMachine
from sync.consistency.types import ConsistencySnapshot


class InMemoryConsistencyStore:
    """Thread-safe snapshot store implementing ``SyncConsistencyStorePort``."""

    __slots__ = ("_lock", "_snap", "_on_change")

    def __init__(
        self,
        *,
        initial: Optional[ConsistencySnapshot] = None,
        on_change: Optional[Callable[[ConsistencySnapshot], None]] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._snap = initial if initial is not None else ConsistencyMachine().boot_snapshot()
        self._on_change = on_change

    def get_snapshot(self) -> ConsistencySnapshot:
        with self._lock:
            return self._snap

    def set_snapshot(self, snapshot: ConsistencySnapshot) -> None:
        if not isinstance(snapshot, ConsistencySnapshot):
            raise TypeError("snapshot must be ConsistencySnapshot")
        with self._lock:
            self._snap = snapshot
            cb = self._on_change
        if cb is not None:
            try:
                cb(snapshot)
            except Exception as exc:
                import logging

                logging.getLogger("consistency.store").warning(
                    "consistency on_change callback failed: %s", exc
                )
