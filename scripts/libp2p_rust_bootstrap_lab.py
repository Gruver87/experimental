#!/usr/bin/env python3
"""ADR 0019 Slice O — persistent bootstrap peer list lab.

Writes a JSON bootstrap book, reloads a fresh node from the same path,
fires bootstrap_dial, and verifies reconnect + metrics.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_bootstrap_lab.py
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

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-boot-") as td:
        boot_path = str(Path(td) / "bootstrap.json")
        hub = abs_native.libp2p_node_new(enable_mdns=False)
        writer = abs_native.libp2p_node_new(
            enable_mdns=False,
            bootstrap_path=boot_path,
        )
        try:
            hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
            hub_ma = f"{hub_addr}/p2p/{hub.peer_id}"
            writer.listen("/ip4/127.0.0.1/tcp/0")
            writer.bootstrap_add(hub.peer_id, hub_ma)
            listed = dict(writer.bootstrap_list())
            if hub.peer_id not in listed:
                print(f"FAIL: bootstrap_list missing hub: {listed}")
                return 1
            if not Path(boot_path).is_file():
                print("FAIL: bootstrap file not written")
                return 1
            disk = json.loads(Path(boot_path).read_text(encoding="utf-8"))
            if hub.peer_id not in (disk.get("peers") or {}):
                print(f"FAIL: disk JSON missing hub: {disk}")
                return 1
            print("OK: bootstrap_add persisted to JSON")
        finally:
            try:
                writer.close()
            except Exception:
                pass

        # Fresh node loads the same book and dials.
        client = abs_native.libp2p_node_new(
            enable_mdns=False,
            bootstrap_path=boot_path,
        )
        try:
            client.listen("/ip4/127.0.0.1/tcp/0")
            loaded = dict(client.bootstrap_list())
            if hub.peer_id not in loaded:
                print(f"FAIL: reload missing hub: {loaded}")
                return 1
            attempts = list(client.bootstrap_dial())
            if not attempts:
                print("FAIL: bootstrap_dial returned empty")
                return 1
            if not any(status == "dialing" for _pid, status in attempts):
                print(f"FAIL: no dialing attempt: {attempts}")
                return 1
            if not _wait(lambda: hub.peer_id in client.connected_peers()):
                print(
                    f"FAIL: reconnect failed client={client.metrics()} "
                    f"hub={hub.metrics()} attempts={attempts}"
                )
                return 1
            m = client.metrics()
            if int(m.get("libp2p_bootstrap_peers", 0)) < 1:
                print(f"FAIL: bootstrap_peers metric: {m}")
                return 1
            if int(m.get("libp2p_bootstrap_dials_ok", 0)) < 1:
                print(f"FAIL: bootstrap_dials_ok metric: {m}")
                return 1
            cap = client.capability_status()
            if not cap.get("bootstrap") or not cap.get("persistent_bootstrap"):
                print(f"FAIL: capability bootstrap flags: {cap}")
                return 1
            if int(cap.get("phase", 0)) < 14:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            print("OK: bootstrap reload + dial reconnect")
            print(
                f"  peers={m.get('libp2p_bootstrap_peers')} "
                f"dials_ok={m.get('libp2p_bootstrap_dials_ok')} "
                f"path={cap.get('bootstrap_path')}"
            )

            # Adapter parity
            from network.transport.libp2p_adapter import Libp2pTransportAdapter

            ad = Libp2pTransportAdapter(
                enabled=True,
                enable_mdns=False,
                bootstrap_path=boot_path,
            )
            try:
                ad.listen("/ip4/127.0.0.1/tcp/0")
                bl = dict(ad.bootstrap_list())
                if hub.peer_id not in bl:
                    print(f"FAIL: adapter bootstrap_list: {bl}")
                    return 1
                ad.bootstrap_dial()
                if not _wait(lambda: hub.peer_id in (ad._ensure_node().connected_peers())):
                    print("FAIL: adapter bootstrap_dial reconnect")
                    return 1
                print("OK: adapter bootstrap path")
            finally:
                try:
                    ad.close()
                except Exception:
                    pass
        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                hub.close()
            except Exception:
                pass

    print("OK: libp2p_rust_bootstrap_lab PASS")
    print("  honesty: FEATURE_LIBP2P lab; bootstrap book opt-in; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
