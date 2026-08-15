#!/usr/bin/env python3
"""ADR 0019 Slice DA — add/remove/expire match the canonical charge key.

After Slice CZ the Python book and crate ExternalAddresses store the key
without trailing ``/p2p/<peer>``. Operator ``add_external_address(suffix)``
must not occupy a second unique slot. ``remove_external_address(suffix)``
must hit the charged listen and drop it from the crate book (otherwise
expire/remove miss the slot — unique-cap lie).

Capability ``behaviour_external_expired_canonical`` / phase >= 104.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_behaviour_external_expired_canonical_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WANT = "expire_canonical_charge_key"


def _wait(pred, timeout: float = 5.0, step: float = 0.05) -> bool:
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

    mod_strategy = str(getattr(abs_native, "BEHAVIOUR_EXTERNAL_EXPIRED_STRATEGY", ""))
    if mod_strategy != WANT:
        print(f"FAIL: module strategy {mod_strategy!r} != {WANT}")
        return 1

    node = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        cap = node.capability_status()
        if not cap.get("behaviour_external_expired_canonical"):
            print(f"FAIL: capability behaviour_external_expired_canonical: {cap}")
            return 1
        if cap.get("behaviour_external_expired_strategy") != WANT:
            print(
                "FAIL: capability strategy "
                f"{cap.get('behaviour_external_expired_strategy')!r} != {WANT}"
            )
            return 1
        if int(cap.get("phase", 0)) < 104:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1

        listen = node.listen("/ip4/127.0.0.1/tcp/0")[0]
        if not _wait(lambda: listen in node.external_addrs(), timeout=4.0):
            print(f"FAIL: listen not charged: {node.external_addrs()}")
            return 1
        if not _wait(lambda: listen in node.swarm_external_addrs(), timeout=4.0):
            print(f"FAIL: listen not in crate book: {node.swarm_external_addrs()}")
            return 1
        used0 = int(node.metrics().get("libp2p_advertised_externals_used", 0))
        if used0 != 1:
            print(f"FAIL: used {used0} after one listen")
            return 1

        suffix = f"{listen}/p2p/{node.peer_id}"
        added = node.add_external_address(suffix)
        if added:
            print(f"FAIL: suffix add occupied a second unique slot used={node.metrics()}")
            return 1
        used1 = int(node.metrics().get("libp2p_advertised_externals_used", 0))
        if used1 != 1:
            print(f"FAIL: used grew after suffix add used={used1}")
            return 1
        crate = list(node.swarm_external_addrs())
        if listen not in crate:
            print(f"FAIL: listen evicted by suffix add: {crate}")
            return 1
        if suffix in crate:
            print(f"FAIL: suffix occupied crate book: {crate}")
            return 1
        print("OK: suffix add is already-charged (no second slot)")

        removed = node.remove_external_address(suffix)
        if not removed:
            print("FAIL: suffix remove missed charged listen")
            return 1
        if listen in node.external_addrs():
            print(f"FAIL: listen still in python book: {node.external_addrs()}")
            return 1
        crate2 = list(node.swarm_external_addrs())
        if listen in crate2:
            print(f"FAIL: listen still in crate book after suffix remove: {crate2}")
            return 1
        used2 = int(node.metrics().get("libp2p_advertised_externals_used", 0))
        if used2 != 0:
            print(f"FAIL: used {used2} after suffix remove of sole listen")
            return 1
        print("OK: suffix remove dropped canonical crate slot")
    finally:
        try:
            node.close()
        except Exception:
            pass

    print("OK: libp2p_rust_behaviour_external_expired_canonical_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; add/remove/expire charge canonical key; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
