#!/usr/bin/env python3
"""ADR 0019 Slice T — persistent learned peerstore lab.

Connect with peerstore_path, learn hub addr via dial/identify, reopen node
from disk and peerstore_dial back to hub.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_peerstore_lab.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait(pred, timeout: float = 10.0, step: float = 0.05) -> bool:
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

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-peerstore-") as td:
        store_path = str(Path(td) / "peerstore.json")
        hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
        client = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            peerstore_path=store_path,
        )
        try:
            hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
            client.listen("/ip4/127.0.0.1/tcp/0")
            remote = client.dial(hub_addr)
            if remote != hub.peer_id:
                print(f"FAIL: dial remote {remote} != {hub.peer_id}")
                return 1

            if not _wait(
                lambda: hub.peer_id in dict(client.peerstore_list()),
                timeout=8.0,
            ):
                print(
                    f"FAIL: peerstore not learned "
                    f"list={dict(client.peerstore_list())} "
                    f"metrics={client.metrics()}"
                )
                return 1
            disk = json.loads(Path(store_path).read_text(encoding="utf-8"))
            if hub.peer_id not in (disk.get("peers") or {}):
                print(f"FAIL: disk peerstore missing hub: {disk}")
                return 1
            print("OK: peerstore learned + persisted")
            learned = int(client.metrics().get("libp2p_peerstore_learned", 0))
            if learned < 1:
                print(f"FAIL: learned counter {learned}")
                return 1
        finally:
            try:
                client.close()
            except Exception:
                pass

        # Warm dial from disk after restart.
        client2 = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            peerstore_path=store_path,
        )
        try:
            client2.listen("/ip4/127.0.0.1/tcp/0")
            listed = dict(client2.peerstore_list())
            if hub.peer_id not in listed:
                print(f"FAIL: reload peerstore missing hub: {listed}")
                return 1
            results = list(client2.peerstore_dial())
            if not any(
                p == hub.peer_id and s in ("ok", "already_connected") for p, s in results
            ):
                print(f"FAIL: peerstore_dial: {results}")
                return 1
            if not _wait(lambda: hub.peer_id in client2.connected_peers(), timeout=5.0):
                print("FAIL: not connected after peerstore_dial")
                return 1
            m = client2.metrics()
            cap = client2.capability_status()
            if int(m.get("libp2p_peerstore_dials_ok", 0)) < 1 and not any(
                s == "already_connected" for _, s in results
            ):
                # ok counter increments for ok settle; already_connected also bumps ok
                print(f"FAIL: peerstore dial metrics: {m} results={results}")
                return 1
            if not cap.get("peerstore"):
                print(f"FAIL: capability peerstore: {cap}")
                return 1
            if int(cap.get("phase", 0)) < 19:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            print(
                f"OK: peerstore_dial restored "
                f"ok={m.get('libp2p_peerstore_dials_ok')} results={results}"
            )
        finally:
            for n in (client2, hub):
                try:
                    n.close()
                except Exception:
                    pass

    print("OK: libp2p_rust_peerstore_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; learned peerstore opt-in; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
