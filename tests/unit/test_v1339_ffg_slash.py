#!/usr/bin/env python3
"""v1.3.39: native FFG finality + slashing conflict kernels."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crypto import native
from consensus.finality_casper import CasperFinality
from consensus.slashing import SlashingEngine
from finality_engine import FinalityEngine


def test_native_ffg_symbols():
    assert native.native_available()
    for name in (
        "ffg_threshold",
        "ffg_best_checkpoint",
        "ffg_accumulate_vote",
        "ffg_evaluate_epoch",
        "fe_epoch",
        "fe_quorum_reached",
        "fe_can_finalize",
        "slash_check_double_vote",
        "slash_check_double_proposal",
    ):
        assert hasattr(native, name), name


def test_ffg_threshold_and_casper_two_step():
    assert native.ffg_threshold(100, 2, 3) == 66
    cf = CasperFinality()
    cf.set_total_stake(300)
    cf.add_vote(1, "0xaaa", 200)
    assert 1 in cf.justified_epochs
    cf.add_vote(2, "0xbbb", 200)
    assert 2 in cf.justified_epochs
    assert 1 in cf.finalized_epochs


def test_slash_double_vote_and_proposal():
    eng = SlashingEngine()
    eng.register_validator("v1", 100)
    assert eng.record_vote("v1", 1, "0x1") is True
    assert eng.record_vote("v1", 1, "0x1") is True  # duplicate OK
    assert eng.record_vote("v1", 1, "0x2") is False  # conflict
    assert eng.is_slashed("v1")

    eng2 = SlashingEngine()
    eng2.register_validator("v2", 100)
    assert eng2.record_proposal("v2", 10, "0xa") is True
    assert eng2.record_proposal("v2", 10, "0xa") is True  # same-hash retry OK
    assert eng2.record_proposal("v2", 10, "0xb") is False
    assert eng2.is_slashed("v2")
    # Already-slashed validator may still land a new canonical height (catch-up).
    assert eng2.record_proposal("v2", 11, "0xc") is True


def test_finality_engine_quorum_native():
    fe = FinalityEngine()
    fe.set_active_validator_count(3)
    assert fe.get_epoch(33) == 1
    fe.create_checkpoint(32, "0xcp")
    assert fe.add_attestation("a", 1, "0xcp")
    assert fe.add_attestation("b", 1, "0xcp")
    # 2/3 of 3 = 2 → justified
    assert 1 in fe.justified_checkpoints
    fe.create_checkpoint(0, "0xgen")
    fe.justified_checkpoints.append(0)
    assert fe.finalize_checkpoint(1) is True


def test_wiring_surfaces():
    assert "ffg_evaluate_epoch" in Path("consensus/finality_casper.py").read_text(encoding="utf-8")
    assert "slash_check_double_vote" in Path("consensus/slashing.py").read_text(encoding="utf-8")
    assert "fe_quorum_reached" in Path("finality_engine.py").read_text(encoding="utf-8")
    assert "native fe_quorum_reached failed" in Path("finality_engine.py").read_text(
        encoding="utf-8"
    )
    assert '_native_fb("ffg_accumulate_vote"' in Path(
        "consensus/finality_casper.py"
    ).read_text(encoding="utf-8")
    assert '_native_fb("ghost_select_head"' in Path("consensus/ghost.py").read_text(
        encoding="utf-8"
    )
    assert "ffg_evaluate_epoch" in Path("consensus/finality_beacon.py").read_text(encoding="utf-8")
