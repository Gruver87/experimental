#!/usr/bin/env python3
"""ADR 0019 Slice CQ — JSON persist tmp/dest born restricted.

CL restricted identity tmp at create. JSON persist (externals / bootstrap /
peerstore) still used ``File::create``, so the staging file inherited
Users/Everyone on a shared directory. Slice CQ uses the same restricted
create (Unix 0600 / Windows protected DACL). Existing JSON is not refused
at load (not key material). Dest ACL is replaced on persist. Capability
``persist_json_acl_restrict`` / phase >= 94.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_persist_json_acl_lab.py
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _file_sddl(path: Path) -> str:
    env = os.environ.copy()
    env["ABS_ACL_PATH"] = str(path)
    proc = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-Acl -LiteralPath $env:ABS_ACL_PATH | Select-Object -ExpandProperty Sddl",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        return ""
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


def _sddl_grants_users(sddl: str) -> bool:
    low = sddl.lower()
    return any(
        token in low
        for token in (
            ";bu)",
            ";wd)",
            ";au)",
            "s-1-5-32-545",
            "s-1-1-0",
            "s-1-5-11",
        )
    )


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    want = (
        "windows_createfile_owner_dacl" if os.name == "nt" else "unix_0600_at_create"
    )
    mod_strategy = str(getattr(abs_native, "PERSIST_JSON_ACL_STRATEGY", ""))
    if mod_strategy != want:
        print(f"FAIL: module strategy {mod_strategy!r} != {want}")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-jsonacl-") as td:
        store = Path(td) / "external_addrs.json"
        tmp = Path(str(store) + f".{os.getpid()}.tmp")
        tmp.write_bytes(b"stale-json")
        node = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            external_addrs_path=str(store),
        )
        try:
            cap = node.capability_status()
            if not cap.get("persist_json_acl_restrict"):
                print(f"FAIL: capability persist_json_acl_restrict: {cap}")
                return 1
            if cap.get("persist_json_acl_strategy") != want:
                print(
                    "FAIL: capability strategy "
                    f"{cap.get('persist_json_acl_strategy')!r} != {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 94:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            added = node.add_external_address("/ip4/203.0.113.94/tcp/4094")
            if not added:
                print("FAIL: add_external_address returned False")
                return 1
        finally:
            node.close()

        if not store.is_file():
            print("FAIL: dest missing after JSON persist")
            return 1
        if tmp.exists():
            print("FAIL: tmp leftover after JSON persist")
            return 1
        if os.name == "nt":
            sddl = _file_sddl(store)
            if not sddl:
                print("FAIL: could not read dest SDDL")
                return 1
            if _sddl_grants_users(sddl):
                print("FAIL: JSON dest DACL grants Users/Everyone")
                return 1
            if "d:p" not in sddl.lower():
                print("FAIL: JSON dest DACL is not protected")
                return 1
        else:
            mode = store.stat().st_mode
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                print(f"FAIL: JSON dest mode {mode & 0o777:o} allows group/other")
                return 1
        print("OK: persist JSON ACL restricted")

    print("OK: libp2p_rust_persist_json_acl_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; JSON persist tmp/dest born restricted; "
        "existing JSON not refused at load; not POSIX inode-atomic on NTFS; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
