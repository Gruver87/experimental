#!/usr/bin/env python3
"""ADR 0019 Slice Q — gossipsub peer scoring lab.

2-node mesh: subscribe/publish, read peer score, apply app score penalty
and confirm score moves. Capability phase >= 16 + peer_score flag.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_peer_score_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 8.0, step: float = 0.05) -> bool:
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
        if not _wait(lambda: a.peer_id in b.connected_peers() and b.peer_id in a.connected_peers()):
            print("FAIL: peers not connected")
            return 1

        a.subscribe(topic)
        b.subscribe(topic)
        time.sleep(1.2)

        mid = a.publish(topic, b"slice-q-peer-score")
        if not mid:
            print("FAIL: empty publish id")
            return 1

        got: list[bytes] = []
        if not _wait(
            lambda: (
                got.extend(
                    bytes(data)
                    for _p, t, data in b.poll_gossip()
                    if t == topic or topic in str(t)
                )
                or bool(got)
            ),
            timeout=5.0,
        ):
            print("FAIL: gossip not received")
            return 1
        print("OK: gossip delivered under peer scoring")

        score = b.gossip_peer_score(a.peer_id)
        if score is None:
            print(f"FAIL: gossip_peer_score None for {a.peer_id}")
            return 1
        print(f"OK: peer score readable score={score}")

        if not b.set_gossip_app_score(a.peer_id, -50.0):
            print("FAIL: set_gossip_app_score returned False")
            return 1
        if not _wait(
            lambda: (b.gossip_peer_score(a.peer_id) or 0.0) < float(score),
            timeout=3.0,
        ):
            print(
                f"FAIL: app score did not lower peer score "
                f"before={score} after={b.gossip_peer_score(a.peer_id)}"
            )
            return 1
        print(f"OK: app score lowered peer score to {b.gossip_peer_score(a.peer_id)}")

        m = b.metrics()
        cap = b.capability_status()
        if not cap.get("peer_score"):
            print(f"FAIL: capability peer_score: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 16:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
        if int(m.get("libp2p_gossip_app_score_sets", 0)) < 1:
            print(f"FAIL: app_score_sets metric: {m}")
            return 1
        if int(m.get("libp2p_gossip_validation_accept", 0)) < 1:
            print(f"FAIL: validation_accept metric: {m}")
            return 1
        print(
            f"OK: metrics accept={m.get('libp2p_gossip_validation_accept')} "
            f"app_sets={m.get('libp2p_gossip_app_score_sets')}"
        )
    finally:
        for n in (a, b):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_peer_score_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; peer scoring opt-in path; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
