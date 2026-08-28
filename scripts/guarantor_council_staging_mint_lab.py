#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gruver87 council staging genesis mint lab — ADR 0022.

Mints 87 council NFTs from manifest into in-memory/temp DB marketplace;
verifies cap, remint refuse, soulbound transfer refuse. No Docker mesh.

Usage:
  python scripts/guarantor_council_staging_mint_lab.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.council_nft import (
    COLLECTION_ID,
    SUPPLY_CAP,
    council_stats,
    council_token_id,
    genesis_mint_from_manifest,
    is_council_token,
    load_manifest,
    refuse_extra_mint,
)
from features.nft import NFTMarketplace


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    print("=== guarantor_council_staging_mint_lab (ADR 0022) ===")
    manifest = ROOT / "docs" / "genesis" / "gruver87-council-manifest.json"
    if not manifest.is_file():
        return _fail("run guarantor_council_manifest_gen.py first")

    data = load_manifest(manifest)
    if data.get("chain_id_staging") == 778888:
        return _fail("manifest must not target prod chain 778888")

    tmp = tempfile.mkdtemp()
    try:
        from storage.database import Database

        db = Database(os.path.join(tmp, "council_mint_lab.db"))
        db.initialize()
        db.update_balance("0xcouncil_genesis_ceremony000000000001", 1000.0)

        nft = NFTMarketplace(db=db)
        nft.tokens.clear()

        first = genesis_mint_from_manifest(nft, manifest)
        if not first.get("ok"):
            return _fail(f"genesis mint failed: {first}")
        if first.get("minted") != SUPPLY_CAP:
            return _fail(f"expected {SUPPLY_CAP} minted, got {first.get('minted')}")

        second = genesis_mint_from_manifest(nft, manifest)
        if second.get("ok") is not False:
            return _fail("remint must refuse")
        if second.get("error") != "council_genesis_already_minted":
            return _fail(f"unexpected remint error: {second}")

        stats = council_stats(nft)
        if not stats.get("genesis_complete"):
            return _fail("genesis_complete must be true")
        if stats.get("minted_count") != SUPPLY_CAP:
            return _fail("minted_count mismatch")

        founder_tid = council_token_id(87)
        founder = nft.get_token(founder_tid)
        if not founder:
            return _fail("founder seat missing")
        if founder["metadata"].get("soulbound_until") != "2029-07-14":
            return _fail("founder soulbound_until mismatch")

        xfer = nft.transfer(
            founder_tid,
            founder["owner"],
            "0x" + "c" * 40,
        )
        if xfer.get("success") is not False:
            return _fail("soulbound founder transfer must refuse")
        if "soulbound" not in str(xfer.get("error", "")).lower():
            return _fail(f"expected soulbound error, got {xfer}")

        refuse88 = refuse_extra_mint(nft, 88)
        if refuse88 is None or "cap" not in refuse88:
            return _fail("mint #88 must refuse cap")

        non_soul = nft.get_token(council_token_id(1))
        if non_soul:
            ok_xfer = nft.transfer(
                council_token_id(1),
                non_soul["owner"],
                "0x" + "d" * 40,
            )
            if ok_xfer.get("success") is not True:
                return _fail("non-soulbound council token should transfer in lab")

        council_rows = [t for t in nft.get_all() if is_council_token(t["token_id"])]
        if len(council_rows) != SUPPLY_CAP:
            return _fail("council token count in marketplace mismatch")

        hashes = {t["metadata"].get("image_sha256") for t in council_rows}
        if len(hashes) != SUPPLY_CAP:
            return _fail("duplicate image_sha256 in minted council set")

        print(f"  OK: genesis mint {SUPPLY_CAP} ({COLLECTION_ID})")
        print(f"  OK: remint refused")
        print(f"  OK: founder soulbound transfer refused")
        print(f"  OK: cap 88 refused")
        print(f"  OK: unique image_sha256 per token")
        print("RESULT: PASS")
        return 0
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
