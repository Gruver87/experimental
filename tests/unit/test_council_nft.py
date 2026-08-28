#!/usr/bin/env python3
"""Council NFT genesis mint + soulbound (ADR 0022)."""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)


def test_council_genesis_mint_and_soulbound():
    from features.council_nft import (
        SUPPLY_CAP,
        council_token_id,
        genesis_mint_from_manifest,
        load_manifest,
    )
    from features.nft import NFTMarketplace
    from storage.database import Database

    manifest = os.path.join(ROOT, "docs", "genesis", "gruver87-council-manifest.json")
    if not os.path.isfile(manifest):
        return

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "council_unit.db"))
    db.initialize()
    nft = NFTMarketplace(db=db)
    nft.tokens.clear()

    result = genesis_mint_from_manifest(nft, manifest)
    assert result["ok"] is True
    assert result["minted"] == SUPPLY_CAP

    founder = nft.get_token(council_token_id(87))
    assert founder is not None
    assert founder["metadata"]["collection_id"] == "gruver87-council-87"

    xfer = nft.transfer(founder["token_id"], founder["owner"], "0x" + "e" * 40)
    assert xfer["success"] is False

    again = genesis_mint_from_manifest(nft, manifest)
    assert again["ok"] is False

    data = load_manifest(manifest)
    assert data["supply_cap"] == 87
