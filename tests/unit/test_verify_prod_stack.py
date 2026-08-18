#!/usr/bin/env python3
"""verify_prod_stack.py tests."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_prod_stack


def test_verify_prod_stack_static_ok():
    with patch.object(verify_prod_stack, "check_prod_gate", return_value=[]):
        with patch.object(verify_prod_stack, "check_docker_prod_compose", return_value=[]):
            errors = verify_prod_stack.check_config_validate()
    assert isinstance(errors, list)

def test_bridge_enabled_profile_requires_bridge_binary(tmp_path, monkeypatch):
    """If bridge_enabled=true, missing abs_bridge_bin must not be suppressed."""
    cfg_path = tmp_path / "node.prod.example.json"
    cfg_path.write_text(
        json.dumps(
            {
                "deployment_mode": "prod",
                "chain_id": 778888,
                "bridge_enabled": True,
                "bridge_mode": "rust",
                "rust_bridge_path": str(tmp_path / "missing_abs_bridge_bin"),
                "bridge_require_l1_proof": True,
                "require_wallet_file": False,
                "rpc_api_key_required": False,
                "jwt_enforce_admin": True,
                "require_native_crypto": True,
                "evm_create2_eip1014": True,
                "evm_require_deploy_salt": True,
                "tip_safety_enforce": True,
                "p2p_native_transport": True,
                "validators_manifest_path": "validators.manifest.example.json",
                "cors_origins": ["https://explorer.example.com"],
            }
        ),
        encoding="utf-8",
    )
    # Host/mesh env must not hide the missing binary (BRIDGE_ENABLED=false, real RUST_BRIDGE_PATH).
    monkeypatch.setenv("BRIDGE_ENABLED", "true")
    monkeypatch.setenv("BRIDGE_MODE", "rust")
    monkeypatch.setenv("TIP_SAFETY_ENFORCE", "true")
    monkeypatch.delenv("RUST_BRIDGE_PATH", raising=False)
    monkeypatch.setattr(verify_prod_stack, "ROOT", tmp_path)
    errors = verify_prod_stack.check_config_validate("node.prod.example.json")
    assert any("binary missing" in e.lower() or "rust binary" in e.lower() for e in errors), errors


def test_docker_compose_prod_has_relayer():
    text = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "relayer:" in text
    assert "profiles:" in text
    assert "- bridge" in text
