#!/usr/bin/env python3
"""v1.3.38: native GHOST / LMD / simple block apply+replay kernels."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crypto import native
from consensus.ghost import get_cumulative_weight, select_head, get_chain_from_head
from consensus.lmd import LMDTable


def test_native_ghost_symbols():
    assert native.native_available()
    assert hasattr(native, "ghost_select_head")
    assert hasattr(native, "ghost_cumulative_weight")
    assert hasattr(native, "ghost_chain_from_head")
    assert hasattr(native, "lmd_compute_weights")
    assert hasattr(native, "blockchain_apply_simple_block")
    assert hasattr(native, "blockchain_replay_simple_blocks")


def test_ghost_native_matches_deep_linear():
    tree = {}
    weights = {}
    prev = None
    for i in range(200):
        h = f"block_{i:04d}"
        tree[h] = {"parent": prev, "number": i, "children": []}
        if prev:
            tree[prev]["children"].append(h)
        weights[h] = 1
        prev = h

    assert select_head(tree, weights) == "block_0199"
    assert get_cumulative_weight("block_0000", tree, weights) == 200
    chain = get_chain_from_head(tree, weights)
    assert chain[0] == "block_0000"
    assert chain[-1] == "block_0199"


def test_lmd_weights_native():
    table = LMDTable()
    table.add_validator("v1", 100)
    table.add_validator("v2", 50)
    assert table.update("v1", "0xaaa", 1)
    assert table.update("v2", "0xaaa", 1)
    assert table.update("v2", "0xbbb", 2)
    weights = table.get_weights()
    assert weights["0xaaa"] == 100
    assert weights["0xbbb"] == 50


def test_blockchain_apply_simple_block_kernel():
    accounts = {
        "alice": {"balance": 10_000_000, "nonce": 0},
        "bob": {"balance": 0, "nonce": 0},
        "miner": {"balance": 0, "nonce": 0},
    }
    txs = [
        {
            "from": "alice",
            "to": "bob",
            "value": 1.0,
            "gas": 21000,
            "nonce": 0,
            "data": "",
        }
    ]
    raw = native.blockchain_apply_simple_block(
        json.dumps(accounts),
        json.dumps(txs),
        0.000_000_1,
        0.02,
        "miner",
        "",
        50.0,
        10_000_000,
        21_000_000 * 1_000_000,
    )
    result = json.loads(raw)
    assert result["native_apply"] is True
    assert result["accounts"]["alice"]["nonce"] == 1
    assert result["accounts"]["bob"]["balance"] == 1_000_000
    assert result["reward_sat"] == 50_000_000


def test_blockchain_replay_rejects_evm_calldata():
    accounts = {"alice": {"balance": 10_000_000, "nonce": 0}}
    blocks = [
        {
            "miner": "miner",
            "transactions": [
                {
                    "from": "alice",
                    "to": "bob",
                    "value": 0.1,
                    "gas": 21000,
                    "nonce": 0,
                    "data": "0xdead",
                }
            ],
        }
    ]
    try:
        native.blockchain_replay_simple_blocks(
            json.dumps(accounts),
            json.dumps(blocks),
            0.000_000_1,
            0.02,
            "",
            50.0,
            10_000_000,
            21_000_000 * 1_000_000,
        )
        assert False, "expected evm_tx_not_supported"
    except Exception as exc:
        assert "evm_tx_not_supported" in str(exc)


def test_blockchain_wires_native_helpers():
    text = Path("core/blockchain.py").read_text(encoding="utf-8")
    state = Path("core/components/state_service.py").read_text(encoding="utf-8")
    assert "_apply_simple_block_native" in text or "_apply_simple_block_native" in state
    assert "_replay_simple_range_native" in text or "_replay_simple_range_native" in state
    assert (
        "blockchain_apply_simple_block" in text
        or "blockchain_apply_simple_block" in state
    )
    assert (
        "blockchain_replay_simple_blocks" in text
        or "blockchain_replay_simple_blocks" in state
    )
    ghost = Path("consensus/ghost.py").read_text(encoding="utf-8")
    assert "ghost_select_head" in ghost
    assert "ghost_cumulative_weight" in ghost
    assert '_native_fb("ghost_select_head"' in ghost
    casper = Path("consensus/finality_casper.py").read_text(encoding="utf-8")
    assert '_native_fb("ffg_accumulate_vote"' in casper
    lmd = Path("consensus/lmd.py").read_text(encoding="utf-8")
    assert '_native_fb("lmd_compute_weights"' in lmd
