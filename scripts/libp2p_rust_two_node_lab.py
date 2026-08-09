#!/usr/bin/env python3
"""Real rust-libp2p 2-node lab (ADR 0019 Slice A).

Requires abs_native built with Cargo feature ``libp2p``:
  cd native/abs_native
  maturin develop --release --features \"pyo3/extension-module,libp2p\"

Usage:
  python scripts/libp2p_rust_two_node_lab.py
"""

from __future__ import annotations

import sys
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
        print("  rebuild: maturin develop --features pyo3/extension-module,libp2p")
        return 1

    a = abs_native.libp2p_node_new()
    b = abs_native.libp2p_node_new()
    try:
        addrs_a = a.listen("/ip4/127.0.0.1/tcp/0")
        addrs_b = b.listen("/ip4/127.0.0.1/tcp/0")
        if not addrs_a or not addrs_b:
            print("FAIL: missing listen addrs")
            return 1
        listen_a = addrs_a[0]
        remote = b.dial(listen_a)
        if not remote:
            print("FAIL: dial returned empty peer id")
            return 1
        # Allow inbound side to observe connection
        import time

        for _ in range(50):
            if a.connected_peers():
                break
            time.sleep(0.05)
        connected_a = list(a.connected_peers())
        connected_b = list(b.connected_peers())
        if not connected_a and not connected_b:
            print("FAIL: no connected peers after dial")
            return 1

        print("OK: libp2p_rust_two_node_lab PASS")
        print(f"  peer_a: {a.peer_id}")
        print(f"  peer_b: {b.peer_id}")
        print(f"  listen_a: {listen_a}")
        print(f"  dial_remote: {remote}")
        print(f"  connected_a: {connected_a}")
        print(f"  connected_b: {connected_b}")
        print("  honesty: FEATURE_LIBP2P lab; not prod TCP+TLS mesh")
        return 0
    finally:
        try:
            a.close()
        except Exception:
            pass
        try:
            b.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
