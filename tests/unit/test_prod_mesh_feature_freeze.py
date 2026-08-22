#!/usr/bin/env python3
"""ADR 0016 — prod mesh FEATURE_* freeze and MODULE_TIERS honesty."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features import FeatureFlags, MODULE_TIERS

_FEATURE_KEYS_OFF = (
    "feature_zk",
    "feature_minivm",
    "feature_sharding",
    "feature_oracles",
    "feature_wasm",
    "feature_plasma",
    "feature_lightning",
    "feature_pq",
    "feature_nft",
    "feature_mev",
    "feature_ai_agents",
    "feature_ai_validator",
    "feature_smart_accounts",
    "feature_validator_selection",
    "feature_long_range",
)


def test_module_tiers_nft_not_production() -> None:
    assert MODULE_TIERS["nft"] == "app-profile"
    assert MODULE_TIERS["reorg_predictor"] == "analysis"
    assert MODULE_TIERS["minivm"] == "r-and-d"


def test_prod_api_blocks_app_profile_sprouts() -> None:
    flags = FeatureFlags(nft=True, zk=True, evm=True)
    out = flags.to_api_dict(
        {"nft": object(), "zk": object(), "evm": object()},
        config=type("C", (), {"deployment_mode": "prod", "is_production": True})(),
    )
    assert out["nft"]["enabled"] is False
    assert out["nft"]["app_profile"] is True
    assert "ADR 0016" in out["nft"]["prod_blocked_reason"]
    assert out["zk"]["enabled"] is False
    assert out["evm"]["enabled"] is True


def test_prod_mesh_json_feature_freeze() -> None:
    for name in (
        "node.prod.mesh1.json",
        "node.prod.mesh2.json",
        "node.prod.mesh3.json",
        "node.prod.json",
    ):
        path = ROOT / "docker" / name
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("deployment_mode") == "prod"
        assert data.get("allow_state_root_rewrite") is False
        for key in _FEATURE_KEYS_OFF:
            assert data.get(key) is False, f"{name}.{key} must be false"
        if "mesh" in name:
            assert int(data.get("chain_id", 0)) == 778888
            assert data.get("feature_libp2p") is True, f"{name} ADR 0020 requires feature_libp2p true"
            assert data.get("p2p_tls_enabled") is False, f"{name} Noise mesh must not enable native mTLS"
        else:
            assert data.get("feature_libp2p") is False, f"{name} single-node stays TCP+TLS"
