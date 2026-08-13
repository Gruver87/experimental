#!/usr/bin/env python3
"""Run abs_native ``cargo test`` with a real CPython link.

PyO3 feature ``extension-module`` (crate default) skips linking libpython
because maturin wheels are loaded by the interpreter. ``cargo test`` emits a
standalone binary and MUST disable that feature so pyo3-build-config links
the interpreter from ``PYO3_PYTHON`` / ``sys.executable``.

Fail-closed: missing interpreter, unknown libpython location, or cargo != 0.
Does not stub symbols and does not skip tests.

Usage (repo root):
  python scripts/cargo_test_abs_native.py
  python scripts/cargo_test_abs_native.py --features libp2p --lib
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "native" / "abs_native" / "Cargo.toml"
AUTO_INIT = "auto-initialize"


class CargoTestAbsNativeError(Exception):
    """Fail-closed cargo-test / CPython link error."""


def cargo_test_argv(
    *, extra_features: list[str] | None = None, extra_args: list[str] | None = None
) -> list[str]:
    """Build the cargo test argv that links libpython (no extension-module)."""
    features: list[str] = []
    seen: set[str] = set()
    for feat in (AUTO_INIT, *(extra_features or [])):
        name = str(feat).strip()
        if not name or name in seen:
            continue
        if name in {"extension-module", "pyo3/extension-module", "default"}:
            raise CargoTestAbsNativeError(
                f"refusing feature {name!r}: that skips linking libpython"
            )
        seen.add(name)
        features.append(name)
    argv = [
        "cargo",
        "test",
        "--manifest-path",
        str(MANIFEST),
        "--no-default-features",
        "--features",
        ",".join(features),
    ]
    argv.extend(extra_args or [])
    return argv


def require_cpython() -> str:
    """Set PYO3_PYTHON and prove this process can locate CPython link inputs."""
    exe = sys.executable
    if not exe:
        raise CargoTestAbsNativeError("sys.executable is empty")
    os.environ["PYO3_PYTHON"] = exe
    print(f"PYO3_PYTHON={exe}")
    print(f"python={sys.version.split()[0]} platform={sys.platform}")
    if sys.platform == "win32":
        base = Path(sys.base_prefix)
        libs = base / "libs"
        dll = base / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
        print(f"win_libs={libs} exists={libs.is_dir()} dll={dll} exists={dll.is_file()}")
        if not libs.is_dir() and not dll.is_file():
            raise CargoTestAbsNativeError(
                f"CPython link inputs missing (libs={libs}, dll={dll})"
            )
        return exe
    libdir = sysconfig.get_config_var("LIBDIR") or sysconfig.get_config_var("LIBPL")
    print(f"LIBDIR={libdir}")
    if not libdir:
        raise CargoTestAbsNativeError("CPython LIBDIR/LIBPL unknown; cannot link libpython")
    lib_path = Path(str(libdir))
    if not lib_path.is_dir():
        raise CargoTestAbsNativeError(f"CPython LIBDIR is not a directory: {libdir}")
    return exe


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--features",
        default="",
        help="extra Cargo features (comma-separated), e.g. libp2p",
    )
    ap.add_argument(
        "cargo_args",
        nargs=argparse.REMAINDER,
        help="args passed to cargo test (use -- before flags, e.g. -- --lib)",
    )
    ns = ap.parse_args(argv)
    extra = [p.strip() for p in str(ns.features).split(",") if p.strip()]
    rest = list(ns.cargo_args or [])
    if rest[:1] == ["--"]:
        rest = rest[1:]
    try:
        require_cpython()
        cmd = cargo_test_argv(extra_features=extra, extra_args=rest)
    except CargoTestAbsNativeError as exc:
        print(f"FAIL: {exc}")
        return 1
    if not MANIFEST.is_file():
        print(f"FAIL: missing {MANIFEST}")
        return 1
    print("cargo:", " ".join(cmd))
    print("honesty: extension-module OFF; CPython linked; tests not skipped")
    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        print(f"FAIL: cargo test exit {proc.returncode}")
        return proc.returncode
    print("OK: cargo_test_abs_native PASS (CPython linked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
