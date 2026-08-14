#!/usr/bin/env python3
"""ADR 0019 Slice CM — existing identity weak ACL refuses spawn.

Unix CH refuses group/other bits (no silent chmod). Windows CI/CL only
protect first-create; ``identity_key_mode_ok`` was a no-op on Windows so an
existing key with Users/Everyone still spawned. Slice CM refuses spawn when
the DACL grants anyone other than owner/SYSTEM/Administrators. Dest ACL is
never rewritten. Capability ``identity_key_existing_acl_refuse`` / phase >= 90.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identity_existing_acl_refuse_lab.py
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

    want = "unix_0600" if os.name == "posix" else "windows_owner_only_dacl"
    mod_strategy = str(getattr(abs_native, "IDENTITY_KEY_EXISTING_ACL_STRATEGY", ""))
    if mod_strategy != want:
        print(f"FAIL: module strategy {mod_strategy!r} != {want}")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-id-aclref-") as td:
        key_path = Path(td) / "node.key"
        a = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
        )
        try:
            cap = a.capability_status()
            if not cap.get("identity_key_existing_acl_refuse"):
                print(f"FAIL: capability identity_key_existing_acl_refuse: {cap}")
                return 1
            if cap.get("identity_key_existing_acl_strategy") != want:
                print(
                    "FAIL: capability strategy "
                    f"{cap.get('identity_key_existing_acl_strategy')!r} != {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 90:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            pid = a.peer_id
        finally:
            a.close()

        if os.name == "posix":
            key_path.chmod(0o644)
            try:
                abs_native.libp2p_node_new(
                    enable_mdns=False,
                    enable_reconnect=False,
                    key_path=str(key_path),
                )
                print("FAIL: world-readable key was accepted")
                return 1
            except Exception as exc:
                msg = str(exc).lower()
                if "mode" not in msg and "group/other" not in msg:
                    print(f"FAIL: world-readable error too vague: {exc}")
                    return 1
            if stat.S_IMODE(key_path.stat().st_mode) != 0o644:
                print("FAIL: mode was silently rewritten")
                return 1
            key_path.chmod(0o600)
        else:
            grant = subprocess.run(
                ["icacls", str(key_path), "/grant", "*S-1-5-32-545:R"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if grant.returncode != 0:
                print("FAIL: icacls grant Users failed")
                return 1
            if not _sddl_grants_users(_file_sddl(key_path)):
                print("FAIL: Users ACE did not land on dest")
                return 1
            try:
                abs_native.libp2p_node_new(
                    enable_mdns=False,
                    enable_reconnect=False,
                    key_path=str(key_path),
                )
                print("FAIL: Users-readable key was accepted")
                return 1
            except Exception as exc:
                msg = str(exc).lower()
                if "dacl" not in msg and "admin" not in msg and "acl" not in msg:
                    print(f"FAIL: Users-readable error too vague: {exc}")
                    return 1
            if not _sddl_grants_users(_file_sddl(key_path)):
                print("FAIL: dest ACL was silently rewritten")
                return 1
            subprocess.run(
                ["icacls", str(key_path), "/remove", "*S-1-5-32-545"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

        b = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
        )
        try:
            if b.peer_id != pid:
                print(f"FAIL: PeerId changed after ACL restore {pid} -> {b.peer_id}")
                return 1
        finally:
            b.close()
        print(f"OK: identity existing ACL refuse strategy={want} peer_id={pid}")

    print("OK: libp2p_rust_identity_existing_acl_refuse_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; existing weak ACL refuses spawn; "
        "no silent chmod/DACL rewrite; not POSIX 0600 on Windows; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
