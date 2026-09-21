"""P0 honesty: slash ejects proposer; ATXV/ATXR satoshi; mempool amount_satoshi."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consensus_engine import ConsensusEngine
from runtime.amount import tx_money_satoshi


def test_slash_ejects_proposer_selection():
    engine = ConsensusEngine()
    assert engine.add_validator("0xaaa", 1_000_000)
    assert engine.add_validator("0xbbb", 1)
    assert engine.slash_validator("0xaaa") is True
    assert engine.validators["0xaaa"].is_active is False
    # After slash, only active stake participates.
    for _ in range(20):
        p = engine.select_proposer()
        assert p is not None
        assert p.address == "0xbbb"
        assert p.is_active is True
        engine.advance_slot()
    assert engine.attest("0xaaa", 0, "0xh") is False


def test_tx_money_satoshi_prefers_explicit():
    sat = tx_money_satoshi(
        {
            "value": 1.0,
            "fee": 2.0,
            "value_satoshi": 7,
            "fee_satoshi": 9,
            "burned_satoshi": 0,
        }
    )
    assert sat["value_satoshi"] == 7
    assert sat["fee_satoshi"] == 9


def test_atxv_v2_roundtrip_satoshi():
    abs_native = pytest.importorskip("abs_native")
    row = {
        "hash": "0xdead",
        "block_height": 3,
        "from_addr": "0xAb",
        "to_addr": "0xCd",
        "value_satoshi": 1_500_000,
        "fee_satoshi": 10_000,
        "burned_satoshi": 0,
        "gas": 21000,
        "gas_used": 21000,
        "nonce": 1,
        "tx_data": "",
        "status": 1,
        "timestamp": 1,
    }
    blob = bytes(abs_native.pack_tx_row(json.dumps(row)))
    assert blob[:4] == b"ATXV"
    assert blob[4] == 2  # v2
    back = json.loads(abs_native.unpack_tx_row(blob))
    assert int(back["value_satoshi"]) == 1_500_000
    assert int(back["fee_satoshi"]) == 10_000
    assert abs(float(back["value"]) - 1.5) < 1e-9


def test_mempool_store_roundtrip_amount_satoshi():
    abs_native = pytest.importorskip("abs_native")
    if not hasattr(abs_native, "MempoolStore"):
        pytest.skip("MempoolStore missing")
    store = abs_native.MempoolStore(8, 0)
    assert store.insert(
        {
            "tx_hash": "h1",
            "from_addr": "0xa",
            "to_addr": "0xb",
            "amount": 2.0,
            "amount_satoshi": 2_000_000,
            "fee": 0.5,
            "fee_satoshi": 500_000,
            "nonce": 0,
            "signature": "",
            "public_key": "",
            "data": "",
            "gas": 21_000,
            "timestamp": 1.0,
        }
    )
    got = store.get("h1")
    assert int(got["amount_satoshi"]) == 2_000_000
    assert int(got["fee_satoshi"]) == 500_000
    with pytest.raises(Exception):
        store.insert(
            {
                "tx_hash": "h2",
                "from_addr": "0xa",
                "to_addr": "0xb",
                "amount": 1.0,
                "fee": 1.0,
                # missing fee_satoshi — must refuse IEEE bridge
                "nonce": 1,
            }
        )
