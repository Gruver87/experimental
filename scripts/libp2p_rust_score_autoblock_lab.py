#!/usr/bin/env python3
"""ADR 0019 Slice S — gossip score auto-block lab.

2-node mesh: enable score→block sweep, apply heavy app-score penalty,
wait for native block_list entry.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_score_autoblock_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 12.0, step: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return False


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    topic = str(getattr(abs_native, "ABS_GOSSIP_BLOCKS_TOPIC", "abs/blocks/1.0.0"))
    a = abs_native.libp2p_node_new(enable_mdns=False)
    b = abs_native.libp2p_node_new(enable_mdns=False)
    try:
        a_addr = a.listen("/ip4/127.0.0.1/tcp/0")[0]
        b.listen("/ip4/127.0.0.1/tcp/0")
        b.dial(a_addr)
        if not _wait(
            lambda: a.peer_id in b.connected_peers() and b.peer_id in a.connected_peers()
        ):
            print("FAIL: peers not connected")
            return 1

        a.subscribe(topic)
        b.subscribe(topic)
        time.sleep(1.0)
        a.publish(topic, b"slice-s-score-autoblock")
        _wait(lambda: bool(list(b.poll_gossip())), timeout=3.0)

        score = b.gossip_peer_score(a.peer_id)
        if score is None:
            print("FAIL: no peer score before penalty")
            return 1
        print(f"OK: baseline score={score}")

        # Default graylist -80; app_specific_weight=10 → -50 app ≈ -500 total.
        b.set_score_autoblock(True, -80.0)
        if not b.set_gossip_app_score(a.peer_id, -50.0):
            print("FAIL: set_gossip_app_score")
            return 1
        scored = b.gossip_peer_score(a.peer_id)
        print(f"OK: penalized score={scored}")

        if not _wait(
            lambda: (
                a.peer_id in b.blocked_peers()
                and int(b.metrics().get("libp2p_score_autoblocks", 0)) >= 1
            ),
            timeout=8.0,
        ):
            print(
                f"FAIL: autoblock did not fire "
                f"blocked={b.blocked_peers()} metrics={b.metrics()}"
            )
            return 1
        print(
            f"OK: score autoblock "
            f"blocks={b.metrics().get('libp2p_score_autoblocks')} "
            f"blocked={b.blocked_peers()}"
        )

        cap = b.capability_status()
        if not cap.get("score_autoblock"):
            print(f"FAIL: capability score_autoblock: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 18:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
        print(f"OK: capability phase={cap.get('phase')}")
    finally:
        for n in (a, b):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_score_autoblock_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; score autoblock opt-in; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
