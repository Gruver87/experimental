"""Storage domain value types and typed errors (ADR 0006).

No RocksDB / SQLite / keycodec / CF imports. Domain services exchange these
values across ``storage.ports``; byte packing stays inside adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping

__all__ = [
    "StorageError",
    "StorageCorruptionError",
    "StorageFullError",
    "StorageUnavailableError",
    "PersistError",
    "StorageConflictError",
    "BlockRecord",
    "AccountRecord",
    "TipMeta",
    "SATOSHI_PER_COIN",
]

SATOSHI_PER_COIN: int = 100_000_000


# ── Errors ───────────────────────────────────────────────────────────────────


class StorageError(Exception):
    """Base storage boundary error (domain-visible)."""

    def __init__(self, message: str = "", *, reason_code: str = "") -> None:
        self.reason_code = str(reason_code or type(self).__name__)
        super().__init__(str(message or self.reason_code))


class StorageCorruptionError(StorageError):
    """Authoritative payload failed decode / integrity check."""


class StorageFullError(StorageError):
    """Disk / quota exhausted on commit."""


class StorageUnavailableError(StorageError):
    """Engine closed, I/O failure, or temporarily unavailable."""


class PersistError(StorageUnavailableError):
    """Hot-path write failed — fail-closed; never soft ``False`` to callers."""


class StorageConflictError(StorageError):
    """CAS / expected_parent / concurrent tip conflict."""


# ── Records ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BlockRecord:
    """Domain block view — payload is already-validated mapping (no bytes)."""

    height: int
    block_hash: str
    parent_hash: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "height", int(self.height or 0))
        object.__setattr__(self, "block_hash", str(self.block_hash or "").strip())
        object.__setattr__(self, "parent_hash", str(self.parent_hash or "").strip())
        object.__setattr__(self, "payload", dict(self.payload or {}))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "BlockRecord":
        d = dict(data or {})
        try:
            h = int(d.get("height", d.get("number", 0)) or 0)
        except (TypeError, ValueError):
            h = 0
        hh = str(d.get("hash") or d.get("block_hash") or "").strip()
        ph = str(d.get("parent_hash") or d.get("parent") or "").strip()
        return cls(height=h, block_hash=hh, parent_hash=ph, payload=d)

    def to_mapping(self) -> MutableMapping[str, Any]:
        out = dict(self.payload)
        out["height"] = int(self.height)
        out["hash"] = str(self.block_hash or out.get("hash") or "")
        out["block_hash"] = str(out["hash"])
        out["parent_hash"] = str(self.parent_hash or out.get("parent_hash") or "")
        return out


@dataclass(frozen=True)
class AccountRecord:
    """Domain account row — adapter maps satoshi/float dual-write on persist."""

    address: str
    balance_satoshi: int = 0
    nonce: int = 0
    code: str = ""
    storage_json: str = "{}"
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "address", str(self.address or "").strip().lower())
        try:
            sat = int(self.balance_satoshi or 0)
        except (TypeError, ValueError):
            sat = 0
        object.__setattr__(self, "balance_satoshi", max(0, sat))
        try:
            nonce = int(self.nonce or 0)
        except (TypeError, ValueError):
            nonce = 0
        object.__setattr__(self, "nonce", max(0, nonce))
        object.__setattr__(self, "code", str(self.code or ""))
        object.__setattr__(self, "storage_json", str(self.storage_json or "{}"))
        object.__setattr__(self, "extra", dict(self.extra or {}))

    @classmethod
    def from_mapping(cls, address: str, data: Mapping[str, Any]) -> "AccountRecord":
        d = dict(data or {})
        addr = str(address or d.get("address") or "").strip()
        sat = d.get("balance_satoshi")
        if sat is None and d.get("balance") is not None:
            try:
                # Soft float→satoshi for domain port; adapter owns canonical dual-write.
                sat = int(round(float(d.get("balance") or 0) * float(SATOSHI_PER_COIN)))
            except (TypeError, ValueError):
                sat = 0
        try:
            sat_i = int(sat or 0)
        except (TypeError, ValueError):
            sat_i = 0
        try:
            nonce_i = int(d.get("nonce") or 0)
        except (TypeError, ValueError):
            nonce_i = 0
        storage = d.get("storage")
        if isinstance(storage, Mapping):
            import json

            storage_json = json.dumps(
                {str(k): v for k, v in storage.items()}, ensure_ascii=False
            )
        else:
            storage_json = str(storage if storage is not None else "{}")
        skip = {"balance", "balance_satoshi", "nonce", "code", "storage", "address"}
        return cls(
            address=addr,
            balance_satoshi=sat_i,
            nonce=nonce_i,
            code=str(d.get("code") or ""),
            storage_json=storage_json,
            extra={k: v for k, v in d.items() if k not in skip},
        )

    def to_mapping(self) -> MutableMapping[str, Any]:
        """Engine-facing account delta (satoshi authoritative; adapter dual-writes)."""
        out = dict(self.extra)
        out["address"] = str(self.address)
        out["balance_satoshi"] = int(self.balance_satoshi)
        out["nonce"] = int(self.nonce)
        out["code"] = self.code
        out["storage"] = self.storage_json
        return out


@dataclass(frozen=True)
class TipMeta:
    """Canonical tip fence written in the same UoW as the tip block."""

    height: int
    head_hash: str
    state_root: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "height", int(self.height or 0))
        object.__setattr__(self, "head_hash", str(self.head_hash or "").strip())
        object.__setattr__(self, "state_root", str(self.state_root or "").strip())
