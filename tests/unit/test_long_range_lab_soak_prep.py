#!/usr/bin/env python3
"""Unit tests for Long-Range lab WS seed helper (no Docker)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = ROOT / "scripts" / "seed_long_range_lab_ws.py"
    spec = importlib.util.spec_from_file_location("seed_long_range_lab_ws", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_writes_valid_checkpoint(tmp_path):
    mod = _load()
    persist = tmp_path / "ws_checkpoint.json"
    path = mod.seed(persist=persist, height=0, block_hash="ab" * 32)
    assert path.is_file()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["items"]
    assert int(raw["items"][0]["height"]) == 0
    assert raw["items"][0]["block_hash"] == "ab" * 32
    assert raw["items"][0].get("digest")


def test_lab_node_json_arms_tip_safety():
    node = json.loads((ROOT / "node.long_range.lab.json").read_text(encoding="utf-8"))
    assert node["feature_long_range"] is True
    assert node["tip_safety_enforce"] is True
    assert node["tip_safety_shadow"] is True
    assert node["deployment_mode"] == "dev"
    assert int(node["chain_id"]) != 778888
    assert node["mining_enabled"] is True
    assert "lr1:5000" in node["bootstrap_peers"]


def test_lr_compose_bind_and_tip_safety():
    text = (ROOT / "docker-compose.long_range.lab.yml").read_text(encoding="utf-8")
    assert "TIP_SAFETY_ENFORCE" in text
    assert "./data/long_range_lab0" in text
    assert "29080" in text
    assert "29081" in text
    assert "29082" in text
    assert '"18180:' not in text
    assert "lr1:" in text
    assert "ABS_WS_COMMITTEE" in text
