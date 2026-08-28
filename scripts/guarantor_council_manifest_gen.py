#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate full Gruver87 Genesis Council manifest (87 tokens) — ADR 0022.

Selects unique SVG assets from nft_images/ (root only, skips nested duplicate
folder), computes SHA-256 per image, assigns tiers/buckets/holders, writes JSON.

Usage:
  python scripts/guarantor_council_manifest_gen.py
  python scripts/guarantor_council_manifest_gen.py --check
  python scripts/guarantor_council_manifest_gen.py -o docs/genesis/custom.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NFT_ROOT = ROOT / "nft_images"
DEFAULT_OUT = ROOT / "docs" / "genesis" / "gruver87-council-manifest.json"
TEMPLATE = ROOT / "docs" / "genesis" / "gruver87-council-manifest.template.json"

SUPPLY_CAP = 87
FOUNDER_TOKEN_ID = 87
FOUNDER_IMAGE = "personage_001_Absolute_Crown_.svg"
FOUNDER_Soulbound_UNTIL = "2029-07-14"

BUCKETS: dict[str, int] = {
    "founder": 1,
    "core_reserve_multisig": 3,
    "early_supporters": 20,
    "community": 40,
    "grant_seats": 15,
    "buffer_timelock": 8,
}

CORE_RESERVE_ADDRS = (
    "0x0000000000000000000000000000000000000001",
    "0x0000000000000000000000000000000000000002",
    "0x0000000000000000000000000000000000000003",
)
BUFFER_ADDR = "0xtimelock_buffer000000000000000000000001"
GRANT_POOL_ADDR = "0xgrant_pool000000000000000000000000001"
TBD = "TBD_PRE_MINT"


def _import_founder_address() -> str:
    sys.path.insert(0, str(ROOT))
    from runtime.tokenomics import DEFAULT_FOUNDER_ADDRESS

    return DEFAULT_FOUNDER_ADDRESS


def _tier_for_id(token_id: int) -> str:
    if token_id == FOUNDER_TOKEN_ID:
        return "founder"
    if token_id <= 29:
        return "genesis"
    if token_id <= 58:
        return "council"
    return "steward"


def _bucket_for_id(token_id: int) -> str:
    if token_id == FOUNDER_TOKEN_ID:
        return "founder"
    if token_id <= 20:
        return "early_supporters"
    if token_id <= 60:
        return "community"
    if token_id <= 75:
        return "grant_seats"
    if token_id <= 83:
        return "buffer_timelock"
    return "core_reserve_multisig"


def _holder_for_id(token_id: int, founder: str) -> str:
    bucket = _bucket_for_id(token_id)
    if bucket == "founder":
        return founder
    if bucket == "core_reserve_multisig":
        idx = token_id - 84
        return CORE_RESERVE_ADDRS[idx]
    if bucket == "buffer_timelock":
        return BUFFER_ADDR
    if bucket == "grant_seats":
        return GRANT_POOL_ADDR
    return TBD


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _sort_key(path: Path) -> tuple:
    name = path.name
    m = re.match(r"nft_(\d{3})_", name)
    if m:
        return (0, int(m.group(1)), name)
    m = re.match(r"3d_nft_(\d+)", name)
    if m:
        return (1, int(m.group(1)), name)
    m = re.match(r"nft_3d_(\d+)", name)
    if m:
        return (2, int(m.group(1)), name)
    m = re.match(r"nft_(\d+)\.svg$", name)
    if m:
        return (3, int(m.group(1)), name)
    return (9, 0, name)


def _display_name(path: Path, token_id: int) -> str:
    stem = path.stem
    if stem == Path(FOUNDER_IMAGE).stem:
        return "Gruver87 Founder Seat"
    m = re.match(r"nft_(\d{3})_(.+)", stem)
    if m:
        label = m.group(2).replace("___", " — ").replace("_", " ").strip()
        return f"{label} — #{token_id:03d}"
    m = re.match(r"3d_nft_(\d+)_(.+)", stem)
    if m:
        return f"3D {m.group(2).replace('_', ' ').title()} — #{token_id:03d}"
    m = re.match(r"nft_3d_(\d+)", stem)
    if m:
        return f"Steward 3D #{m.group(1)} — #{token_id:03d}"
    m = re.match(r"nft_(\d+)", stem)
    if m:
        return f"Genesis Steward #{token_id:03d}"
    return f"Genesis Steward #{token_id:03d}"


def collect_image_pool() -> list[Path]:
    """Root-level SVG only; exclude nested nft_images/ duplicate tree."""
    pool: list[Path] = []
    seen: set[str] = set()
    for path in sorted(NFT_ROOT.iterdir(), key=_sort_key):
        if not path.is_file() or path.suffix.lower() != ".svg":
            continue
        if path.name == FOUNDER_IMAGE:
            continue
        if path.name in seen:
            continue
        seen.add(path.name)
        pool.append(path)
    return pool


