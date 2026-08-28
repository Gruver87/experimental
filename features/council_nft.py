#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gruver87 Genesis Council NFT — ADR 0022 Profile C extension.

Loads published manifest, performs one-shot genesis mint (87 cap), enforces
soulbound metadata on transfer, and exposes read-only stats. Not L1 security.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from features.nft import NFTMarketplace, NFTToken

COLLECTION_ID = "gruver87-council-87"
SUPPLY_CAP = 87
DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "genesis"
    / "gruver87-council-manifest.json"
)


class CouncilNftError(Exception):
    """Council mint / governance NFT boundary violation."""


def council_token_id(numeric_id: int) -> str:
    if numeric_id < 1 or numeric_id > SUPPLY_CAP:
        raise CouncilNftError(f"token_id out of range: {numeric_id}")
    return f"{COLLECTION_ID}:{numeric_id:03d}"


def parse_council_numeric_id(token_id: str) -> Optional[int]:
    prefix = f"{COLLECTION_ID}:"
    if not token_id.startswith(prefix):
        return None
    try:
        return int(token_id[len(prefix) :])
    except ValueError:
        return None


def is_council_token(token_id: str) -> bool:
    return parse_council_numeric_id(token_id) is not None


def load_manifest(path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    manifest_path = Path(path) if path is not None else DEFAULT_MANIFEST
    if not manifest_path.is_file():
        raise CouncilNftError(f"manifest missing: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("collection_id") != COLLECTION_ID:
        raise CouncilNftError("manifest collection_id mismatch")
    if data.get("supply_cap") != SUPPLY_CAP:
        raise CouncilNftError("manifest supply_cap mismatch")
    return data


def _soulbound_active(metadata: Dict[str, Any], today: Optional[date] = None) -> bool:
    until = metadata.get("soulbound_until")
    if not until:
        return False
    try:
        end = datetime.strptime(str(until), "%Y-%m-%d").date()
    except ValueError:
        return True
    ref = today or date.today()
    return ref <= end


def council_transfer_refuse(token: NFTToken, today: Optional[date] = None) -> Optional[str]:
    """Return error string if transfer must be refused; None if allowed."""
    meta = token.metadata or {}
    if meta.get("collection_id") != COLLECTION_ID:
        return None
    if _soulbound_active(meta, today=today):
        return "council_soulbound: transfer refused until soulbound_until"
    return None


def list_council_tokens(marketplace: NFTMarketplace) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for tid, tok in marketplace.tokens.items():
        if is_council_token(tid):
            out.append(tok.to_dict())
    out.sort(key=lambda row: parse_council_numeric_id(row["token_id"]) or 0)
    return out


def council_stats(marketplace: Optional[NFTMarketplace]) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "collection_id": COLLECTION_ID,
        "supply_cap": SUPPLY_CAP,
        "enabled": marketplace is not None,
        "tier": "app-profile",
        "adr": "0022",
        "on_chain_standard": False,
        "execution_bound": bool(
            marketplace and marketplace._has_balance_backend()
        ),
        "minted_count": 0,
        "genesis_complete": False,
        "manifest_path": str(DEFAULT_MANIFEST.relative_to(DEFAULT_MANIFEST.parents[2]))
        if DEFAULT_MANIFEST.is_file()
        else None,
    }
    if not marketplace:
        return base
    council = list_council_tokens(marketplace)
    base["minted_count"] = len(council)
    base["genesis_complete"] = len(council) == SUPPLY_CAP
    base["unique_owners"] = len({t["owner"] for t in council})
    return base


def genesis_mint_from_manifest(
    marketplace: NFTMarketplace,
    manifest_path: Optional[Union[str, Path]] = None,
    *,
    clear_non_council: bool = False,
) -> Dict[str, Any]:
    """
    One-shot genesis mint of all 87 council tokens from manifest.

    Refuses if any council token already exists (remint forbidden).
    """
    data = load_manifest(manifest_path)
    tokens = data.get("tokens") or []
    if len(tokens) != SUPPLY_CAP:
        raise CouncilNftError(f"manifest token rows {len(tokens)} != {SUPPLY_CAP}")

    existing = [tid for tid in marketplace.tokens if is_council_token(tid)]
    if existing:
        return {
            "ok": False,
            "error": "council_genesis_already_minted",
            "existing_count": len(existing),
            "adr": "0022",
        }

    if clear_non_council:
        marketplace.tokens = {
            k: v for k, v in marketplace.tokens.items() if is_council_token(k)
        }

    minted: List[str] = []
    ceremony_minter = "0xcouncil_genesis_ceremony000000000001"
    manifest_hash = data.get("manifest_tokens_sha256", "")

    with marketplace.lock:
        for row in sorted(tokens, key=lambda r: int(r["token_id"])):
            numeric = int(row["token_id"])
            tid = council_token_id(numeric)
            owner = row.get("initial_holder") or ceremony_minter
            if owner == "TBD_PRE_MINT":
                owner = ceremony_minter

            metadata = {
                "collection_id": COLLECTION_ID,
                "council_numeric_id": numeric,
                "tier": row.get("tier"),
                "bucket": row.get("bucket"),
                "image_file": row.get("image_file"),
                "image_sha256": row.get("image_sha256"),
                "vote_weight": row.get("vote_weight", 1),
                "soulbound_until": row.get("soulbound_until"),
                "manifest_tokens_sha256": manifest_hash,
                "adr": "0022",
            }
            marketplace._mint_internal(
                tid,
                row.get("name") or f"Steward #{numeric:03d}",
                f"Gruver87 Genesis Council seat #{numeric:03d}",
                row.get("image_file") or "",
                owner,
                price=0.0,
            )
            tok = marketplace.tokens[tid]
            tok.metadata = metadata
            tok.owner = owner
            tok.for_sale = False
            marketplace._persist_token(tid)
            minted.append(tid)

    return {
        "ok": True,
        "minted": len(minted),
        "collection_id": COLLECTION_ID,
        "manifest_tokens_sha256": manifest_hash,
        "ceremony_minter": ceremony_minter,
        "adr": "0022",
    }


def refuse_extra_mint(marketplace: NFTMarketplace, numeric_id: int) -> Optional[str]:
    """Refuse mint beyond cap or duplicate council id."""
    if numeric_id < 1 or numeric_id > SUPPLY_CAP:
        return f"council_cap_exceeded: max {SUPPLY_CAP}"
    tid = council_token_id(numeric_id)
    if tid in marketplace.tokens:
        return "council_token_exists"
    council_count = sum(1 for k in marketplace.tokens if is_council_token(k))
    if council_count >= SUPPLY_CAP:
        return "council_cap_exceeded: genesis complete"
    return None
