"""Unit tests for ADR 0017 autonomous WS roll-forward (lab)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from consensus.long_range.checkpoint import CheckpointCertificate
from consensus.long_range.checkpoint_store import CheckpointStore
from consensus.long_range.committee import generate_keypair, sign_with_keys
from consensus.long_range.roll_forward import (
    OUTCOME_ISSUED,
    OUTCOME_NOT_DUE,
    OUTCOME_NOT_MINER,
    OUTCOME_NO_SEED,
    OUTCOME_UNARMED,
    maybe_roll_ws_checkpoint,
    roll_forward_gap_threshold,
)


def _seed_store(path: Path, *, height: int, block_hash: str) -> None:
    store = CheckpointStore()
    store.push(
        CheckpointCertificate.issue(
            height=height, block_hash=block_hash, issuer="seed_test"
        )
    )
    store.save(path)


def test_roll_forward_gap_threshold_clamped(monkeypatch):
    monkeypatch.delenv("ABS_WS_ROLL_GAP", raising=False)
    monkeypatch.setenv("TIP_ANCESTRY_WINDOW_MAX", "256")
    assert roll_forward_gap_threshold() == 128
    monkeypatch.setenv("ABS_WS_ROLL_GAP", "50")
    assert roll_forward_gap_threshold() == 50


def test_roll_forward_unarmed(monkeypatch, tmp_path):
    monkeypatch.delenv("FEATURE_LONG_RANGE", raising=False)
    cfg = SimpleNamespace(deployment_mode="dev", feature_long_range=False)
    out = maybe_roll_ws_checkpoint(
        config=cfg,
        tip_height=100,
        tip_hash="ab" * 32,
        mining_enabled=True,
    )
    assert out["outcome"] == OUTCOME_UNARMED
    assert out["issued"] is False


def test_roll_forward_not_miner(monkeypatch, tmp_path):
    monkeypatch.setenv("FEATURE_LONG_RANGE", "true")
    monkeypatch.delenv("ABS_WS_COMMITTEE_REQUIRED", raising=False)
    monkeypatch.delenv("ABS_WS_COMMITTEE_PUBKEYS", raising=False)
    monkeypatch.delenv("ABS_WS_COMMITTEE_PUBKEYS_FILE", raising=False)
    persist = tmp_path / "ws.json"
    monkeypatch.setenv("ABS_WS_CHECKPOINT_PATH", str(persist))
    _seed_store(persist, height=10, block_hash="aa" * 32)
    cfg = SimpleNamespace(deployment_mode="dev", feature_long_range=True)
    out = maybe_roll_ws_checkpoint(
        config=cfg,
        tip_height=500,
        tip_hash="bb" * 32,
        gap_threshold=64,
        mining_enabled=False,
    )
    assert out["outcome"] == OUTCOME_NOT_MINER


def test_roll_forward_not_due_and_no_seed(monkeypatch, tmp_path):
    monkeypatch.setenv("FEATURE_LONG_RANGE", "true")
    monkeypatch.delenv("ABS_WS_COMMITTEE_REQUIRED", raising=False)
    monkeypatch.delenv("ABS_WS_COMMITTEE_PUBKEYS", raising=False)
    monkeypatch.delenv("ABS_WS_COMMITTEE_PUBKEYS_FILE", raising=False)
    monkeypatch.delenv("ABS_WS_ROLL_CONFIRM", raising=False)
    persist = tmp_path / "ws.json"
    monkeypatch.setenv("ABS_WS_CHECKPOINT_PATH", str(persist))
    cfg = SimpleNamespace(
        deployment_mode="dev", feature_long_range=True, mining_enabled=True
    )
    out = maybe_roll_ws_checkpoint(
        config=cfg,
        tip_height=100,
        tip_hash="cc" * 32,
        gap_threshold=64,
        mining_enabled=True,
        confirm_depth=0,
    )
    assert out["outcome"] == OUTCOME_NO_SEED

    _seed_store(persist, height=10, block_hash="aa" * 32)
    out2 = maybe_roll_ws_checkpoint(
        config=cfg,
        tip_height=50,
        tip_hash="dd" * 32,
        gap_threshold=64,
        mining_enabled=True,
        confirm_depth=0,
    )
    assert out2["outcome"] == OUTCOME_NOT_DUE
    assert out2["gap"] == 40


def test_roll_forward_issues_and_persists(monkeypatch, tmp_path):
    monkeypatch.setenv("FEATURE_LONG_RANGE", "true")
    monkeypatch.delenv("ABS_WS_COMMITTEE_REQUIRED", raising=False)
    monkeypatch.delenv("ABS_WS_COMMITTEE_PUBKEYS", raising=False)
    monkeypatch.delenv("ABS_WS_COMMITTEE_PUBKEYS_FILE", raising=False)
    persist = tmp_path / "ws.json"
    monkeypatch.setenv("ABS_WS_CHECKPOINT_PATH", str(persist))
    _seed_store(persist, height=10, block_hash="aa" * 32)
    tip_hash = "ee" * 32
    cfg = SimpleNamespace(
        deployment_mode="dev", feature_long_range=True, mining_enabled=True
    )
    out = maybe_roll_ws_checkpoint(
        config=cfg,
        tip_height=200,
        tip_hash=tip_hash,
        gap_threshold=64,
        mining_enabled=True,
        confirm_depth=0,
    )
    assert out["outcome"] == OUTCOME_ISSUED
    assert out["issued"] is True
    assert int(out["anchor_height"]) == 200
    assert int(out["prev_anchor_height"]) == 10
    store = CheckpointStore.load(persist)
    latest = store.latest()
    assert latest is not None
    assert int(latest.anchor.height) == 200
    assert latest.anchor.block_hash == tip_hash
    assert latest.verify_digest()


def test_roll_forward_confirm_depth_pins_ancestor(monkeypatch, tmp_path):
    monkeypatch.setenv("FEATURE_LONG_RANGE", "true")
    monkeypatch.delenv("ABS_WS_COMMITTEE_REQUIRED", raising=False)
    monkeypatch.delenv("ABS_WS_COMMITTEE_PUBKEYS", raising=False)
    monkeypatch.delenv("ABS_WS_COMMITTEE_PUBKEYS_FILE", raising=False)
    persist = tmp_path / "ws.json"
    monkeypatch.setenv("ABS_WS_CHECKPOINT_PATH", str(persist))
    _seed_store(persist, height=10, block_hash="aa" * 32)
    confirmed = "ff" * 32
    cfg = SimpleNamespace(
        deployment_mode="dev", feature_long_range=True, mining_enabled=True
    )
    out = maybe_roll_ws_checkpoint(
        config=cfg,
        tip_height=200,
        tip_hash=confirmed,
        gap_threshold=64,
        mining_enabled=True,
        confirm_depth=16,
    )
    assert out["outcome"] == OUTCOME_ISSUED
    assert int(out["anchor_height"]) == 184
    assert CheckpointStore.load(persist).latest().anchor.block_hash == confirmed


def test_roll_forward_committee_required_signs(monkeypatch, tmp_path):
    keys = [generate_keypair() for _ in range(3)]
    pubs = ",".join(p for _, p in keys)
    monkeypatch.setenv("FEATURE_LONG_RANGE", "true")
    monkeypatch.setenv("ABS_WS_COMMITTEE_PUBKEYS", pubs)
    monkeypatch.setenv("ABS_WS_COMMITTEE_REQUIRED", "true")
    monkeypatch.setenv("ABS_WS_COMMITTEE_THRESHOLD", "2")
    secrets = {
        "threshold": 2,
        "members": [
            {"private_key": keys[0][0], "public_key": keys[0][1]},
            {"private_key": keys[1][0], "public_key": keys[1][1]},
            {"private_key": keys[2][0], "public_key": keys[2][1]},
        ],
    }
    sec_path = tmp_path / "secrets.json"
    sec_path.write_text(json.dumps(secrets), encoding="utf-8")
    monkeypatch.setenv("ABS_WS_COMMITTEE_SECRETS_FILE", str(sec_path))
    persist = tmp_path / "ws.json"
    monkeypatch.setenv("ABS_WS_CHECKPOINT_PATH", str(persist))
    # Seed with signed cert so store is valid under committee mode.
    seed = CheckpointCertificate.issue(height=5, block_hash="11" * 32, issuer="seed")
    seed = seed.with_signatures(
        sign_with_keys(digest=seed.digest, private_keys_hex=[keys[0][0], keys[1][0]])
    )
    store = CheckpointStore()
    store.push(seed)
    store.save(persist)

    tip_hash = "22" * 32
    cfg = SimpleNamespace(
        deployment_mode="dev", feature_long_range=True, mining_enabled=True
    )
    out = maybe_roll_ws_checkpoint(
        config=cfg,
        tip_height=500,
        tip_hash=tip_hash,
        gap_threshold=64,
        mining_enabled=True,
        confirm_depth=0,
    )
    assert out["outcome"] == OUTCOME_ISSUED
    payload = out["payload"]
    assert payload.get("signatures")
    rolled = CheckpointCertificate.from_dict(payload)
    assert rolled.verify_committee()