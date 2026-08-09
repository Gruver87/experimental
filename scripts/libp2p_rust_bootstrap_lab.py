#!/usr/bin/env python3
"""ADR 0019 Slice O — industrial persistent bootstrap dial lab.

- Persist JSON bootstrap book
- Reload + sequential bootstrap_dial that settles each entry before return
- Partial-fail: dead peer fails, live hub still reconnects
- Budget / already_connected paths covered via metrics

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
        dead = abs_native.libp2p_node_new(enable_mdns=False)
        dead_pid = dead.peer_id
        writer = abs_native.libp2p_node_new(
            enable_mdns=False,
            bootstrap_path=boot_path,
        )
        try:
            hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
            hub_ma = f"{hub_addr}/p2p/{hub.peer_id}"
            # Closed port → fast outbound failure (not hang).
            dead_ma = f"/ip4/127.0.0.1/tcp/1/p2p/{dead_pid}"
            writer.listen("/ip4/127.0.0.1/tcp/0")
            writer.bootstrap_add(hub.peer_id, hub_ma)
            writer.bootstrap_add(dead_pid, dead_ma)
            listed = dict(writer.bootstrap_list())
            if hub.peer_id not in listed or dead_pid not in listed:
                print(f"FAIL: bootstrap_list incomplete: {listed}")
                return 1
            disk = json.loads(Path(boot_path).read_text(encoding="utf-8"))
            if hub.peer_id not in (disk.get("peers") or {}):
                print(f"FAIL: disk JSON missing hub: {disk}")
                return 1
            print("OK: bootstrap_add persisted hub+dead entries")
        finally:
            try:
                writer.close()
            except Exception:
                pass
            try:
                dead.close()
            except Exception:
                pass

        client = abs_native.libp2p_node_new(
            enable_mdns=False,
            bootstrap_path=boot_path,
        )
        try:
            client.listen("/ip4/127.0.0.1/tcp/0")
            t0 = time.time()
            results = list(client.bootstrap_dial())
            elapsed = time.time() - t0
            by_peer = {str(p): str(s) for p, s in results}
            if hub.peer_id not in by_peer:
                print(f"FAIL: missing hub settle result: {results}")
                return 1
            if by_peer[hub.peer_id] not in ("ok", "already_connected"):
                print(f"FAIL: hub status not settled ok: {by_peer[hub.peer_id]!r}")
                return 1
            if dead_pid not in by_peer:
                print(f"FAIL: missing dead settle result: {results}")
                return 1
            dead_status = by_peer[dead_pid]
            if dead_status in ("ok", "already_connected", "dialing"):
                print(f"FAIL: dead peer should fail, got {dead_status!r}")
                return 1
            if "dialing" in by_peer.values():
                print(f"FAIL: settle returned dialing (fire-and-forget leak): {results}")
                return 1
            if hub.peer_id not in client.connected_peers():
                print(f"FAIL: hub not connected after settle: {client.metrics()}")
                return 1
            m = client.metrics()
            if int(m.get("libp2p_bootstrap_dials_attempted", 0)) < 2:
                print(f"FAIL: attempted metric: {m}")
                return 1
            if int(m.get("libp2p_bootstrap_dials_ok", 0)) < 1:
                print(f"FAIL: ok metric: {m}")
                return 1
            if int(m.get("libp2p_bootstrap_dials_fail", 0)) < 1:
                print(f"FAIL: fail metric: {m}")
                return 1
            # already_connected path
            again = list(client.bootstrap_dial())
            again_map = {str(p): str(s) for p, s in again}
            if again_map.get(hub.peer_id) != "already_connected":
                print(f"FAIL: expected already_connected, got {again_map}")
                return 1
            cap = client.capability_status()
            if not cap.get("bootstrap") or int(cap.get("phase", 0)) < 14:
                print(f"FAIL: capability: {cap}")
                return 1
            print("OK: sequential settle (hub ok + dead fail + already_connected)")
            print(
                f"  elapsed={elapsed:.2f}s attempted={m.get('libp2p_bootstrap_dials_attempted')} "
                f"ok={m.get('libp2p_bootstrap_dials_ok')} fail={m.get('libp2p_bootstrap_dials_fail')}"
            )
            print(f"  results={results}")

            from network.transport.libp2p_adapter import Libp2pTransportAdapter

            ad = Libp2pTransportAdapter(
                enabled=True,
                enable_mdns=False,
                bootstrap_path=boot_path,
            )
            try:
                ad.listen("/ip4/127.0.0.1/tcp/0")
                settled = ad.bootstrap_dial()
                if not any(p == hub.peer_id and s in ("ok", "already_connected") for p, s in settled):
                    print(f"FAIL: adapter settle: {settled}")
                    return 1
                if not _wait(lambda: hub.peer_id in ad._ensure_node().connected_peers()):
                    print("FAIL: adapter not connected to hub")
                    return 1
                print("OK: adapter bootstrap_dial settle")
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
    print("  honesty: FEATURE_LIBP2P lab; industrial bootstrap dial; not prod mesh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
