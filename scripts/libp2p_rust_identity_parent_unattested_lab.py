#!/usr/bin/env python3
"""ADR 0019 Slice CT — identity parent ACL is always attested.

CR/CS reused ``should_fsync_dir``, which skips volume roots and relative
one-component parents. Slice CT resolves relative key paths against cwd and
refuses a volume-root parent. The key is not written. Directory ACL is never
rewritten. Fsync still skips volume roots. Capability
``identity_key_parent_unattested_refuse`` / phase >= 97.

Requires abs_native built with Cargo feature ``libp2p``.

Usage:
  python scripts/libp2p_rust_identity_parent_unattested_lab.py
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import time
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


def _volume_root_key() -> Path:
    stamp = f"{os.getpid()}-{time.time_ns()}"
    name = f"abs-ct-volroot-{stamp}.key"
    if os.name == "nt":
        anchor = Path(tempfile.gettempdir()).anchor
        return Path(anchor) / name
    return Path("/") / name


def main() -> int:
    try:
        import abs_native
    except ImportError:
        print("FAIL: abs_native not importable")
        return 1

    if not bool(getattr(abs_native, "libp2p_available", lambda: False)()):
        print("FAIL: abs_native.libp2p_available() is False")
        return 1

    want = "absolute_cwd_refuse_volume_root"
    mod_strategy = str(
        getattr(abs_native, "IDENTITY_KEY_PARENT_UNATTESTED_STRATEGY", "")
    )
    if mod_strategy != want:
        print(f"FAIL: module strategy {mod_strategy!r} != {want}")
        return 1

    vol = _volume_root_key()
    try:
        abs_native.libp2p_node_new(
            enable_mdns=False,
            enable_reconnect=False,
            key_path=str(vol),
        )
        print("FAIL: volume-root identity parent was accepted")
        return 1
    except Exception as exc:
        msg = str(exc).lower()
        if "volume root" not in msg and "unattested" not in msg:
            print(f"FAIL: volume-root error too vague: {exc}")
            return 1
    if vol.exists():
        print("FAIL: volume-root key was created")
        try:
            vol.unlink()
        except OSError:
            pass
        return 1

    old_cwd = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="abs-libp2p-id-unatt-") as td:
        td_path = Path(td)
        try:
            os.chdir(td)
            a = abs_native.libp2p_node_new(
                enable_mdns=False,
                enable_reconnect=False,
                key_path="node.key",
            )
            try:
                cap = a.capability_status()
                if not cap.get("identity_key_parent_unattested_refuse"):
                    print(f"FAIL: capability identity_key_parent_unattested_refuse: {cap}")
                    return 1
                if cap.get("identity_key_parent_unattested_strategy") != want:
                    print(
                        "FAIL: capability strategy "
                        f"{cap.get('identity_key_parent_unattested_strategy')!r} != {want}"
                    )
                    return 1
                if int(cap.get("phase", 0)) < 97:
                    print(f"FAIL: phase {cap.get('phase')}")
                    return 1
                pid = a.peer_id
            finally:
                a.close()
            rel = Path("node.key")
            if not rel.is_file():
                print("FAIL: relative identity path did not create cwd/node.key")
                return 1
            first = rel.read_bytes()

            if os.name == "posix":
                os.chmod(td_path, 0o0777)
                try:
                    abs_native.libp2p_node_new(
                        enable_mdns=False,
                        enable_reconnect=False,
                        key_path="node.key",
                    )
                    print("FAIL: world-writable cwd relative key was accepted")
                    return 1
                except Exception as exc:
                    msg = str(exc).lower()
                    if "parent" not in msg and "mode" not in msg and "group/other" not in msg:
                        print(f"FAIL: relative cwd parent error too vague: {exc}")
                        return 1
                if stat.S_IMODE(td_path.stat().st_mode) != 0o0777:
                    print("FAIL: cwd mode was silently rewritten")
                    return 1
                os.chmod(td_path, 0o0700)
            else:
                grant = subprocess.run(
                    ["icacls", str(td_path), "/grant", "*S-1-5-32-545:(W)"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )
                if grant.returncode != 0:
                    print("FAIL: icacls grant Users write on cwd failed")
                    return 1
                sddl_weak = _dir_sddl(td_path)
                if not _sddl_grants_users(sddl_weak):
                    print("FAIL: Users ACE did not land on cwd")
                    return 1
                try:
                    abs_native.libp2p_node_new(
                        enable_mdns=False,
                        enable_reconnect=False,
                        key_path="node.key",
                    )
                    print("FAIL: Users-writable cwd relative key was accepted")
                    return 1
                except Exception as exc:
                    msg = str(exc).lower()
                    if not any(token in msg for token in ("parent", "write", "dacl", "dir")):
                        print(f"FAIL: relative cwd parent error too vague: {exc}")
                        return 1
                if rel.read_bytes() != first:
                    print("FAIL: dest bytes changed after relative-cwd refuse")
                    return 1
                if _dir_sddl(td_path) != sddl_weak:
                    print("FAIL: cwd ACL was silently rewritten")
                    return 1
                subprocess.run(
                    ["icacls", str(td_path), "/remove", "*S-1-5-32-545"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                )

            b = abs_native.libp2p_node_new(
                enable_mdns=False,
                enable_reconnect=False,
                key_path="node.key",
            )
            try:
                if b.peer_id != pid:
                    print(f"FAIL: PeerId changed after relative restore {pid} -> {b.peer_id}")
                    return 1
            finally:
                b.close()
            print(f"OK: identity parent unattested refuse strategy={want} peer_id={pid}")
        finally:
            os.chdir(old_cwd)

    print("OK: libp2p_rust_identity_parent_unattested_lab PASS")
    print(
        "  honesty: FEATURE_LIBP2P lab; relative key uses cwd ACL; "
        "volume-root parent refuses; no silent directory ACL rewrite; "
        "TCP+TLS remains default mesh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
