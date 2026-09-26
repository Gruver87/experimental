#!/usr/bin/env python3
"""Long-Range WS checkpoint gossip lab (ADR 0017 wave-14).

Exercises CheckpointStore merge + P2P ``ws_checkpoint`` handler without live mesh.

Usage:
  python scripts/long_range_gossip_lab.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consensus.long_range import (
    CheckpointCertificate,
    CheckpointStore,
    ingest_peer_ws_checkpoint,
    merge_peer_certificate_dict,
)
from consensus.long_range.gossip import (
    OUTCOME_ADOPTED,
    OUTCOME_STALE_HEIGHT,
    OUTCOME_UNARMED,
)
from network.p2p_node import MSG_WS_CHECKPOINT, P2PNode
from runtime.config import Config


def _hash(n: int) -> str:
    return f"{n:064x}"


class _FakePeer:
    peer_id = "lab-peer-1"

    async def send(self, msg_type: str, data=None) -> bool:
        return True


def _cert(height: int, *, issuer: str = "lab-a") -> CheckpointCertificate:
    return CheckpointCertificate.issue(
        height=height,
        block_hash=_hash(height),
        issuer=issuer,
    )


def main() -> int:
    cfg = Config()
    cfg.deployment_mode = "dev"
    cfg.feature_long_range = True
    cfg.p2p_native_transport = False
    cfg.require_native_crypto = False
    cfg.bootstrap_peers = []
    os.environ.pop("FEATURE_LONG_RANGE", None)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ws_gossip.json"
        os.environ["ABS_WS_CHECKPOINT_PATH"] = str(path)

        # Store merge: adopt higher anchor, refuse stale.
        store = CheckpointStore()
        high = _cert(20)
        low = _cert(10)
        r1 = merge_peer_certificate_dict(store, dict(high.to_dict()))
        if r1.get("outcome") != OUTCOME_ADOPTED or len(store) != 1:
            print(f"FAIL: first adopt expected adopted, got {r1}")
            return 1
        r2 = merge_peer_certificate_dict(store, dict(low.to_dict()))
        if r2.get("outcome") != OUTCOME_STALE_HEIGHT:
            print(f"FAIL: stale cert must refuse, got {r2}")
            return 1
        store.save(path)
        if not path.is_file():
            print("FAIL: persist after adopt")
            return 1

        reloaded = CheckpointStore.load(path)
        if reloaded.latest() is None or reloaded.latest().anchor.height != 20:
            print("FAIL: reload must retain h=20 anchor")
            return 1

        # ingest_peer_ws_checkpoint: adopt h=25 and persist.
        newer = _cert(25, issuer="lab-b")
        r3 = ingest_peer_ws_checkpoint(config=cfg, data=dict(newer.to_dict()))
        if not r3.get("adopted"):
            print(f"FAIL: ingest adopt h=25, got {r3}")
            return 1
        again = CheckpointStore.load(path)
        if again.latest() is None or again.latest().anchor.height != 25:
            print("FAIL: persisted store must show h=25")
            return 1

        # P2P handler: armed node adopts peer cert at/below local tip.
        chain = MagicMock()
        # Tip must be >= cert height — adopt above tip is deferred (ahead_of_tip).
        chain.get_height = MagicMock(return_value=30)
        chain.get_block = MagicMock(
            return_value={"hash": _hash(30), "height": 30, "parent_hash": _hash(29)}
        )
        node = P2PNode(cfg, chain, MagicMock())
        node.tip_safety_shadow = MagicMock()
        node.tip_safety_shadow.sync_from_chain = MagicMock(return_value=True)

        peer_cert = _cert(30, issuer="peer-1")
        asyncio.run(node.handle_ws_checkpoint(_FakePeer(), dict(peer_cert.to_dict())))
        adopt_n = int(getattr(node, "_ws_checkpoint_adopt_total", 0) or 0)
        if adopt_n < 1:
            print(f"FAIL: P2P ws_checkpoint adopt counter (adopt_total={adopt_n})")
            return 1
        if not node.tip_safety_shadow.sync_from_chain.called:
            print("FAIL: shadow must resync after adopt")
            return 1

        # Ahead-of-tip cert must defer (not brick catch-up).
        ahead = _cert(40, issuer="peer-ahead")
        before_defer = int(getattr(node, "_ws_checkpoint_ahead_defer_total", 0) or 0)
        asyncio.run(node.handle_ws_checkpoint(_FakePeer(), dict(ahead.to_dict())))
        after_defer = int(getattr(node, "_ws_checkpoint_ahead_defer_total", 0) or 0)
        latest = CheckpointStore.load(path).latest()
        if latest is None or int(latest.anchor.height) >= 40:
            print("FAIL: ahead_of_tip must not persist future anchor")
            return 1
        if after_defer < before_defer + 1:
            print("FAIL: ahead_of_tip counter not bumped")
            return 1

        # Unarmed prod refuses gossip at merge layer.
        prod = Config()
        prod.deployment_mode = "prod"
        prod.feature_long_range = False
        r_unarmed = ingest_peer_ws_checkpoint(
            config=prod, data=dict(peer_cert.to_dict())
        )
        if r_unarmed.get("outcome") != OUTCOME_UNARMED:
            print(f"FAIL: prod must refuse WS gossip, got {r_unarmed}")
            return 1

        if MSG_WS_CHECKPOINT not in (
            __import__("network.p2p_node", fromlist=["ALLOWED_WIRE_TYPES"]).ALLOWED_WIRE_TYPES
        ):
            print("FAIL: MSG_WS_CHECKPOINT must be allowlisted")
            return 1

    print("OK: long_range_gossip_lab PASS (store merge + P2P ws_checkpoint)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
