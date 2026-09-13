#!/usr/bin/env python3
"""ADR 0021 Phase 4.1+4.2+4.3 operator verify — host kernels/store + optional mesh.

Covers:
  - phase 1 post-sig snapshot kernel (mempool_validate_post_sig)
  - phase 2 fee-sorted store (MempoolStore / Mempool.store_backend)
  - phase 3 EVM deploy admit (mempool_admit_evm_deploy)

Does NOT start soak. Does NOT rebuild Docker (mesh may still be on old bake).

Usage:
  python scripts/verify_adr0021_phase1.py
  python scripts/verify_adr0021_phase1.py --skip-mesh
  python scripts/verify_adr0021_phase1.py --require-rust

Honesty: PASS here = phase-1/2/3 host path + goldens (+ mesh probe if not skipped).
Not soak. Not mainnet. Not Hybrid pin.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "tests" / "fixtures" / "adr0021_phase1"
PROD_HTTP = (18180, 18181, 18182)


def _run(cmd: list[str], label: str) -> bool:
    print(f"==> {label}")
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, encoding="utf-8", errors="replace")
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


def _kernel_goldens(*, require_rust: bool) -> bool:
    from crypto.native import (
        create_mempool_store,
        mempool_admit_evm_deploy,
        mempool_validate_post_sig,
        native_capabilities_status,
    )

    caps = native_capabilities_status()
    fam = (caps.get("families") or {}).get("mempool_kernel") or {}
    store_fam = (caps.get("families") or {}).get("mempool_store") or {}
    print(f"  mempool_kernel family: {json.dumps(fam, sort_keys=True)}")
    print(f"  mempool_store family: {json.dumps(store_fam, sort_keys=True)}")
    if require_rust and fam.get("backend") != "rust":
        print("FAIL: --require-rust but mempool_kernel backend is not rust")
        return False
    if require_rust and store_fam.get("backend") != "rust":
        print("FAIL: --require-rust but mempool_store backend is not rust")
        return False

    for name in (
        "kernel_input_accept.json",
        "kernel_input_refuse_nonce.json",
        "kernel_input_refuse_balance.json",
    ):
        doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        out = mempool_validate_post_sig(doc["snapshot"], doc["tx"])
        want_accept = bool(doc["expected"]["accept"])
        got_accept = bool(out.get("accept"))
        if got_accept != want_accept:
            print(f"FAIL: {name} accept want={want_accept} got={got_accept} out={out}")
            return False
        if not want_accept and out.get("reason") != doc["expected"]["reason"]:
            print(f"FAIL: {name} reason want={doc['expected']['reason']} got={out.get('reason')}")
            return False
        print(f"  OK golden {name}")

    for name in (
        "pipeline_refuse_deploy_eof.json",
        "pipeline_refuse_deploy_bad_opcode.json",
    ):
        doc = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        out = mempool_admit_evm_deploy(doc["bytecode_hex"])
        if out.get("accept"):
            print(f"FAIL: {name} expected refuse, got accept")
            return False
        if out.get("reason") != doc["expected_pipeline_error"]:
            print(
                f"FAIL: {name} reason want={doc['expected_pipeline_error']} "
                f"got={out.get('reason')}"
            )
            return False
        print(f"  OK deploy golden {name}")

    store = create_mempool_store(8, 0.0)
    if require_rust and store is None:
        print("FAIL: create_mempool_store returned None under --require-rust")
        return False
    if store is not None:
        assert store.insert(
            {
                "tx_hash": "v_high",
                "from_addr": "0xa",
                "to_addr": "0xb",
                "amount": 1.0,
                "fee": 9.0,
                "nonce": 0,
                "signature": "",
                "public_key": "",
                "data": "",
                "gas": 21_000,
                "timestamp": 1.0,
            }
        )
        assert store.insert(
            {
                "tx_hash": "v_low",
                "from_addr": "0xa",
                "to_addr": "0xb",
                "amount": 1.0,
                "fee": 1.0,
                "nonce": 1,
                "signature": "",
                "public_key": "",
                "data": "",
                "gas": 21_000,
                "timestamp": 1.0,
            }
        )
        ranked = list(store.get_sorted(10, 0.0))
        if not ranked or str(ranked[0].get("tx_hash")) != "v_high":
            print(f"FAIL: store sort want v_high first, got {ranked}")
            return False
        print("  OK mempool_store fee sort")
    else:
        print("  OK mempool_store python fallback (no native store)")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-mesh", action="store_true", help="labs/units/gate only")
    ap.add_argument(
        "--require-rust",
        action="store_true",
        help="fail if mempool_kernel / mempool_store families are not rust",
    )
    args = ap.parse_args()
    py = sys.executable
    fails = 0

    print("ADR 0021 Phase 4.1+4.2+4.3 verify — does NOT start soak / does NOT rebuild image")
    if not _kernel_goldens(require_rust=args.require_rust):
        fails += 1
    if not _run(
        [py, "-m", "pytest", "-q", "tests/unit/test_adr0021_phase1_fixtures.py"],
        "pytest adr0021 phase1+3",
    ):
        fails += 1
    if not _run(
        [py, "-m", "pytest", "-q", "tests/unit/test_adr0021_phase2_store.py"],
        "pytest adr0021 phase2 store",
    ):
        fails += 1
    if not _run([py, str(ROOT / "scripts" / "industrial_gate.py")], "industrial_gate"):
        fails += 1

    if not args.skip_mesh:
        dead = [p for p in PROD_HTTP if not _http_live(p)]
        if dead:
            print(
                f"FAIL: prod mesh live missing on {dead} "
                "(bring up: .\\scripts\\docker_prod_3node.ps1 -SkipBuild -KeepVolumes)"
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
            print(
                "NOTE: mesh containers may still run pre-4.2 bake (-SkipBuild). "
                "Host kernel/store PASS != baked image yet."
            )

    if fails:
        print(f"ADR 0021 phase-1/2/3 FAIL: {fails} step(s)")
        print("NOT: soak / mainnet / Hybrid")
        return 1
    print("OK: ADR 0021 Phase 4.1+4.2+4.3 verify PASS")
    print("NOT: soak / mainnet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
