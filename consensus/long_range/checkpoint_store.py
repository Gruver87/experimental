"""Bounded store of WS checkpoint certificates (ADR 0017 wave-6)."""

from __future__ import annotations

from collections import deque
from typing import Deque, List, Optional

from consensus.long_range.checkpoint import CheckpointCertificate


class CheckpointStore:
    """Keep the latest certificate plus a short rotation history."""

    def __init__(self, *, max_history: int = 8) -> None:
        if int(max_history) < 1:
            raise ValueError("max_history must be >= 1")
        self._max = int(max_history)
        self._items: Deque[CheckpointCertificate] = deque(maxlen=self._max)

    def push(self, cert: CheckpointCertificate) -> None:
        if not cert.verify_digest():
            raise ValueError("checkpoint digest invalid")
        # Avoid duplicate tip digests
        if self._items and self._items[-1].digest == cert.digest:
            return
        self._items.append(cert)

    def latest(self) -> Optional[CheckpointCertificate]:
        return self._items[-1] if self._items else None

    def history(self) -> List[CheckpointCertificate]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)
