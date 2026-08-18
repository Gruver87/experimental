"""Wave 46 — NFT marketplace SQLite persistence."""
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)


def test_nft_genesis_persists():
    from features.nft import NFTMarketplace
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "n.db"))
    db.initialize()

    m1 = NFTMarketplace(db=db)
    assert m1.get_stats()["total_tokens"] >= 5
    assert m1.get_stats()["persisted"] is True

    m2 = NFTMarketplace(db=db)
    assert m2.get_stats()["total_tokens"] == m1.get_stats()["total_tokens"]


def test_nft_mint_and_buy_persist():
    from features.nft import NFTMarketplace
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "m.db"))
    db.initialize()
    seller = "0x" + "a" * 40
    buyer = "0x" + "b" * 40
    db.update_balance(seller, 1000.0)
    db.update_balance(buyer, 1000.0)

    nft = NFTMarketplace(db=db)
    tid = "test_nft_wave46"
    r = nft.mint(tid, "Wave46", "test", "img", seller, price=50.0)
    assert r["success"] is True
    nft.list_for_sale(tid, seller, 50.0)
    buy = nft.buy(tid, buyer)
    assert buy["success"] is True

    nft2 = NFTMarketplace(db=db)
    tok = nft2.get_token(tid)
    assert tok["owner"] == buyer
    assert nft2.get_stats()["total_sales"] >= 1
    assert db.get_balance(buyer) == 950.0
    assert db.get_balance(seller) == 1046.5


def test_nft_paid_operations_require_balance_backend():
    from features.nft import NFTMarketplace

    nft = NFTMarketplace(db=None)
    seller = "0x" + "a" * 40
    buyer = "0x" + "b" * 40
    tid = "test_nft_no_backend"

    minted = nft.mint(tid, "NoBackend", "test", "img", seller, price=50.0)
    assert minted["success"] is False

    nft._mint_internal(tid, "NoBackend", "test", "img", seller, 50.0)
    assert nft.buy(tid, buyer)["success"] is False
    assert nft.make_offer(tid, buyer, 55.0) is None

    auction_id = nft.create_auction(tid, seller, 50.0)
    assert auction_id is not None
    bid = nft.place_bid(auction_id, buyer, 60.0)
    assert bid["success"] is False


def test_nft_auction_finalize_fails_if_token_missing():
    from features.nft import NFTMarketplace
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "auction.db"))
    db.initialize()
    seller = "0x" + "a" * 40
    buyer = "0x" + "b" * 40
    db.update_balance(seller, 1000.0)
    db.update_balance(buyer, 1000.0)

    nft = NFTMarketplace(db=db)
    tid = "test_nft_missing_before_finalize"
    assert nft.mint(tid, "Missing", "test", "img", seller, price=50.0)["success"] is True
    auction_id = nft.create_auction(tid, seller, 50.0)
    assert auction_id is not None
    assert nft.place_bid(auction_id, buyer, 60.0)["success"] is True

    del nft.tokens[tid]
    finalized = nft.finalize_auction(auction_id)

    assert finalized == {"success": False, "error": "Auction token not found"}
    assert nft.auctions[auction_id]["status"] == "settlement_failed"


def test_db_nft_token_roundtrip():
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "t.db"))
    db.initialize()
    db.save_nft_token({
        "token_id": "x1",
        "name": "Test",
        "description": "d",
        "image_url": "i",
        "owner": "0x1",
        "creator": "0x1",
        "price": 10.0,
        "for_sale": True,
        "created_at": 1700000000,
        "metadata": {"rarity": "rare"},
    })
    rows = db.get_nft_tokens()
    assert len(rows) == 1
    assert rows[0]["metadata"]["rarity"] == "rare"


def test_nft_price_is_satoshi_quantized_bool_refused():
    from storage.database import Database

    tmp = tempfile.mkdtemp()
    db = Database(os.path.join(tmp, "nft-money.db"))
    db.initialize()
    db.save_nft_token(
        {
            "token_id": "dust",
            "name": "Dust",
            "price": 10.0000003,
            "created_at": 1,
        }
    )
    assert db.get_nft_tokens()[0]["price"] == 10.0
    db.save_nft_offer(
        {
            "offer_id": "o1",
            "token_id": "dust",
            "bidder": "0x1",
            "price": 3.0000003,
            "created_at": 1,
        }
    )
    assert db.get_nft_offers()[0]["price"] == 3.0
    db.save_nft_sale({"token_id": "dust", "from": "0xa", "to": "0xb", "price": 4.0000003, "created_at": 1})
    assert db.get_nft_sales()[0]["price"] == 4.0
    db.save_nft_auction(
        {
            "auction_id": "a1",
            "token_id": "dust",
            "seller": "0xa",
            "start_price": 1.0000003,
            "reserve_price": 2.0000003,
            "current_bid": 1.0000003,
            "created_at": 1,
        }
    )
    auction = db.get_nft_auctions()[0]
    assert auction["start_price"] == 1.0
    assert auction["reserve_price"] == 2.0
    assert auction["current_bid"] == 1.0
    with pytest.raises(TypeError, match="bool is not an amount"):
        db.save_nft_token({"token_id": "bad", "name": "Bad", "price": True, "created_at": 1})
