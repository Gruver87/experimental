#!/usr/bin/env python3
"""Canonical serializer prefers fee_satoshi / amount_satoshi over IEEE×1e6."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from blockchain.canonical_serializer import CanonicalSerializer, _field_satoshi


def test_field_satoshi_prefers_explicit() -> None:
    assert _field_satoshi({"fee_satoshi": 42, "fee": 9.0}, "fee_satoshi", "fee") == 42


def test_field_satoshi_derives_via_to_satoshi() -> None:
    assert _field_satoshi({"fee": 1.5}, "fee_satoshi", "fee") == 1_500_000


def test_serialize_block_uses_fee_satoshi() -> None:
    raw = CanonicalSerializer.serialize_block(
        {
            "height": 1,
            "previous_hash": "00" * 32,
            "timestamp": 1,
            "miner": "m",
            "nonce": 0,
            "transactions": [
                {
                    "hash": "aa",
                    "from": "0xa",
                    "to": "0xb",
                    "amount": 2.0,
                    "fee": 0.5,
                    "fee_satoshi": 500_000,
                    "amount_satoshi": 2_000_000,
                    "nonce": 0,
                    "timestamp": 1,
                }
            ],
        }
    )
    doc = json.loads(raw)
    tx = doc["transactions"][0]
    assert tx["fee_satoshi"] == 500_000
    assert tx["amount_satoshi"] == 2_000_000
