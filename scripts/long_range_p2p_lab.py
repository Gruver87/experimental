#!/usr/bin/env python3
"""Long-Range P2P import lab (ADR 0017 wave-13).

Exercises TipSafetyShadowObserver + Config.feature_long_range on a fake chain
(import refuse below WS anchor; valid child accepted). No live mesh required.

Usage:
  python scripts/long_range_p2p_lab.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consensus.long_range import bind_persisted_ws
from consensus.tip_safety.shadow import TipSafetyShadowObserver
from network.p2p_node import P2PNode
from runtime.config import Config


def _h(n: int) -> str:
    return f"{n:064x}"


def _block(height: int, *, n: int | None = None) -> dict:
    digest = _h(n if n is not None else height)
    parent = "0" * 64 if height == 0 else _h(height - 1)
    return {
        "height": height,
        "hash": digest,
        "parent_hash": parent,
        "transactions": [],
    }


class _Chain:
    GENESIS_HASH = "0" * 64

    def __init__(self, height: int) -> None:
        self._height = height
        self._blocks = {0: _block(0, n=0xA1)}
        for i in range(1, height + 1):
            blk = _block(i, n=0xA1 + i)
            blk["parent_hash"] = self._blocks[i - 1]["hash"]
            self._blocks[i] = blk

    def get_height(self) -> int:
        return self._height

    def get_block(self, height: int):
        return self._blocks.get(height)

    def get_last_block(self):
        return self._blocks.get(self._height)

    def import_block(self, data: dict) -> bool:
        h = int(data["height"])
        if h != self._height + 1:
            return False
        if data.get("parent_hash") != self._blocks[self._height]["hash"]:
            return False
        self._blocks[h] = dict(data)
        self._height = h
        return True


def _lab_node(cfg: Config, chain: _Chain) -> P2PNode:
    node = P2PNode(cfg, chain, MagicMock())
    node.tip_safety_shadow = TipSafetyShadowObserver(
        enabled=True, enforce=True, config=cfg
    )
    return node


def main() -> int:
    cfg = Config()
    cfg.deployment_mode = "dev"
    cfg.feature_long_range = True
    cfg.p2p_native_transport = False
    cfg.require_native_crypto = False
    cfg.bootstrap_peers = []
    cfg.tip_safety_enforce = True
    os.environ.pop("FEATURE_LONG_RANGE", None)

    with tempfile.TemporaryDirectory() as tmp:
        # Refuse: anchor at h=10, chain tip at h=2, candidate h=3 is below anchor.
        refuse_path = Path(tmp) / "ws_refuse.json"
        bind_persisted_ws(path=refuse_path, env_height="10", env_hash="ff" * 32)
        os.environ["ABS_WS_CHECKPOINT_PATH"] = str(refuse_path)

        chain = _Chain(2)
        node = _lab_node(cfg, chain)
        assert node.tip_safety_shadow.sync_from_chain(chain) is True
        tip = chain.get_last_block()
        below = {
            "height": 3,
            "hash": _h(0xB0),
            "parent_hash": tip["hash"],
            "transactions": [],
        }
        if node.import_block(below) is not False:
            print("FAIL: import below WS anchor must refuse")
            return 1
        if int(node.tip_safety_shadow.reject_by_code.get("ws_below_ws_anchor", 0)) < 1:
            print("FAIL: expected ws_below_ws_anchor reject code")
            return 1

        # Accept: anchor at live tip; child h=3 extends above checkpoint.
        accept_path = Path(tmp) / "ws_accept.json"
        chain2 = _Chain(2)
        tip2 = chain2.get_last_block()
        bind_persisted_ws(
            path=accept_path,
            env_height=str(tip2["height"]),
            env_hash=str(tip2["hash"]),
        )
        os.environ["ABS_WS_CHECKPOINT_PATH"] = str(accept_path)

        node2 = _lab_node(cfg, chain2)
        assert node2.tip_safety_shadow.sync_from_chain(chain2) is True
        good = {
            "height": 3,
            "hash": _h(0xC0),
            "parent_hash": tip2["hash"],
            "transactions": [],
        }
        if node2.import_block(good) is not True:
            print("FAIL: valid child of WS anchor must import")
            return 1
        if chain2.get_height() != 3:
            print("FAIL: chain height must advance to 3")
            return 1

    print("OK: long_range_p2p_lab PASS (config.feature_long_range + P2P enforce)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
