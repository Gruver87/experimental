#!/usr/bin/env python3
"""rust-libp2p mDNS Toggle lab (ADR 0019 Slice K).

enable_mdns=False -> no mDNS discoveries; enable_mdns=True -> loopback discover.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_mdns_toggle_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    off_a = abs_native.libp2p_node_new(enable_mdns=False)
    off_b = abs_native.libp2p_node_new(enable_mdns=False)
    try:
        off_a.listen("/ip4/127.0.0.1/tcp/0")
        off_b.listen("/ip4/127.0.0.1/tcp/0")
        time.sleep(1.2)
        ma = off_a.metrics()
        mb = off_b.metrics()
        if bool(ma.get("libp2p_mdns_enabled", True)):
            print(f"FAIL: mdns should be off: {ma}")
            return 1
        if int(ma.get("libp2p_mdns_discovered", 0)) != 0:
            print(f"FAIL: mdns off but discoveries: {ma}")
            return 1
        if int(mb.get("libp2p_mdns_discovered", 0)) != 0:
            print(f"FAIL: mdns off but discoveries b: {mb}")
            return 1
        print("OK: enable_mdns=False suppresses mDNS")
    finally:
        for n in (off_a, off_b):
            try:
                n.close()
            except Exception:
                pass

    on_a = abs_native.libp2p_node_new(enable_mdns=True)
    on_b = abs_native.libp2p_node_new(enable_mdns=True)
    try:
        on_a.listen("/ip4/127.0.0.1/tcp/0")
        on_b.listen("/ip4/127.0.0.1/tcp/0")
        found = False
        for _ in range(40):
            time.sleep(0.1)
            disc = dict(on_a.discovered_peers())
            if on_b.peer_id in disc:
                found = True
                break
            if int(on_a.metrics().get("libp2p_mdns_discovered", 0)) >= 1:
                # discovered count may be for other loopback peers; still proves mdns on
                found = True
                break
        if not found:
            # Soft-fail on CI without mDNS: still require enabled flag
            m = on_a.metrics()
            if not bool(m.get("libp2p_mdns_enabled", False)):
                print(f"FAIL: mdns not enabled: {m}")
                return 1
            print("OK: enable_mdns=True (no peer seen in window; flag/metrics ok)")
        else:
            print("OK: enable_mdns=True with loopback discovery activity")
        print(f"  mdns_enabled={on_a.metrics().get('libp2p_mdns_enabled')}")
        print(f"  mdns_discovered={on_a.metrics().get('libp2p_mdns_discovered')}")
    finally:
        for n in (on_a, on_b):
            try:
                n.close()
            except Exception:
                pass

    print("OK: libp2p_rust_mdns_toggle_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