def build_tokens(founder: str) -> list[dict[str, Any]]:
    pool = collect_image_pool()
    need = SUPPLY_CAP - 1
    if len(pool) < need:
        raise RuntimeError(
            f"need {need} unique SVG assets in {NFT_ROOT}, found {len(pool)}"
        )

    founder_path = NFT_ROOT / FOUNDER_IMAGE
    if not founder_path.is_file():
        raise RuntimeError(f"founder image missing: {founder_path}")

    tokens: list[dict[str, Any]] = []
    for token_id in range(1, SUPPLY_CAP + 1):
        if token_id == FOUNDER_TOKEN_ID:
            img = founder_path
            soulbound = FOUNDER_Soulbound_UNTIL
            note = "Founder abstains on self-grant votes per charter §10"
        else:
            img = pool[token_id - 1]
            soulbound = None
            note = None

        rel = img.relative_to(ROOT).as_posix()
        row: dict[str, Any] = {
            "token_id": token_id,
            "tier": _tier_for_id(token_id),
            "bucket": _bucket_for_id(token_id),
            "name": _display_name(img, token_id),
            "image_file": rel,
            "image_sha256": _sha256_file(img),
            "initial_holder": _holder_for_id(token_id, founder),
            "soulbound_until": soulbound,
            "vote_weight": 1,
        }
        if note:
            row["note"] = note
        tokens.append(row)
    return tokens


def manifest_body(founder: str) -> dict[str, Any]:
    tokens = build_tokens(founder)
    tokens_canonical = json.dumps(tokens, ensure_ascii=False, separators=(",", ":"))
    manifest_hash = hashlib.sha256(tokens_canonical.encode("utf-8")).hexdigest()

    base: dict[str, Any] = {
        "$schema": "absolute/genesis-council-manifest/v1",
        "collection_id": "gruver87-council-87",
        "collection_name": "Gruver87 Genesis Council '87",
        "supply_cap": SUPPLY_CAP,
        "chain_id_staging": 778889,
        "rationale": "Birth year 1987 and public identity Gruver87; fixed steward council",
        "adr": "0022",
        "charter_version": "1.0",
        "generated_at": date.today().isoformat(),
        "manifest_tokens_sha256": manifest_hash,
        "mint_policy": {
            "genesis_mint_only": True,
            "remint_forbidden": True,
            "vote_weight_rule": "1_nft_1_vote",
            "founder_seat_token_id": FOUNDER_TOKEN_ID,
            "founder_soulbound_months": 36,
        },
        "allocation_buckets": dict(BUCKETS),
        "governance": {
            "quorum_standard": 30,
            "quorum_treasury": 45,
            "supermajority_charter": 58,
            "timelock_hours_standard": 72,
            "timelock_days_treasury_policy": 7,
        },
        "multisig": {
            "core_reserve": {
                "threshold": "2-of-3",
                "addresses": list(CORE_RESERVE_ADDRS),
                "note": "Replace with real addresses before mint; never commit private keys",
            }
        },
        "tokens": tokens,
    }
    return base


def validate_manifest(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("supply_cap") != SUPPLY_CAP:
        errors.append("supply_cap != 87")
    tokens = data.get("tokens", [])
    if len(tokens) != SUPPLY_CAP:
        errors.append(f"token count {len(tokens)} != 87")
    ids = [t.get("token_id") for t in tokens]
    if sorted(ids) != list(range(1, SUPPLY_CAP + 1)):
        errors.append("token_id sequence not 1..87")
    hashes = [t.get("image_sha256") for t in tokens]
    if len(set(hashes)) != len(hashes):
        errors.append("duplicate image_sha256 in manifest")
    bucket_counts: dict[str, int] = {}
    for t in tokens:
        b = t.get("bucket", "")
        bucket_counts[b] = bucket_counts.get(b, 0) + 1
    for name, expected in BUCKETS.items():
        if bucket_counts.get(name, 0) != expected:
            errors.append(f"bucket {name}: got {bucket_counts.get(name, 0)}, want {expected}")
    founder = [t for t in tokens if t.get("token_id") == FOUNDER_TOKEN_ID]
    if len(founder) != 1 or founder[0].get("vote_weight") != 1:
        errors.append("founder seat #87 invalid")
    for t in tokens:
        if t.get("vote_weight") != 1:
            errors.append(f"token {t.get('token_id')}: vote_weight != 1")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Gruver87 council manifest")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output JSON (default: {DEFAULT_OUT.relative_to(ROOT)})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate existing output only (no write)",
    )
    args = parser.parse_args()

    if args.check:
        if not args.output.is_file():
            print(f"FAIL: missing {args.output}")
            return 1
        data = json.loads(args.output.read_text(encoding="utf-8"))
        errors = validate_manifest(data)
        if errors:
            for e in errors:
                print(f"FAIL: {e}")
            return 1
        print(f"OK: {args.output} valid ({SUPPLY_CAP} tokens)")
        return 0

    founder = _import_founder_address()
    body = manifest_body(founder)
    errors = validate_manifest(body)
    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(body, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(text, encoding="utf-8")
    print(f"Wrote {args.output.relative_to(ROOT)} ({SUPPLY_CAP} tokens)")
    print(f"manifest_tokens_sha256={body['manifest_tokens_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
