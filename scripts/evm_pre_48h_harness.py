#!/usr/bin/env python3
"""EVM pre-48h harness — prove mesh EVM path before any soak claim.

Does NOT start a 48h soak. Exit 0 = labs + gate + live mesh smoke PASS.

Usage:
  python scripts/evm_pre_48h_harness.py
  python scripts/evm_pre_48h_harness.py --skip-mesh   # labs+gate only

Honesty: PASS here is Phase 3 readiness, not EVM-only 48h, not mainnet, not BLS.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EVM_LABS = [
    "scripts/evm_precompile_lab.py",
    "scripts/evm_rpc_lab.py",
    "scripts/evm_nested_lab.py",
    "scripts/evm_reorg_lab.py",
    "scripts/evm_logs_lab.py",
    "scripts/evm_filters_lab.py",
]

EVM_UNIT = [
    "tests/unit/test_evm_runtime.py",
    "tests/unit/test_evm_rpc_compat.py",
    "tests/unit/test_sprout_profiles.py",
]

PROD_HTTP = (18180, 18181, 18182)


def _run(cmd: list[str], label: str) -> bool:
    print(f"==> {label}")
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        print(f"FAIL: {label} (exit {proc.returncode})")
        return False
    print(f"OK: {label}")
    return True


def _http_live(port: int, timeout: float = 8.0) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/health/live", timeout=timeout)
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _refuse_prod_ports_in_lab(ports: tuple[int, ...]) -> None:
    for p in ports:
        if p in (29080, 29081, 29082):
            raise SystemExit("REFUSE: EVM mesh harness must use prod ports 18180-18182")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--skip-mesh",
        action="store_true",
        help="skip probe + prod_evm_smoke (labs and industrial_gate only)",
    )
    args = ap.parse_args()
    py = sys.executable
    fails = 0

    print("EVM pre-48h harness (ADR 0010 / Profile A) — does NOT start soak")
    for lab in EVM_LABS:
        if not _run([py, str(ROOT / lab)], lab):
            fails += 1
    if not _run([py, "-m", "pytest", "-q", *EVM_UNIT], "evm focused unit"):
        fails += 1
    if not _run([py, str(ROOT / "scripts" / "industrial_gate.py")], "industrial_gate"):
        fails += 1

    if not args.skip_mesh:
        _refuse_prod_ports_in_lab(PROD_HTTP)
        dead = [p for p in PROD_HTTP if not _http_live(p)]
        if dead:
            print(
                f"FAIL: prod mesh HTTP live missing on {dead} "
                "(recreate: .\\scripts\\docker_prod_3node.ps1 -SkipBuild -KeepVolumes)"
            )
            fails += 1
        else:
            probe = ROOT / "scripts" / "probe_prod_mesh.ps1"
            if not _run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(probe),
                    "-Quick",
                ],
                "probe_prod_mesh -Quick",
            ):
                fails += 1
            if not _run(
                [py, str(ROOT / "scripts" / "prod_evm_smoke.py")],
                "prod_evm_smoke",
            ):
                fails += 1

    if fails:
        print(f"EVM pre-48h FAIL: {fails} step(s) — do not start soak")
        print("NOT: 48h claim / mainnet / BLS / Hybrid")
        return 1
    scope = "labs + gate only (--skip-mesh)" if args.skip_mesh else "labs + gate + mesh smoke"
    print(f"OK: EVM pre-48h harness PASS ({scope})")
    print("NOT: 48h soak started; not mainnet; not BLS; not Hybrid")
    if not args.skip_mesh:
        print("Next (manual): .\\scripts\\prepare_48h_soak.ps1 then start_soak_prod_mesh_48h.ps1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
