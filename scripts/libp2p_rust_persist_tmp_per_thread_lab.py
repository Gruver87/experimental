#!/usr/bin/env python3
"""ADR 0019 Slice CU — persist staging tmp is per-thread.

CK used ``dest.{pid}.tmp`` so two processes do not share staging. Two
threads in one process still collided and could tear a snapshot. Slice CU
uses ``dest.{pid}.{tid}.tmp``. Same-thread sequential persist reuses the
name (leftover cleanup). JSON persist remains last-writer-wins replace
(CD) of a complete snapshot. Capability ``persist_tmp_per_thread`` /
phase >= 98.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_persist_tmp_per_thread_lab.py
"""

from __future__ import annotations

import sys
import tempfile
import threading
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

    want = "pid_tid_tmp"
    mod_strategy = str(getattr(abs_native, "PERSIST_TMP_STRATEGY", ""))
    if mod_strategy != want:
        print(f"FAIL: module strategy {mod_strategy!r} != {want}")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-tmp-tid-") as td:
        key_path = Path(td) / "keystore" / "node.key"
        a = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
        )
        try:
            cap = a.capability_status()
            if not cap.get("persist_tmp_per_thread"):
                print(f"FAIL: capability persist_tmp_per_thread: {cap}")
                return 1
            if cap.get("persist_tmp_strategy") != want:
                print(
                    "FAIL: capability strategy "
                    f"{cap.get('persist_tmp_strategy')!r} != {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 98:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
        finally:
            a.close()

        race_key = Path(td) / "race" / "node.key"
        barrier = threading.Barrier(2)
        results: list[tuple[str, str]] = []
        lock = threading.Lock()

        def spawn() -> None:
            barrier.wait()
            try:
                n = abs_native.libp2p_node_new(
                    enable_mdns=False,
                    enable_reconnect=False,
                    key_path=str(race_key),
                )
                pid = n.peer_id
                n.close()
                with lock:
                    results.append(("ok", pid))
            except Exception as exc:
                with lock:
                    results.append(("err", str(exc)))

        t1 = threading.Thread(target=spawn)
        t2 = threading.Thread(target=spawn)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        if not race_key.is_file():
            print(f"FAIL: race dest missing results={results}")
            return 1
        loaded = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(race_key),
        )
        try:
            final_pid = loaded.peer_id
        finally:
            loaded.close()
        oks = [pid for status, pid in results if status == "ok"]
        if any(pid != final_pid for pid in oks):
            print(f"FAIL: torn identity PeerId oks={oks} loaded={final_pid}")
            return 1
        print(
            f"OK: persist tmp per-thread strategy={want} "
            f"race_ok={len(oks)} peer_id={final_pid}"
        )

    print("OK: libp2p_rust_persist_tmp_per_thread_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; staging tmp is per-thread; "
        "JSON persist still last-writer-wins complete snapshot; "
        "not POSIX inode-atomic on NTFS; TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
