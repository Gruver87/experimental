#!/usr/bin/env python3
"""ADR 0017 Long-Range runtime wiring (Config + env arm, honesty snapshot)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consensus.adapter import ConsensusAdapter
from consensus.long_range.runtime import (
    build_ws_service,
    long_range_feature_armed,
    weak_subjectivity_honesty_snapshot,
)
from consensus.tip_safety.shadow import _optional_ws_service
from runtime.config import Config


def test_prod_never_arms(monkeypatch) -> None:
    monkeypatch.setenv("FEATURE_LONG_RANGE", "true")
    cfg = Config()
    cfg.deployment_mode = "prod"
    assert long_range_feature_armed(cfg) is False
    assert build_ws_service(cfg) is None
    assert _optional_ws_service(cfg) is None


def test_dev_config_flag_arms_without_env(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("FEATURE_LONG_RANGE", raising=False)
    path = tmp_path / "ws.json"
    monkeypatch.setenv("ABS_WS_CHECKPOINT_PATH", str(path))
    monkeypatch.setenv("ABS_WS_ANCHOR_HEIGHT", "7")
    monkeypatch.setenv("ABS_WS_ANCHOR_HASH", "aa" * 32)

    cfg = Config()
    cfg.deployment_mode = "dev"
    cfg.feature_long_range = True
    assert long_range_feature_armed(cfg) is True
    svc = build_ws_service(cfg)
    assert svc is not None
    anchor = svc.get_anchor()
    assert anchor is not None
    assert int(anchor.height) == 7


def test_honesty_prod_always_off() -> None:
    cfg = SimpleNamespace(
        deployment_mode="prod",
        feature_long_range=False,
        finality_quorum_live=False,
    )

    class _A:
        config = cfg

        def weak_subjectivity_status(self):
            return ConsensusAdapter.weak_subjectivity_status(self)  # type: ignore[arg-type]

    status = _A().weak_subjectivity_status()
    assert status["long_range_defense"] is False
    assert status["long_range_armed"] is False


def test_honesty_dev_armed_with_anchor(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("FEATURE_LONG_RANGE", raising=False)
    path = tmp_path / "ws.json"
    monkeypatch.setenv("ABS_WS_CHECKPOINT_PATH", str(path))
    monkeypatch.setenv("ABS_WS_ANCHOR_HEIGHT", "12")
    monkeypatch.setenv("ABS_WS_ANCHOR_HASH", "bb" * 32)

    cfg = Config()
    cfg.deployment_mode = "dev"
    cfg.feature_long_range = True
    cfg.finality_quorum_live = False
    snap = weak_subjectivity_honesty_snapshot(cfg)
    assert snap["long_range_armed"] is True
    assert snap["long_range_defense"] is True
    assert snap["weak_subjectivity_checkpoints"] is True
    assert snap["ws_anchor_height"] == 12
