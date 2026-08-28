#!/usr/bin/env python3
"""Unit tests for EVM runtime honesty snapshot (Profile A wave-9)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution.evm_runtime import compat_matrix_rows, evm_compat_honesty_snapshot
from runtime.config import Config


def test_compat_matrix_has_partial_and_not_claimed() -> None:
    rows = compat_matrix_rows()
    statuses = {r["status"] for r in rows}
    assert "partial" in statuses
    assert "not_claimed" in statuses
    assert "supported" in statuses or "supported_prod" in statuses


def test_evm_snapshot_dev_profile() -> None:
    cfg = Config()
    cfg.deployment_mode = "dev"
    snap = evm_compat_honesty_snapshot(cfg)
    assert snap["evm_enabled"] is True
    assert snap["partial_count"] >= 1
    assert "evm_rpc_lab.py" in " ".join(snap["lab_scripts"])


def test_evm_snapshot_prod_hardened() -> None:
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.evm_create2_eip1014 = True
    cfg.evm_require_deploy_salt = True
    snap = evm_compat_honesty_snapshot(cfg)
    assert snap["prod_hardened"] is True
    assert "not full geth" in snap["detail"]


def test_evm_snapshot_prod_incomplete_without_create2() -> None:
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.evm_create2_eip1014 = False
    cfg.evm_require_deploy_salt = True
    snap = evm_compat_honesty_snapshot(cfg)
    assert snap["prod_hardened"] is False
    assert "incomplete" in snap["detail"]
