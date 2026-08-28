#!/usr/bin/env python3
"""Optional batch verify for parallel R&D work (no soak / no prod mesh).

Runs the lab scripts + focused unit tests that do not require Docker mesh.
Exit 0 = all PASS.

Usage:
  python scripts/verify_parallel_rd_batch.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LABS = [
    "scripts/oracle_lab.py",
    "scripts/cross_shard_lab.py",
    "scripts/evm_precompile_lab.py",
    "scripts/evm_rpc_lab.py",
    "scripts/evm_nested_lab.py",
    "scripts/evm_reorg_lab.py",
    "scripts/evm_logs_lab.py",
    "scripts/long_range_lab_2h_harness.py",
]

UNIT = [
    "tests/unit/test_mempool_port.py",
    "tests/unit/test_evm_runtime.py",
    "tests/unit/test_evm_rpc_compat.py::test_eth_estimate_gas_null_without_adapter",
    "tests/unit/test_evm_rpc_compat.py::test_eth_max_priority_fee_null_without_eip1559",
    "tests/unit/test_evm_rpc_compat.py::test_eth_coinbase_mining_hashrate_honesty",
    "tests/unit/test_evm_rpc_compat.py::test_eth_get_code_balance_storage_missing_account",
    "tests/unit/test_evm_rpc_compat.py::test_eth_chain_net_sync_client_honesty",
]


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


def main() -> int:
    py = sys.executable
    fails = 0
    for lab in LABS:
        if not _run([py, str(ROOT / lab)], lab):
            fails += 1
    if not _run([py, "-m", "pytest", "-q", *UNIT], "focused unit"):
        fails += 1
    if not _run([py, str(ROOT / "scripts" / "industrial_gate.py")], "industrial_gate"):
        fails += 1
    if fails:
        print(f"BATCH FAIL: {fails} step(s)")
        return 1
    print("BATCH PASS: parallel R&D labs + gate (not soak / not libp2p 48h)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
