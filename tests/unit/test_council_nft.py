#!/usr/bin/env python3
"""Council NFT genesis mint + soulbound (ADR 0022)."""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

MANIFEST = os.path.join(ROOT, "docs", "genesis", "gruver87-council-manifest.json")


def test_council_genesis_mint_and_soulbound():
    from features.council_nft import (
        SUPPLY_CAP,
        council_token_id,
        genesis_mint_from_manifest,
        load_manifest,
    )
    from features.nft import NFTMarketplace
    from storage.database import Database

    if not os.path.isfile(MANIFEST):
        return

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "council_unit.db"))
    db.initialize()
    nft = NFTMarketplace(db=db)
    nft.tokens.clear()

    result = genesis_mint_from_manifest(nft, MANIFEST)
    assert result["ok"] is True
    assert result["minted"] == SUPPLY_CAP

    founder = nft.get_token(council_token_id(87))
    assert founder is not None
    assert founder["metadata"]["collection_id"] == "gruver87-council-87"

    xfer = nft.transfer(founder["token_id"], founder["owner"], "0x" + "e" * 40)
    assert xfer["success"] is False

    again = genesis_mint_from_manifest(nft, MANIFEST)
    assert again["ok"] is False

    data = load_manifest(MANIFEST)
    assert data["supply_cap"] == 87


def test_council_genesis_mint_refuses_second_call():
    from features.council_nft import genesis_mint_from_manifest
    from features.nft import NFTMarketplace
    from storage.database import Database

    if not os.path.isfile(MANIFEST):
        return

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "council_refuse.db"))
    db.initialize()
    nft = NFTMarketplace(db=db)
    nft.tokens.clear()

    first = genesis_mint_from_manifest(nft, MANIFEST)
    assert first["ok"] is True
    second = genesis_mint_from_manifest(nft, MANIFEST)
    assert second["ok"] is False
    assert second["error"] == "council_genesis_already_minted"


def test_council_token_id_format():
    from features.council_nft import council_token_id, is_council_token

    tid = council_token_id(87)
    assert tid == "gruver87-council-87:087"
    assert is_council_token(tid) is True
    assert is_council_token("abs_genesis_crown") is False
