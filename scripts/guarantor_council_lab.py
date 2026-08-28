#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gruver87 Genesis Council lab — ADR 0022 design gates.

Validates manifest (full generated JSON preferred), allocation math,
refuse-list invariants, and honesty flags. Does NOT require live staging mesh.

Usage:
  python scripts/guarantor_council_lab.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_FULL = ROOT / "docs" / "genesis" / "gruver87-council-manifest.json"
MANIFEST_TEMPLATE = ROOT / "docs" / "genesis" / "gruver87-council-manifest.template.json"
ADR = ROOT / "docs" / "adr" / "0022-gruver87-genesis-council-governance.md"
CHARTER = ROOT / "docs" / "GRUVER87_COUNCIL_CHARTER.md"
TOKENOMICS = ROOT / "runtime" / "tokenomics.py"
GEN_SCRIPT = ROOT / "scripts" / "guarantor_council_manifest_gen.py"

SUPPLY_CAP = 87
FOUNDER_PERCENT = 17.4

REFUSE_TOPICS = (
    "validator set",
    "consensus",
    "feature_*",
    "778888",
    "tip-safety",
    "bridge ON",
    "founder pool",
    "remint",
)

BUCKETS = {
    "founder": 1,
    "core_reserve_multisig": 3,
    "early_supporters": 20,
    "community": 40,
    "grant_seats": 15,
    "buffer_timelock": 8,
}


def _ok(msg: str) -> None:
    print(f"  OK: {msg}")


def _validate_full_manifest(data: dict, errors: list[str]) -> None:
    tokens = data.get("tokens", [])
    if len(tokens) != SUPPLY_CAP:
        errors.append(f"expected {SUPPLY_CAP} tokens, got {len(tokens)}")
        return
    ids = sorted(t.get("token_id") for t in tokens)
    if ids != list(range(1, SUPPLY_CAP + 1)):
        errors.append("token_ids must be exactly 1..87")
    hashes = [t.get("image_sha256") for t in tokens]
    if any(h in ("", "TBD_AT_MINT", None) for h in hashes):
        errors.append("all tokens must have computed image_sha256")
    if len(set(hashes)) != len(hashes):
        errors.append("duplicate image_sha256")
    bucket_counts: dict[str, int] = {}
    for t in tokens:
        bucket_counts[t.get("bucket", "")] = bucket_counts.get(t.get("bucket", ""), 0) + 1
    for name, expected in BUCKETS.items():
        if bucket_counts.get(name, 0) != expected:
            errors.append(f"bucket {name}: {bucket_counts.get(name, 0)} != {expected}")
    if not data.get("manifest_tokens_sha256"):
        errors.append("manifest_tokens_sha256 missing (run manifest gen)")


def main() -> None:
    print("=== guarantor_council_lab (ADR 0022) ===")
    errors: list[str] = []

    for path in (ADR, CHARTER, TOKENOMICS, GEN_SCRIPT):
        if not path.is_file():
            errors.append(f"missing {path.relative_to(ROOT)}")

    if sum(BUCKETS.values()) != SUPPLY_CAP:
        errors.append(f"bucket sum {sum(BUCKETS.values())} != {SUPPLY_CAP}")

    manifest_path = MANIFEST_FULL if MANIFEST_FULL.is_file() else MANIFEST_TEMPLATE
    if not manifest_path.is_file():
        errors.append("no manifest (template or generated)")
    else:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if data.get("supply_cap") != SUPPLY_CAP:
            errors.append(f"manifest supply_cap != {SUPPLY_CAP}")
        if data.get("chain_id_staging") == 778888:
            errors.append("council must not use prod chain_id 778888")

        mint = data.get("mint_policy", {})
        if mint.get("remint_forbidden") is not True:
            errors.append("remint_forbidden must be true")
        if mint.get("founder_seat_token_id") != 87:
            errors.append("founder seat must be token_id 87")

        gov = data.get("governance", {})
        if gov.get("quorum_standard", 0) > SUPPLY_CAP:
            errors.append("quorum_standard exceeds supply")
        if gov.get("quorum_treasury", 0) > SUPPLY_CAP:
            errors.append("quorum_treasury exceeds supply")

        tokens = data.get("tokens", [])
        founder_rows = [t for t in tokens if t.get("token_id") == 87]
        if len(founder_rows) != 1:
            errors.append("manifest must include exactly one token_id 87 row")
        elif founder_rows[0].get("vote_weight") != 1:
            errors.append("founder vote_weight must be 1")

        if manifest_path == MANIFEST_FULL:
            _validate_full_manifest(data, errors)
            _ok(f"full manifest {MANIFEST_FULL.name} ({len(tokens)} tokens)")
        else:
            errors.append(
                "run: python scripts/guarantor_council_manifest_gen.py "
                "(template-only is not sufficient for lab PASS)"
            )

    adr_text = ADR.read_text(encoding="utf-8").lower()
    for topic in REFUSE_TOPICS:
        if topic.lower() not in adr_text:
            errors.append(f"ADR refuse-list missing mention: {topic}")

    if "гарант" in adr_text or "guarantor of the blockchain" in adr_text:
        errors.append("ADR must not claim NFT as L1 security guarantor")

    tok_text = TOKENOMICS.read_text(encoding="utf-8")
    if f"FOUNDER_PERCENT: float = {FOUNDER_PERCENT}" not in tok_text:
        errors.append(f"tokenomics founder percent expected {FOUNDER_PERCENT}")

    charter = CHARTER.read_text(encoding="utf-8")
    if "abstain" not in charter.lower():
        errors.append("charter must document founder abstain on self-grants")

    if errors:
        for e in errors:
            print(f"FAIL: {e}")
        sys.exit(1)

    _ok("docs present (ADR, charter, tokenomics, manifest gen)")
    _ok(f"allocation buckets sum to {SUPPLY_CAP}")
    _ok("founder seat #87, vote_weight=1, remint_forbidden")
    _ok("refuse-list topics present in ADR")
    _ok(f"founder ABS {FOUNDER_PERCENT}% unchanged in tokenomics")
    _ok("charter founder abstain rule")

    print("RESULT: PASS")


if __name__ == "__main__":
    main()
