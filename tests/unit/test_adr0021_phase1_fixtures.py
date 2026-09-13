#!/usr/bin/env python3
"""ADR 0021 phase 1 golden fixtures + mempool_validate_post_sig kernel."""

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


def test_kernel_fixtures_match_mempool_validate_post_sig() -> None:
    from crypto.native import mempool_validate_post_sig

    for name in (
        "kernel_input_accept.json",
        "kernel_input_refuse_nonce.json",
        "kernel_input_refuse_balance.json",
    ):
        doc = _load(name)
        out = mempool_validate_post_sig(doc["snapshot"], doc["tx"])
        assert bool(out.get("accept")) is bool(doc["expected"]["accept"]), name
        if doc["expected"]["accept"]:
            assert out.get("reason") in (None, "")
        else:
            assert out.get("reason") == doc["expected"]["reason"], name


def test_invariant_sig_before_snapshot_fixture() -> None:
    doc = _load("invariant_sig_before_snapshot.json")
    assert doc["invariant"] == "sig_before_snapshot"
    assert doc["order"][0] == "verify_signatures"
    assert doc["order"][1] == "build_snapshot"
    assert set(doc["snapshot_keys"]) == {"nonce", "balance_sat"}


def test_pipeline_deploy_refuse_fixtures_match_validator() -> None:
    """Phase 3 golden: bytecode validator + admit kernel match TxPipeline errors."""
    from crypto.native import mempool_admit_evm_deploy
    from execution.evm_bytecode_validator import validate_bytecode_hex

    eof = _load("pipeline_refuse_deploy_eof.json")
    v_eof = validate_bytecode_hex(eof["bytecode_hex"])
    assert not v_eof.get("valid")
    bad = v_eof.get("unsupported") or []
    name_eof = bad[0].get("name", "?") if bad else v_eof.get("error", "invalid")
    assert f"unsupported_evm_bytecode:{name_eof}" == eof["expected_pipeline_error"]
    admit_eof = mempool_admit_evm_deploy(eof["bytecode_hex"])
    assert not admit_eof.get("accept")
    assert admit_eof.get("reason") == eof["expected_pipeline_error"]

    bad_op = _load("pipeline_refuse_deploy_bad_opcode.json")
    v_bad = validate_bytecode_hex(bad_op["bytecode_hex"])
    assert not v_bad.get("valid")
    issues = v_bad.get("unsupported") or []
    assert issues, "expected unsupported opcode scan hit"
    name_bad = issues[0].get("name", "?")
    assert f"unsupported_evm_bytecode:{name_bad}" == bad_op["expected_pipeline_error"]
    admit_bad = mempool_admit_evm_deploy(bad_op["bytecode_hex"])
    assert not admit_bad.get("accept")
    assert admit_bad.get("reason") == bad_op["expected_pipeline_error"]


def test_tx_pipeline_deploy_admit_uses_kernel() -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from core.components.tx_pipeline import TxPipeline

    cfg = SimpleNamespace(
        require_signatures=False,
        base_gas_price=0,
        gas_price_wei=0,
        burn_rate=0,
        chain_id=778888,
    )
    storage = MagicMock()
    storage.get_nonce.return_value = 0
    storage.get_balance_satoshi.return_value = 10_000_000
    storage.get_account.return_value = None
    pipe = TxPipeline(
        config=cfg,
        storage=storage,
        get_evm=lambda: object(),
    )
    tx = SimpleNamespace(
        from_addr="0x1111111111111111111111111111111111111111",
        to_addr="0x2222222222222222222222222222222222222222",
        nonce=0,
        value=0,
        gas=21000,
        signature="",
        data="0xEF0000",
        zk_proof=None,
        public_key="",
    )
    out = pipe.validate_for_mempool(tx)
    assert not out.valid
    assert out.error == "unsupported_evm_bytecode:eof_container_not_supported"
    assert "mempool_admit_evm" in (out.meta or {})


def test_tx_pipeline_uses_post_sig_kernel_meta() -> None:
    """Kernel refuse maps to historical pipeline error strings."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from core.components.tx_pipeline import TxPipeline

    cfg = SimpleNamespace(
        require_signatures=False,
        base_gas_price=0,
        gas_price_wei=0,
        burn_rate=0,
    )
    storage = MagicMock()
    storage.get_nonce.return_value = 0
    storage.get_balance_satoshi.return_value = 100_000
    pipe = TxPipeline(config=cfg, storage=storage)
    tx = SimpleNamespace(
        from_addr="0x1111111111111111111111111111111111111111",
        to_addr="0x2222222222222222222222222222222222222222",
        nonce=0,
        value=0.09,  # 90_000 sat if multiplier 1e6
        gas=0,
        signature="",
        data="",
        zk_proof=None,
    )
    # Force fee via gas_price so total exceeds balance: use value that maps via plan.
    # Prefer direct kernel path assertion via validate with large value.
    from runtime.amount import to_satoshi

    # Ensure value_sat + fee exceeds balance for this test.
    tx.value = 1.0  # 1_000_000 sat >> 100_000
    out = pipe.validate_for_mempool(tx)
    assert not out.valid
    assert out.error == "insufficient_funds"
    assert out.meta.get("mempool_kernel") == "insufficient_balance"
    _ = to_satoshi  # keep import used if amount path changes
