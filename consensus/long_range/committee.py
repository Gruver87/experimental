"""Ed25519 committee multi-sig for lab WS certificates (ADR 0017).

Lab-industrial quorum over the digest payload. Not BLS aggregate. Not prod mesh.
Threshold default: ceil(2/3 * n) of configured committee pubkeys.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def _norm_hex(raw: str) -> str:
    return str(raw or "").strip().lower().replace("0x", "")


def threshold_for(n: int, *, numer: int = 2, denom: int = 3) -> int:
    """Minimum signatures required (ceil(numer/denom * n), at least 1 when n>0)."""
    size = int(n)
    if size <= 0:
        return 0
    return max(1, (size * int(numer) + int(denom) - 1) // int(denom))


def cert_signing_message(*, digest: str) -> bytes:
    """Domain-separated message bound to the digest-only certificate checksum."""
    d = _norm_hex(digest)
    if len(d) != 64:
        raise ValueError("digest must be 32-byte hex")
    return b"ABS_WS_CERT_ED25519_V1|" + d.encode("ascii")


def generate_keypair() -> tuple[str, str]:
    """Return (private_hex, public_hex) for lab ceremony only."""
    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key()
    priv = sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()
    pub = pk.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    return priv, pub


def sign_digest(*, private_key_hex: str, digest: str) -> str:
    raw = bytes.fromhex(_norm_hex(private_key_hex))
    if len(raw) != 32:
        raise ValueError("ed25519 private key must be 32 bytes")
    sk = Ed25519PrivateKey.from_private_bytes(raw)
    sig = sk.sign(cert_signing_message(digest=digest))
    return sig.hex()


def verify_signature(*, public_key_hex: str, digest: str, signature_hex: str) -> bool:
    try:
        pk_raw = bytes.fromhex(_norm_hex(public_key_hex))
        sig_raw = bytes.fromhex(_norm_hex(signature_hex))
        if len(pk_raw) != 32 or len(sig_raw) != 64:
            return False
        pk = Ed25519PublicKey.from_public_bytes(pk_raw)
        pk.verify(sig_raw, cert_signing_message(digest=digest))
        return True
    except (ValueError, InvalidSignature, TypeError):
        return False


@dataclass(frozen=True)
class CommitteeConfig:
    """Committee pubkey allow-list + threshold for lab WS certs."""

    pubkeys: tuple[str, ...]
    threshold: int

    @staticmethod
    def from_env() -> Optional["CommitteeConfig"]:
        """Load from ABS_WS_COMMITTEE_PUBKEYS or ABS_WS_COMMITTEE_PUBKEYS_FILE."""
        path = str(os.environ.get("ABS_WS_COMMITTEE_PUBKEYS_FILE", "") or "").strip()
        if path:
            return load_committee_manifest(path)
        raw = str(os.environ.get("ABS_WS_COMMITTEE_PUBKEYS", "") or "").strip()
        if not raw:
            return None
        pubs = tuple(_norm_hex(p) for p in raw.split(",") if _norm_hex(p))
        if not pubs:
            return None
        for p in pubs:
            if len(p) != 64:
                raise ValueError(f"invalid committee pubkey length: {p[:16]}...")
        thr_raw = str(os.environ.get("ABS_WS_COMMITTEE_THRESHOLD", "") or "").strip()
        thr = int(thr_raw) if thr_raw else threshold_for(len(pubs))
        if thr < 1 or thr > len(pubs):
            raise ValueError("ABS_WS_COMMITTEE_THRESHOLD out of range")
        return CommitteeConfig(pubkeys=pubs, threshold=thr)

    @staticmethod
    def from_mapping(data: Mapping[str, Any]) -> "CommitteeConfig":
        pubs = tuple(_norm_hex(str(p)) for p in (data.get("pubkeys") or []))
        if not pubs:
            raise ValueError("committee pubkeys empty")
        thr = int(data.get("threshold") or threshold_for(len(pubs)))
        return CommitteeConfig(pubkeys=pubs, threshold=thr)

    def to_dict(self) -> dict[str, Any]:
        return {"pubkeys": list(self.pubkeys), "threshold": int(self.threshold)}


@dataclass(frozen=True)
class CommitteeSignature:
    public_key: str
    signature: str

    def to_dict(self) -> dict[str, str]:
        return {
            "public_key": _norm_hex(self.public_key),
            "signature": _norm_hex(self.signature),
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "CommitteeSignature":
        return CommitteeSignature(
            public_key=_norm_hex(str(data.get("public_key") or "")),
            signature=_norm_hex(str(data.get("signature") or "")),
        )


def verify_committee_quorum(
    *,
    digest: str,
    signatures: Sequence[CommitteeSignature | Mapping[str, Any]],
    committee: CommitteeConfig,
) -> bool:
    """Fail-closed: distinct committee members, valid Ed25519, count >= threshold."""
    allow = set(committee.pubkeys)
    seen: set[str] = set()
    ok = 0
    for item in signatures:
        sig = (
            item
            if isinstance(item, CommitteeSignature)
            else CommitteeSignature.from_dict(item)
        )
        pk = _norm_hex(sig.public_key)
        if pk not in allow or pk in seen:
            continue
        if not verify_signature(
            public_key_hex=pk, digest=digest, signature_hex=sig.signature
        ):
            continue
        seen.add(pk)
        ok += 1
        if ok >= int(committee.threshold):
            return True
    return False


def sign_with_keys(
    *,
    digest: str,
    private_keys_hex: Iterable[str],
) -> List[CommitteeSignature]:
    """Sign digest with each private key; return committee signature rows."""
    out: List[CommitteeSignature] = []
    for priv in private_keys_hex:
        raw = bytes.fromhex(_norm_hex(priv))
        sk = Ed25519PrivateKey.from_private_bytes(raw)
        pub = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
        out.append(
            CommitteeSignature(
                public_key=pub,
                signature=sign_digest(private_key_hex=priv, digest=digest),
            )
        )
    return out


def committee_required() -> bool:
    """When true, gossip/adopt refuses certs without valid quorum."""
    return str(os.environ.get("ABS_WS_COMMITTEE_REQUIRED", "") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def load_committee_manifest(path: str) -> CommitteeConfig:
    data = json.loads(open(path, encoding="utf-8").read())
    return CommitteeConfig.from_mapping(data)
