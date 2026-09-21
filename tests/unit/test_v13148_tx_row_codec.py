#!/usr/bin/env python3
"""v1.3.148: typed Rocks tx-row ATXV codec + dual-read."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.config import Config

abs_native = pytest.importorskip("abs_native")


def test_needles_v13148():
    assert hasattr(abs_native, "pack_tx_row")
    assert hasattr(abs_native, "unpack_tx_row")
    assert hasattr(abs_native, "tx_blob_to_json")
    assert hasattr(abs_native, "is_tx_row_binary")
    rs = (ROOT / "native" / "abs_native" / "src" / "tx_row.rs").read_text(
        encoding="utf-8"
    )
    assert "ATXV" in rs
    assert "pack_tx_row_value" in rs
    assert "tx_blob_to_value" in rs
    store = (ROOT / "storage" / "rocks_store.py").read_text(encoding="utf-8")
    assert "_pack_tx_blob" in store
    assert "_loads_tx_blob_or_none" in store
    assert "ATXV" in store
    notes = (ROOT / "RELEASE_NOTES_v1.3.148.md").read_text(encoding="utf-8")
    assert "1.3.148-industrial" in notes
    assert Config().node_version.startswith("1.3.")


def test_pack_unpack_roundtrip():
    row = {
        "hash": "0xdeadbeef",
        "block_height": 42,
        "from_addr": "0xAbC",
        "to_addr": "0xDeF",
        "value": 3.5,
        "gas": 21000,
        "gas_used": 21000,
        "fee": 0.002,
        "burned": 0.0,
        "nonce": 9,
        "tx_data": "0x",
        "status": 1,
        "timestamp": 1_700_000_000,
    }
    blob = bytes(abs_native.pack_tx_row(json.dumps(row)))
    assert abs_native.is_tx_row_binary(blob)
    assert blob[:4] == b"ATXV"
    back = json.loads(abs_native.unpack_tx_row(blob))
    assert back["hash"] == "0xdeadbeef"
    assert back["from_addr"] == "0xabc"
    assert int(back["block_height"]) == 42
    assert int(back["status"]) == 1
    assert int(back["nonce"]) == 9
    assert "value_satoshi" in back
    assert int(back["value_satoshi"]) == 3_500_000


def test_dual_read_legacy_json():
    row = {
        "hash": "0x11",
        "block_height": 1,
        "from_addr": "0x1",
        "to_addr": "0x2",
        "value": 0.0,
        "gas": 21000,
        "gas_used": 21000,
        "fee": 0.0,
        "burned": 0.0,
        "nonce": 0,
        "tx_data": "",
        "status": 0,
        "timestamp": 1,
    }
    blob = json.dumps(row).encode("utf-8")
    assert not abs_native.is_tx_row_binary(blob)
    decoded = json.loads(abs_native.tx_blob_to_json(blob))
    assert decoded["hash"] == "0x11"


def test_status_fail_closed():
    row = {
        "hash": "0x22",
        "block_height": 2,
        "from_addr": "0x1",
        "to_addr": "0x2",
        "value": 0.0,
        "gas": 21000,
        "gas_used": 21000,
        "fee": 0.0,
        "burned": 0.0,
        "nonce": 0,
        "tx_data": "",
        "status": "unknown-xyz",
        "timestamp": 1,
    }
    blob = bytes(abs_native.pack_tx_row(json.dumps(row)))
    back = json.loads(abs_native.unpack_tx_row(blob))
    assert int(back["status"]) == 0
