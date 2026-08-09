#!/usr/bin/env python3
"""ADR 0019 Slice AJ — listener lifecycle metrics lab.

Listen → ``libp2p_new_listen_addr``; ``remove_listener`` → expired/closed.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_listener_lifecycle_lab.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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

    node = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
    try:
        addrs = node.listen("/ip4/127.0.0.1/tcp/0")
        if not addrs:
            print("FAIL: empty listen")
            return 1
        listen = addrs[0]
        print(f"OK: listen {listen}")

        if not _wait(
            lambda: int(node.metrics().get("libp2p_new_listen_addr", 0)) >= 1
            and listen in node.listen_addrs(),
            timeout=3.0,
        ):
            print(f"FAIL: new_listen_addr metrics={node.metrics()}")
            return 1
        print(
            f"OK: new_listen_addr={node.metrics().get('libp2p_new_listen_addr')} "
            f"book={node.listen_addrs()}"
        )

        closed_before = int(node.metrics().get("libp2p_listener_closed", 0))
        expired_before = int(node.metrics().get("libp2p_expired_listen_addr", 0))
        removed = node.remove_listener(listen)
        if not removed:
            print(f"FAIL: remove_listener returned False for {listen}")
            return 1

        if not _wait(
            lambda: (
                int(node.metrics().get("libp2p_listener_closed", 0)) > closed_before
                or int(node.metrics().get("libp2p_expired_listen_addr", 0))
                > expired_before
            )
            and listen not in node.listen_addrs(),
            timeout=4.0,
        ):
            print(
                f"FAIL: remove not reflected metrics={node.metrics()} "
                f"listen_addrs={node.listen_addrs()}"
            )
            return 1
        m = node.metrics()
        print(
            f"OK: removed closed={m.get('libp2p_listener_closed')} "
            f"expired={m.get('libp2p_expired_listen_addr')} "
            f"book={node.listen_addrs()}"
        )

        try:
            node.remove_listener(listen)
            print("FAIL: second remove_listener should error")
            return 1
        except Exception as exc:
            if "no listener" not in str(exc):
                print(f"FAIL: unexpected remove error: {exc}")
                return 1
            print("OK: second remove_listener refused")

        cap = node.capability_status()
        if not cap.get("listener_lifecycle"):
            print(f"FAIL: capability listener_lifecycle: {cap}")
            return 1
        if int(cap.get("phase", 0)) < 35:
            print(f"FAIL: phase {cap.get('phase')}")
            return 1
    finally:
        try:
            node.close()
        except Exception:
            pass

    print("OK: libp2p_rust_listener_lifecycle_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; listener lifecycle; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
