#!/usr/bin/env python3
"""ADR 0019 Slice CE — bootstrap + peerstore persist via atomic replace.

``save_bootstrap_peers`` (bootstrap book and learned peerstore) used
``std::fs::write`` (truncate dest in place). A crash mid-write left corrupt
JSON. Slice CE routes both books through tmp+fsync+replace (same CD
MoveFileEx / POSIX rename). Learned addrs that fail persist are rolled back
in memory (no silent disk/memory split). Capability
``bootstrap_peerstore_atomic_persist`` / phase >= 82.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_bootstrap_peerstore_atomic_persist_lab.py
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


def _assert_valid_book(path: Path, tmp: Path, label: str) -> dict:
    if not path.is_file():
        raise RuntimeError(f"FAIL: {label} dest missing")
    if tmp.exists():
        raise RuntimeError(f"FAIL: {label} tmp leftover: {tmp}")
    disk = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(disk.get("peers"), dict):
        raise RuntimeError(f"FAIL: {label} dest not a peer book: {disk}")
    return disk


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-books-atomic-") as td:
        boot = Path(td) / "bootstrap.json"
        store = Path(td) / "peerstore.json"
        boot_tmp = Path(str(boot) + ".tmp")
        store_tmp = Path(str(store) + ".tmp")
        hub = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
        writer = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            bootstrap_path=str(boot),
            peerstore_path=str(store),
        )
        try:
            cap = writer.capability_status()
            if not cap.get("bootstrap_peerstore_atomic_persist"):
                print(f"FAIL: capability bootstrap_peerstore_atomic_persist: {cap}")
                return 1
            if int(cap.get("phase", 0)) < 82:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1

            hub_addr = hub.listen("/ip4/127.0.0.1/tcp/0")[0]
            hub_ma = f"{hub_addr}/p2p/{hub.peer_id}"
            writer.listen("/ip4/127.0.0.1/tcp/0")
            writer.bootstrap_add(hub.peer_id, hub_ma)
            disk1 = _assert_valid_book(boot, boot_tmp, "bootstrap first")
            if hub.peer_id not in (disk1.get("peers") or {}):
                print(f"FAIL: bootstrap missing hub after first add: {disk1}")
                return 1

            extra = abs_native.libp2p_node_new(enable_mdns=False, enable_reconnect=False)
            extra_pid = extra.peer_id
            try:
                extra_ma = f"/ip4/127.0.0.1/tcp/9/p2p/{extra_pid}"
                writer.bootstrap_add(extra_pid, extra_ma)
            finally:
                extra.close()
            disk2 = _assert_valid_book(boot, boot_tmp, "bootstrap replace")
            peers = disk2.get("peers") or {}
            if hub.peer_id not in peers or extra_pid not in peers:
                print(f"FAIL: bootstrap after replace: {disk2}")
                return 1

            writer.dial(hub_addr)
            if not _wait(
                lambda: int(writer.metrics().get("libp2p_peerstore_learned", 0)) >= 1,
                timeout=6.0,
            ):
                print(f"FAIL: peerstore did not learn: {writer.metrics()}")
                return 1
            if not _wait(lambda: store.is_file(), timeout=4.0):
                print("FAIL: peerstore dest never appeared")
                return 1
            pdisk = _assert_valid_book(store, store_tmp, "peerstore")
            if not (pdisk.get("peers") or {}):
                print(f"FAIL: peerstore empty after learn: {pdisk}")
                return 1
            listed = dict(writer.peerstore_list())
            on_disk = set((pdisk.get("peers") or {}).keys())
            in_mem = set(listed.keys())
            if on_disk != in_mem:
                print(f"FAIL: peerstore memory/disk split mem={in_mem} disk={on_disk}")
                return 1
            print(
                f"OK: books atomic persist bootstrap_peers={len(peers)} "
                f"peerstore_peers={len(on_disk)}"
            )
        finally:
            try:
                writer.close()
            except Exception:
                pass
            try:
                hub.close()
            except Exception:
                pass

    print("OK: libp2p_rust_bootstrap_peerstore_atomic_persist_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; bootstrap+peerstore atomic replace; "
        "not POSIX inode-atomic on NTFS; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
