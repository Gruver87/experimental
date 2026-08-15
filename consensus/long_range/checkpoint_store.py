"""Bounded store of WS checkpoint certificates (ADR 0017 wave-6/8)."""

from __future__ import annotations

import json
import os
from collections import deque
from pathlib import Path
from typing import Deque, List, Optional, Union

from consensus.long_range.checkpoint import CheckpointCertificate
from consensus.long_range.service import WeakSubjectivityService


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

    def apply_latest(self, svc: WeakSubjectivityService) -> bool:
        """Set ``svc`` anchor from the newest certificate (wave-7)."""
        cert = self.latest()
        if cert is None:
            return False
        svc.set_anchor(cert.anchor)
        return True

    def save(self, path: Union[str, Path]) -> Path:
        """Persist history as JSON (atomic replace)."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "max_history": self._max,
            "items": [dict(c.to_dict()) for c in self._items],
        }
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)
        return p

    @classmethod
    def load(cls, path: Union[str, Path]) -> "CheckpointStore":
        """Load store from JSON; fail-closed on digest mismatch."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        max_h = int(raw.get("max_history") or 8)
        store = cls(max_history=max_h)
        for item in raw.get("items") or []:
            store.push(CheckpointCertificate.from_dict(item))
        return store

    @classmethod
    def load_or_empty(cls, path: Union[str, Path, None]) -> "CheckpointStore":
        """Missing path/file → empty store (caller must fail-closed on no_anchor)."""
        if path is None or not str(path).strip():
            return cls()
        p = Path(path)
        if not p.is_file():
            return cls()
        return cls.load(p)

    def __len__(self) -> int:
        return len(self._items)


def bind_persisted_ws(
    *,
    path: Union[str, Path, None] = None,
    env_height: str = "",
    env_hash: str = "",
) -> WeakSubjectivityService:
    """Load WS anchor from disk; seed from env once and persist for restart.

    Empty store and empty env → service with no anchor (tip-import must refuse).
    """
    svc = WeakSubjectivityService()
    store = CheckpointStore.load_or_empty(path)
    if store.apply_latest(svc):
        return svc
    h_raw = str(env_height or "").strip()
    hash_raw = str(env_hash or "").strip()
    if not h_raw or not hash_raw:
        return svc
    cert = CheckpointCertificate.issue(
        height=int(h_raw), block_hash=hash_raw, issuer="env"
    )
    store.push(cert)
    svc.set_anchor(cert.anchor)
    if path and str(path).strip():
        store.save(path)
    return svc
