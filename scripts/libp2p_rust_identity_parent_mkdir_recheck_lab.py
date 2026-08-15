#!/usr/bin/env python3
"""ADR 0019 Slice CS — identity parent mkdir then ACL recheck.

CR walked a missing parent to the first existing ancestor and skipped
inherit-only ACEs. ``create_dir_all`` then inherited Users/group-other write
onto the new directory, so the key landed in a world-writable parent.
Slice CS mkdir's first and rechecks the created parent. Directory ACL is
never rewritten. Capability ``identity_key_parent_mkdir_recheck`` / phase >= 96.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identity_parent_mkdir_recheck_lab.py
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

    want = "mkdir_then_recheck_parent_acl"
    mod_strategy = str(
        getattr(abs_native, "IDENTITY_KEY_PARENT_MKDIR_RECHECK_STRATEGY", "")
    )
    if mod_strategy != want:
        print(f"FAIL: module strategy {mod_strategy!r} != {want}")
        return 1

    with tempfile.TemporaryDirectory(prefix="abs-libp2p-id-mkdir-") as td:
        clean_parent = Path(td) / "clean" / "keystore"
        clean_key = clean_parent / "node.key"
        a = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(clean_key),
        )
        try:
            cap = a.capability_status()
            if not cap.get("identity_key_parent_mkdir_recheck"):
                print(f"FAIL: capability identity_key_parent_mkdir_recheck: {cap}")
                return 1
            if cap.get("identity_key_parent_mkdir_recheck_strategy") != want:
                print(
                    "FAIL: capability strategy "
                    f"{cap.get('identity_key_parent_mkdir_recheck_strategy')!r} != {want}"
                )
                return 1
            if int(cap.get("phase", 0)) < 96:
                print(f"FAIL: phase {cap.get('phase')}")
                return 1
            pid = a.peer_id
        finally:
            a.close()
        if not clean_key.is_file():
            print("FAIL: clean nested mkdir spawn did not create key")
            return 1

        if os.name == "posix":
            old_mask = os.umask(0)
            try:
                weak_parent = Path(td) / "umask0" / "keystore"
                weak_key = weak_parent / "node.key"
                try:
                    abs_native.libp2p_node_new(
                        enable_mdns=False,
                        enable_reconnect=False,
                        key_path=str(weak_key),
                    )
                    print("FAIL: umask-0 created parent was accepted")
                    return 1
                except Exception as exc:
                    msg = str(exc).lower()
                    if "parent" not in msg and "mode" not in msg and "group/other" not in msg:
                        print(f"FAIL: umask-0 parent error too vague: {exc}")
                        return 1
                if weak_key.exists():
                    print("FAIL: key written before parent recheck")
                    return 1
                if not weak_parent.is_dir():
                    print("FAIL: missing parent was not created before recheck")
                    return 1
                mode = stat.S_IMODE(weak_parent.stat().st_mode)
                if mode & 0o022 == 0:
                    print(f"FAIL: umask-0 parent was not world-writable: {mode:o}")
                    return 1
            finally:
                os.umask(old_mask)
        else:
            anc = Path(td) / "inherit"
            anc.mkdir()
            grant = subprocess.run(
                [
                    "icacls",
                    str(anc),
                    "/grant",
                    "*S-1-5-32-545:(OI)(CI)(IO)(W)",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if grant.returncode != 0:
                print("FAIL: icacls inherit-only Users write on ancestor failed")
                return 1
            weak_key = anc / "keystore" / "node.key"
            try:
                abs_native.libp2p_node_new(
                    enable_mdns=False,
                    enable_reconnect=False,
                    key_path=str(weak_key),
                )
                print("FAIL: inherited Users-writable parent was accepted")
                return 1
            except Exception as exc:
                msg = str(exc).lower()
                if not any(token in msg for token in ("parent", "write", "dacl", "dir")):
                    print(f"FAIL: inherited parent error too vague: {exc}")
                    return 1
            if weak_key.exists():
                print("FAIL: key written before parent recheck")
                return 1
            created = anc / "keystore"
            if not created.is_dir():
                print("FAIL: missing parent was not created before recheck")
                return 1
            sddl = _dir_sddl(created)
            if not _sddl_grants_users(sddl):
                print("FAIL: Users ACE did not inherit onto created parent")
                return 1
            subprocess.run(
                ["icacls", str(anc), "/remove", "*S-1-5-32-545"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

        b = abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(clean_key),
        )
        try:
            if b.peer_id != pid:
                print(f"FAIL: PeerId changed after mkdir-recheck {pid} -> {b.peer_id}")
                return 1
        finally:
            b.close()
        print(f"OK: identity parent mkdir recheck strategy={want} peer_id={pid}")

    print("OK: libp2p_rust_identity_parent_mkdir_recheck_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; mkdir-then-recheck refuses inherited "
        "world-writable parent; no silent directory ACL rewrite; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
