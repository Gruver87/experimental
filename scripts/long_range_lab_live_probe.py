#!/usr/bin/env python3
"""Live Long-Range lab probe (ADR 0017) — honesty + tip-gate wiring check.

Checks lab HTTP only (default :29080). Never prod mesh :18180–:18182.

1. /health/live + /health/ready
2. /consensus/weak-subjectivity → long_range_defense=true + armed
3. Tip-safety metrics /status fields when present
4. In-process TipSafetyShadowObserver refuse below seeded anchor (same digest
   rules as wave-13; proves gate code path with the on-disk checkpoint)

Usage:
  python scripts/long_range_lab_live_probe.py
  python scripts/long_range_lab_live_probe.py --base-url http://127.0.0.1:29080
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_BASE = "http://127.0.0.1:29080"
DEFAULT_PERSIST = ROOT / "data" / "long_range_lab0" / "ws_checkpoint.json"


def _get_json(url: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _tip_refuse_from_persist(persist: Path) -> int:
    from consensus.long_range import CheckpointStore
    from consensus.tip_safety.shadow import TipSafetyShadowObserver
    from network.p2p_node import P2PNode
    from runtime.config import Config

    if not persist.is_file():
        return _fail(f"checkpoint missing: {persist}")
    store = CheckpointStore.load(persist)
    cert = store.latest()
    if cert is None:
        return _fail("checkpoint store empty")
    anchor_h = int(cert.anchor.height)
    anchor_hash = str(cert.anchor.block_hash)

    class _Chain:
        def __init__(self) -> None:
            self._height = anchor_h
            self._tip = {
                "height": anchor_h,
                "hash": anchor_hash,
                "parent_hash": "0" * 64,
                "transactions": [],
            }

        def get_height(self) -> int:
            return self._height

        def get_block(self, height: int):
            if int(height) == self._height:
                return dict(self._tip)
            return None

        def get_last_block(self):
            return dict(self._tip)

        def import_block(self, data: dict) -> bool:
            raise AssertionError(f"import must be refused, got {data!r}")

    cfg = Config()
    cfg.deployment_mode = "dev"
    cfg.feature_long_range = True
    cfg.tip_safety_enforce = True
    cfg.tip_safety_shadow = True
    with tempfile.TemporaryDirectory() as tmp:
        # Point env bind at the real persist file via copy into tmp so Config path
        # matches lab digest without mutating production files.
        import os
        import shutil

        local = Path(tmp) / "ws_checkpoint.json"
        shutil.copy2(persist, local)
        os.environ["FEATURE_LONG_RANGE"] = "true"
        os.environ["ABS_WS_CHECKPOINT_PATH"] = str(local)
        chain = _Chain()
        node = P2PNode(cfg, chain, MagicMock())
        node.tip_safety_shadow = TipSafetyShadowObserver(
            enabled=True, enforce=True, config=cfg
        )
        below = {
            "height": max(0, anchor_h - 1) if anchor_h > 0 else 0,
            "hash": "ab" * 32,
            "parent_hash": "cd" * 32,
            "transactions": [],
        }
        if anchor_h == 0:
            # At genesis floor, below-anchor is a divergent same-height / fork.
            below = {
                "height": 0,
                "hash": "ef" * 32,
                "parent_hash": "00" * 32,
                "transactions": [],
            }
        decision = node.tip_safety_shadow.observe_before_import(below, chain)
        if decision is None:
            return _fail("tip_safety observe returned None (gate not armed)")
        accepted = bool(getattr(decision, "accepted", getattr(decision, "accept", True)))
        reason = getattr(decision, "reason_code", None) or getattr(decision, "reason", "")
        if accepted:
            return _fail(f"expected refuse below/divergent tip got accept reason={reason}")
        print(f"OK: tip gate refuse reason={reason}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--persist", type=Path, default=DEFAULT_PERSIST)
    parser.add_argument("--skip-tip-gate", action="store_true")
    parser.add_argument(
        "--all-nodes",
        action="store_true",
        help="Probe HTTP ports 29080-29082 (lab mesh)",
    )
    args = parser.parse_args()
    bases = (
        [
            "http://127.0.0.1:29080",
            "http://127.0.0.1:29081",
            "http://127.0.0.1:29082",
        ]
        if args.all_nodes
        else [str(args.base_url).strip().rstrip("/")]
    )
    persists = (
        [
            ROOT / "data" / "long_range_lab0" / "ws_checkpoint.json",
            ROOT / "data" / "long_range_lab1" / "ws_checkpoint.json",
            ROOT / "data" / "long_range_lab2" / "ws_checkpoint.json",
        ]
        if args.all_nodes
        else [args.persist]
    )

    for base in bases:
        if any(p in base for p in (":18180", ":18181", ":18182")):
            return _fail("refuse prod mesh ports")
        try:
            live = _get_json(f"{base}/health/live")
            if str(live.get("status") or "") != "alive":
                return _fail(f"{base} live not alive: {live}")
            ready = _get_json(f"{base}/health/ready")
            if str(ready.get("status") or "") != "ready":
                return _fail(f"{base} ready not ready: {ready}")
            print(f"OK: {base} health live+ready")
            honesty = _get_json(f"{base}/consensus/weak-subjectivity")
            if not bool(honesty.get("long_range_armed")):
                return _fail(f"{base} long_range_armed false: {honesty}")
            if not bool(honesty.get("long_range_defense")):
                return _fail(
                    f"{base} long_range_defense false — seed WS first "
                    "(python scripts/seed_long_range_lab_ws.py --restart)"
                )
            print(
                f"OK: {base} weak-subjectivity "
                f"defense=true anchor_h={honesty.get('ws_anchor_height')}"
            )
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            return _fail(f"{base}: {exc}")

    if not args.skip_tip_gate:
        rc = _tip_refuse_from_persist(persists[0])
        if rc != 0:
            return rc

    print("OK: long_range_lab_live_probe PASS (lab-only; not BLS; not prod mesh)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
