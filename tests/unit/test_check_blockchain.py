#!/usr/bin/env python3
"""Honesty tests for scripts/check_blockchain.py soak reader."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = ROOT / "scripts" / "check_blockchain.py"
    spec = importlib.util.spec_from_file_location("check_blockchain", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_check_blockchain_scripts_exist():
    assert (ROOT / "scripts" / "check_blockchain.py").is_file()
    assert (ROOT / "scripts" / "check_blockchain.ps1").is_file()
    src = (ROOT / "scripts" / "check_blockchain.py").read_text(encoding="utf-8")
    assert "Does NOT start 48h soak" in src
    assert "--min-soak-hours" in src
    assert "Do NOT pass --min-soak-hours" in src
    assert '[py, "-m", "pytest", "-q", "--tb=line", "tests/"]' in src


def test_verify_full_blockchain_scripts_exist_and_do_not_start_soak():
    py = ROOT / "scripts" / "verify_full_blockchain.py"
    ps1 = ROOT / "scripts" / "verify_full_blockchain.ps1"
    assert py.is_file()
    assert ps1.is_file()
    src = py.read_text(encoding="utf-8")
    wrap = ps1.read_text(encoding="utf-8")
    assert "Does NOT start 48h soak" in src
    assert "Does NOT rebuild Docker" in src
    assert "start_soak" not in src.lower()
    assert "start_soak" not in wrap.lower()
    assert "scan-all" in src
    assert "_bind_prod_smoke_wallet" in src
    assert "PROD_SMOKE_WALLET_PATH" in src
    wrap.encode("ascii")
    run_all = (ROOT / "scripts" / "run_all_tests.ps1").read_text(encoding="utf-8")
    assert "verify_full_blockchain.ps1" in run_all


def test_run_all_tests_script_exists_and_does_not_start_soak():
    path = ROOT / "scripts" / "run_all_tests.ps1"
    assert path.is_file()
    src = path.read_text(encoding="utf-8")
    assert "Does NOT start 48h soak" in src
    assert "pytest tests/" in src
    assert "industrial_gate.py" in src
    assert "start_soak" not in src.lower()
    # PowerShell 5.1 breaks on non-ASCII in .ps1 without BOM.
    src.encode("ascii")


def test_soak_fail_file_never_painted_pass(tmp_path, monkeypatch):
    mod = _load()
    fail = tmp_path / "soak_report_48h_experimental.json"
    fail.write_text(
        json.dumps(
            {
                "passed": False,
                "hours_elapsed": 48.02,
                "counts": {"hard_fail_lines": 87},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "SOAK_48H", fail)
    monkeypatch.setattr(mod, "SOAK_5H", tmp_path / "missing.json")
    pack = mod.soak_honesty()
    assert pack["experimental_48h"]["passed"] is False
    assert pack["experimental_48h"]["claim"] == "FAIL"
    assert pack["claim_48h_pass"] is False
    assert pack["strict_5h"]["claim"] == "NOT_RUN"


def test_soak_pass_with_hard_fails_is_still_fail(tmp_path):
    mod = _load()
    p = tmp_path / "lie.json"
    p.write_text(
        json.dumps({"passed": True, "counts": {"hard_fail_lines": 3}}),
        encoding="utf-8",
    )
    row = mod.read_soak_report(p)
    assert row["passed"] is False
    assert row["claim"] == "FAIL"


def test_soak_true_zero_hard_fails_is_pass(tmp_path):
    mod = _load()
    p = tmp_path / "ok.json"
    p.write_text(
        json.dumps({"passed": True, "counts": {"hard_fail_lines": 0}}),
        encoding="utf-8",
    )
    row = mod.read_soak_report(p)
    assert row["passed"] is True
    assert row["claim"] == "PASS"
