#!/usr/bin/env python3
"""ADR 0019 Slice CR — world-writable identity parent dir refuses spawn.

CI–CP lock the key file DACL/mode. If Users/Everyone can write the parent
directory they can replace/unlink ``node.key``. Slice CR refuses spawn.
Directory ACL is never rewritten. Volume roots are skipped. Capability
``identity_key_parent_dir_refuse`` / phase >= 95.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identity_parent_dir_refuse_lab.py
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


def _dir_sddl(path: Path) -> str:
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
        "windows_dir_no_users_write"
        if os.name == "nt"
        else "unix_dir_no_group_other_write"
    )
    mod_strategy = str(getattr(abs_native, "IDENTITY_KEY_PARENT_DIR_STRATEGY", ""))
    if mod_strategy != want:
        print(f"FAIL: module strategy {mod_strategy!r} != {want}")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-id-parent-") as td:
        parent = Path(td) / "keystore"
        parent.mkdir()
        key_path = parent / "node.key"
        a = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(key_path),
        )
        try:
            cap = a.capability_status()
            if not cap.get("identity_key_parent_dir_refuse"):
                print(f"FAIL: capability identity_key_parent_dir_refuse: {cap}")
                return 1
            if cap.get("identity_key_parent_dir_strategy") != want:
                print(
                    "FAIL: capability strategy "
                    f"{cap.get('identity_key_parent_dir_strategy')!r} != {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 95:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            pid = a.peer_id
            first = key_path.read_bytes()
        finally:
            a.close()

        if os.name == "posix":
            os.chmod(parent, 0o0777)
            try:
                abs_native.libp2p_node_new(
                    enable_mdns=False,
                    enable_reconnect=False,
                    key_path=str(key_path),
                )
                print("FAIL: world-writable parent was accepted")
                return 1
            except Exception as exc:
                msg = str(exc).lower()
                if "parent" not in msg and "mode" not in msg and "group/other" not in msg:
                    print(f"FAIL: world-writable parent error too vague: {exc}")
                    return 1
            if stat.S_IMODE(parent.stat().st_mode) != 0o0777:
                print("FAIL: parent mode was silently rewritten")
                return 1
            if key_path.read_bytes() != first:
                print("FAIL: dest bytes changed after parent-mode refuse")
                return 1
            os.chmod(parent, 0o1777)
            sticky = abs_native.libp2p_node_new(
                enable_mdns=False,
                enable_reconnect=False,
                key_path=str(key_path),
            )
            try:
                if sticky.peer_id != pid:
                    print(f"FAIL: PeerId changed on sticky parent {pid} -> {sticky.peer_id}")
                    return 1
            finally:
                sticky.close()
            os.chmod(parent, 0o0700)
        else:
            grant = subprocess.run(
                ["icacls", str(parent), "/grant", "*S-1-5-32-545:(W)"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if grant.returncode != 0:
                print("FAIL: icacls grant Users write on parent failed")
                return 1
            sddl_weak = _dir_sddl(parent)
            if not _sddl_grants_users(sddl_weak):
                print("FAIL: Users ACE did not land on parent")
                return 1
            try:
                abs_native.libp2p_node_new(
                    enable_mdns=False,
                    enable_reconnect=False,
                    key_path=str(key_path),
                )
                print("FAIL: Users-writable parent was accepted")
                return 1
            except Exception as exc:
                msg = str(exc).lower()
                if not any(
                    token in msg for token in ("parent", "write", "dacl", "dir")
                ):
                    print(f"FAIL: Users-writable parent error too vague: {exc}")
                    return 1
            if key_path.read_bytes() != first:
                print("FAIL: dest bytes changed after parent-ACL refuse")
                return 1
            if _dir_sddl(parent) != sddl_weak:
                print("FAIL: parent ACL was silently rewritten")
                return 1
            subprocess.run(
                ["icacls", str(parent), "/remove", "*S-1-5-32-545"],
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
                print(f"FAIL: PeerId changed after parent restore {pid} -> {b.peer_id}")
                return 1
        finally:
            b.close()
        print(f"OK: identity parent dir refuse strategy={want} peer_id={pid}")

    print("OK: libp2p_rust_identity_parent_dir_refuse_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; world-writable parent refuses spawn; "
        "no silent directory ACL rewrite; volume roots skipped; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
