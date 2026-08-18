#!/usr/bin/env python3
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, ROOT)

from runtime.config import Config
from storage.hybrid_database import HybridDatabase


@pytest.fixture
def hybrid_db(tmp_path):
    try:
        import abs_native  # noqa: F401
    except ImportError:
        pytest.skip("abs_native not built")
    cfg = Config()
    cfg.db_path = str(tmp_path / "chainstore")
    cfg.db_engine = "rocksdb"
    db = HybridDatabase(cfg)
    db.initialize()
    yield db
    db.close()


def test_nft_tokens_rocks_roundtrip(hybrid_db):
    hybrid_db.save_nft_token({
        "token_id": "nft-1",
        "name": "Test",
        "owner": "0x" + "11" * 20,
        "creator": "0x" + "22" * 20,
        "price": 1.5,
        "for_sale": True,
        "created_at": int(time.time()),
        "metadata": {"tier": "gold"},
    })
    tokens = hybrid_db.get_nft_tokens()
    assert len(tokens) == 1
    assert tokens[0]["token_id"] == "nft-1"
    assert tokens[0]["metadata"]["tier"] == "gold"
    assert hybrid_db.get_meta("aux_nft_tokens_migrated_v1") is True


def test_nft_token_price_is_satoshi_quantized_bool_refused(hybrid_db):
    hybrid_db.save_nft_token({
        "token_id": "nft-dust",
        "name": "Dust",
        "price": 1.5000003,
        "created_at": int(time.time()),
    })
    tokens = [t for t in hybrid_db.get_nft_tokens() if t["token_id"] == "nft-dust"]
    assert tokens[0]["price"] == 1.5
    with pytest.raises(TypeError, match="bool is not an amount"):
        hybrid_db.save_nft_token({
            "token_id": "nft-bool",
            "name": "Bad",
            "price": True,
            "created_at": int(time.time()),
        })
