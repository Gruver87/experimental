#!/usr/bin/env python3
"""ADR 0021 phase 1 golden fixtures — schema only (no Rust kernel)."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "adr0021_phase1"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _assert_snapshot(row: dict) -> None:
    assert set(row.keys()) == {"nonce", "balance_sat"}
    assert isinstance(row["nonce"], int) and row["nonce"] >= 0
    assert isinstance(row["balance_sat"], int) and row["balance_sat"] >= 0


def test_snapshot_minimal_fixture() -> None:
    snap = _load("snapshot_minimal.json")
    _assert_snapshot(snap)


def test_kernel_fixtures_schema() -> None:
    for name in (
        "kernel_input_accept.json",
        "kernel_input_refuse_nonce.json",
        "kernel_input_refuse_balance.json",
    ):
        doc = _load(name)
        assert "snapshot" in doc and "tx" in doc and "expected" in doc
        _assert_snapshot(doc["snapshot"])
        tx = doc["tx"]
        for key in ("from_addr", "to_addr", "nonce", "value_sat", "fee_sat", "gas_limit"):
            assert key in tx
        exp = doc["expected"]
        assert isinstance(exp["accept"], bool)
        if exp["accept"]:
            assert exp.get("reason") is None
        else:
            assert isinstance(exp.get("reason"), str) and exp["reason"]


def test_invariant_sig_before_snapshot_fixture() -> None:
    doc = _load("invariant_sig_before_snapshot.json")
    assert doc["invariant"] == "sig_before_snapshot"
    assert doc["order"][0] == "verify_signatures"
    assert doc["order"][1] == "build_snapshot"
    assert set(doc["snapshot_keys"]) == {"nonce", "balance_sat"}


def test_pipeline_deploy_refuse_fixtures_match_validator() -> None:
    """Phase 3 golden: bytecode validator output maps to TxPipeline error shape."""
    from execution.evm_bytecode_validator import validate_bytecode_hex

    eof = _load("pipeline_refuse_deploy_eof.json")
    v_eof = validate_bytecode_hex(eof["bytecode_hex"])
    assert not v_eof.get("valid")
    bad = v_eof.get("unsupported") or []
    name_eof = bad[0].get("name", "?") if bad else v_eof.get("error", "invalid")
    assert f"unsupported_evm_bytecode:{name_eof}" == eof["expected_pipeline_error"]

    bad_op = _load("pipeline_refuse_deploy_bad_opcode.json")
    v_bad = validate_bytecode_hex(bad_op["bytecode_hex"])
    assert not v_bad.get("valid")
    issues = v_bad.get("unsupported") or []
    assert issues, "expected unsupported opcode scan hit"
    name_bad = issues[0].get("name", "?")
    assert f"unsupported_evm_bytecode:{name_bad}" == bad_op["expected_pipeline_error"]
