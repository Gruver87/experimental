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
