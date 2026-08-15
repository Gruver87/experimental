#!/usr/bin/env python3
"""Production/staging config validation rules."""
import os
import json
import sys
import tempfile
import importlib.util
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from runtime.config import Config


def test_staging_config_valid():
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    path = os.path.join(root, "node.staging.example.json")
    cfg = Config.from_json(path)
    assert cfg.deployment_mode == "staging"
    assert cfg.validate() == []


def test_prod_rejects_simulator_bridge_without_override():
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.bridge_mode = "simulator"
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = False
    errs = cfg.validate()
    assert any("bridge_mode=rust" in e for e in errs)


def test_prod_rejects_devnet_chain_id():
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.chain_id = 77777
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = False
    cfg.evm_create2_eip1014 = True
    cfg.evm_require_deploy_salt = True
    errs = cfg.validate()
    assert any("chain_id 77777" in e for e in errs)


def test_prod_requires_deploy_salt_flag():
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.evm_require_deploy_salt = False
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = False
    cfg.require_native_crypto = True
    cfg.evm_create2_eip1014 = True
    cfg.chain_id = 778888

    errs = cfg.validate()
    assert any("evm_require_deploy_salt" in e for e in errs)


def test_static_prod_gate_requires_native_crypto(tmp_path, monkeypatch):
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    script_path = os.path.join(root, "scripts", "prod_gate.py")
    spec = importlib.util.spec_from_file_location("prod_gate_for_test", script_path)
    prod_gate = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(prod_gate)

    prod_dir = tmp_path / "docker"
    prod_dir.mkdir()
    config_path = prod_dir / "node.prod.json"
    config = {
        "deployment_mode": "prod",
        "bridge_enabled": False,
        "chain_id": 778888,
        "require_signatures": True,
        "enforce_proposer": True,
        "verify_peer_state_root": True,
        "rpc_api_key_required": True,
        "jwt_enforce_admin": True,
        "require_wallet_file": True,
        "bridge_require_l1_proof": True,
        "require_native_crypto": False,
        "evm_create2_eip1014": True,
        "evm_require_deploy_salt": True,
        "validators_manifest_path": "validators.manifest.example.json",
        "cors_origins": ["https://explorer.example.com"],
    }
    for feature in prod_gate.BLOCKED_FEATURES:
        config[feature] = False
    config_path.write_text(json.dumps(config), encoding="utf-8")

    monkeypatch.setattr(prod_gate, "ROOT", Path(tmp_path))
    errors = prod_gate.check_file("docker/node.prod.json")

    assert any("require_native_crypto" in err for err in errors)


def test_prod_rejects_bridge_dev_adapter():
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.bridge_dev_adapter_enabled = True
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = False
    errs = cfg.validate()
    assert any("BRIDGE_DEV_ADAPTER_ENABLED" in e for e in errs)


def test_prod_missing_rust_bridge_ok_when_bridge_off():
    """bridge_mode=rust + missing bin is not an error while bridge_enabled=false."""
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.bridge_enabled = False
    cfg.bridge_mode = "rust"
    cfg.rust_bridge_path = "bridge/abs_bridge_bin_absent_for_test"
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = False
    errs = cfg.validate()
    assert not any("binary missing" in e for e in errs), errs


def test_prod_missing_rust_bridge_errors_when_bridge_on():
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.bridge_enabled = True
    cfg.bridge_mode = "rust"
    cfg.rust_bridge_path = "bridge/abs_bridge_bin_absent_for_test"
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = False
    errs = cfg.validate()
    assert any("binary missing" in e for e in errs), errs


def test_prod_requires_jwt_secret():
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.bridge_mode = "rust"
    cfg.rust_bridge_path = __file__  # exists for this test only
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = False
    cfg.bridge_oracle_secret = "test-oracle"
    old = os.environ.pop("JWT_SECRET", None)
    try:
        errs = cfg.validate()
        assert any("JWT_SECRET" in e for e in errs)
    finally:
        if old:
            os.environ["JWT_SECRET"] = old


def test_prod_requires_bridge_oracle_secret():
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.bridge_enabled = True
    cfg.bridge_mode = "rust"
    cfg.rust_bridge_path = __file__
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = False
    os.environ["JWT_SECRET"] = "x" * 32
    try:
        errs = cfg.validate()
        assert any("BRIDGE_ORACLE_SECRET" in e for e in errs)
    finally:
        os.environ.pop("JWT_SECRET", None)


def test_prod_rejects_placeholder_and_weak_secrets(monkeypatch):
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.bridge_enabled = True
    cfg.bridge_mode = "rust"
    cfg.rust_bridge_path = __file__
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = True
    cfg.rpc_api_keys = ["your_rpc_key_here"]
    cfg.bridge_oracle_secret = "your_bridge_oracle_hmac_secret"
    monkeypatch.setenv("JWT_SECRET", "your_jwt_secret_here")

    errs = cfg.validate()
    assert any("JWT_SECRET" in e and "placeholder" in e for e in errs)
    assert any("RPC_API_KEYS" in e and "weak" in e for e in errs)
    assert any("BRIDGE_ORACLE_SECRET" in e and "placeholder" in e for e in errs)


def test_prod_rejects_jwt_secret_under_32_bytes(monkeypatch):
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = False
    # 31 bytes, non-placeholder — still too short for HS256.
    monkeypatch.setenv("JWT_SECRET", "a" * 31)
    errs = cfg.validate()
    assert any("JWT_SECRET" in e and "too short" in e for e in errs)
    monkeypatch.setenv("JWT_SECRET", "b" * 32)
    errs = cfg.validate()
    assert not any("JWT_SECRET" in e and "too short" in e for e in errs)


def test_prod_bridge_requires_l1_rpc_and_proof_flag(monkeypatch):
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.bridge_enabled = True
    cfg.bridge_mode = "rust"
    cfg.rust_bridge_path = __file__
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = False
    cfg.bridge_oracle_secret = "x" * 32
    cfg.bridge_require_l1_proof = False
    monkeypatch.setenv("JWT_SECRET", "y" * 32)
    monkeypatch.delenv("ETH_RPC_URL", raising=False)
    monkeypatch.delenv("BSC_RPC_URL", raising=False)
    monkeypatch.delenv("POLYGON_RPC_URL", raising=False)

    errs = cfg.validate()
    assert any("L1 RPC URL" in e for e in errs)
    assert any("BRIDGE_REQUIRE_L1_PROOF" in e for e in errs)

    cfg.bridge_require_l1_proof = True
    monkeypatch.setenv("ETH_RPC_URL", "https://rpc.example.com")
    errs = cfg.validate()
    assert not any("L1 RPC URL" in e for e in errs)
    assert not any("BRIDGE_REQUIRE_L1_PROOF" in e for e in errs)


def test_prod_bridge_forbids_auto_confirm_and_requires_l1_queue_path(monkeypatch):
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.bridge_enabled = True
    cfg.bridge_mode = "rust"
    cfg.rust_bridge_path = __file__
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = False
    cfg.bridge_oracle_secret = "x" * 32
    cfg.bridge_require_l1_proof = True
    cfg.bridge_auto_confirm_sec = 10
    cfg.bridge_l1_queue_path = ""
    monkeypatch.setenv("JWT_SECRET", "y" * 32)
    monkeypatch.setenv("ETH_RPC_URL", "https://rpc.example.com")

    errs = cfg.validate()
    assert any("BRIDGE_AUTO_CONFIRM_SEC" in e for e in errs)
    assert any("BRIDGE_L1_QUEUE_PATH" in e for e in errs)


def test_prod_bridge_l1_rpc_probe_when_enabled(monkeypatch):
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.bridge_enabled = True
    cfg.bridge_mode = "rust"
    cfg.rust_bridge_path = __file__
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = False
    cfg.bridge_oracle_secret = "x" * 32
    cfg.bridge_require_l1_proof = True
    monkeypatch.setenv("JWT_SECRET", "y" * 32)
    monkeypatch.setenv("ETH_RPC_URL", "https://mainnet.infura.io/v3/testkey")
    monkeypatch.setenv("BRIDGE_PROBE_L1_RPC", "true")

    monkeypatch.setattr(
        "bridge.l1_rpc.probe_configured_l1_rpcs",
        lambda timeout=5.0: {"ok": False, "error": "ETH_RPC_URL: timeout"},
    )

    errs = cfg.validate()
    assert any("L1 RPC reachability probe failed" in e for e in errs)


def test_prod_bridge_rejects_placeholder_l1_rpc(monkeypatch):
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.bridge_enabled = True
    cfg.bridge_mode = "rust"
    cfg.rust_bridge_path = __file__
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = False
    cfg.bridge_oracle_secret = "x" * 32
    cfg.bridge_require_l1_proof = True
    monkeypatch.setenv("JWT_SECRET", "y" * 32)
    monkeypatch.setenv("ETH_RPC_URL", "https://rpc.example.com")
    monkeypatch.setenv("BRIDGE_PROBE_L1_RPC", "true")
    monkeypatch.setattr(
        "bridge.health.check_rust_bridge_binary",
        lambda path: {"ok": True, "path": path},
    )

    errs = cfg.validate()
    assert any("placeholder URL" in e for e in errs)


def test_non_dev_public_bind_requires_auth_and_cors():
    cfg = Config()
    cfg.deployment_mode = "staging"
    cfg.http_host = "0.0.0.0"
    cfg.rpc_host = "0.0.0.0"
    cfg.jwt_enforce_admin = False
    cfg.rpc_api_key_required = False
    cfg.cors_origins = ["*"]

    errs = cfg.validate()
    assert any("public HTTP bind" in e for e in errs)
    assert any("public RPC bind" in e for e in errs)
    assert any("wildcard CORS" in e for e in errs)


def test_non_dev_public_bind_allowed_when_protected():
    cfg = Config()
    cfg.deployment_mode = "staging"
    cfg.http_host = "0.0.0.0"
    cfg.rpc_host = "0.0.0.0"
    cfg.jwt_enforce_admin = True
    cfg.rpc_api_key_required = True
    cfg.rpc_api_keys = ["x" * 32]
    cfg.cors_origins = ["https://explorer.example.com"]

    errs = cfg.validate()
    assert not any("public HTTP bind" in e for e in errs)
    assert not any("public RPC bind" in e for e in errs)
    assert not any("wildcard CORS" in e for e in errs)


def test_prod_validate_requires_core_security_flags():
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.require_wallet_file = False
    cfg.require_signatures = False
    cfg.enforce_proposer = False
    cfg.verify_peer_state_root = False
    cfg.jwt_enforce_admin = False
    cfg.rpc_api_key_required = False
    cfg.rate_limit_rpm = 0
    cfg.allow_insecure_public_bind = True
    cfg.chain_id = 778888
    cfg.evm_create2_eip1014 = True
    cfg.evm_require_deploy_salt = True
    cfg.require_native_crypto = False
    errs = cfg.validate()
    assert any("REQUIRE_SIGNATURES" in e for e in errs)
    assert any("ENFORCE_PROPOSER" in e for e in errs)
    assert any("VERIFY_PEER_STATE_ROOT" in e for e in errs)
    assert any("JWT_ENFORCE_ADMIN" in e for e in errs)
    assert any("RPC_API_KEY_REQUIRED" in e for e in errs)
    assert any("RATE_LIMIT_RPM" in e for e in errs)
    assert any("ALLOW_INSECURE_PUBLIC_BIND" in e for e in errs)


def test_prod_apply_env_forces_security_flags(monkeypatch):
    cfg = Config()
    cfg.deployment_mode = "prod"
    monkeypatch.setenv("REQUIRE_SIGNATURES", "false")
    monkeypatch.setenv("ENFORCE_PROPOSER", "false")
    monkeypatch.setenv("VERIFY_PEER_STATE_ROOT", "false")
    monkeypatch.setenv("JWT_ENFORCE_ADMIN", "false")
    monkeypatch.setenv("RPC_API_KEY_REQUIRED", "false")
    monkeypatch.setenv("ALLOW_INSECURE_PUBLIC_BIND", "true")
    monkeypatch.setenv("RATE_LIMIT_RPM", "0")
    cfg.apply_env()
    assert cfg.require_signatures is True
    assert cfg.enforce_proposer is True
    assert cfg.verify_peer_state_root is True
    assert cfg.jwt_enforce_admin is True
    assert cfg.rpc_api_key_required is True
    assert cfg.allow_insecure_public_bind is False
    assert cfg.rate_limit_rpm == 120


def test_static_prod_gate_rejects_insecure_bind_and_zero_rpm(tmp_path, monkeypatch):
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    script_path = os.path.join(root, "scripts", "prod_gate.py")
    spec = importlib.util.spec_from_file_location("prod_gate_for_test2", script_path)
    prod_gate = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(prod_gate)

    prod_dir = tmp_path / "docker"
    prod_dir.mkdir()
    config_path = prod_dir / "node.prod.json"
    config = {
        "deployment_mode": "prod",
        "bridge_enabled": False,
        "chain_id": 778888,
        "require_signatures": True,
        "enforce_proposer": True,
        "verify_peer_state_root": True,
        "state_root_strict_p2p": True,
        "rpc_api_key_required": True,
        "jwt_enforce_admin": True,
        "require_wallet_file": True,
        "bridge_require_l1_proof": True,
        "require_native_crypto": True,
        "evm_create2_eip1014": True,
        "evm_require_deploy_salt": True,
        "validators_manifest_path": "validators.manifest.example.json",
        "cors_origins": ["https://explorer.example.com"],
        "db_engine": "rocksdb",
        "allow_insecure_public_bind": True,
        "rate_limit_rpm": 0,
    }
    for feature in prod_gate.BLOCKED_FEATURES:
        config[feature] = False
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(prod_gate, "ROOT", Path(tmp_path))
    errors = prod_gate.check_file("docker/node.prod.json")
    assert any("allow_insecure_public_bind" in err for err in errors)
    assert any("rate_limit_rpm" in err for err in errors)


def test_prod_example_json_structure():
    root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    path = os.path.join(root, "node.prod.example.json")
    cfg = Config.from_json(path)
    assert cfg.deployment_mode == "prod"
    assert cfg.bridge_mode == "rust"
    assert cfg.jwt_enforce_admin is True
    assert cfg.rpc_api_key_required is True
    assert cfg.bridge_require_l1_proof is True
    assert cfg.require_native_crypto is True
    assert cfg.evm_create2_eip1014 is True
    assert cfg.evm_require_deploy_salt is True
    assert cfg.chain_id == 778888
    assert cfg.feature_mev is False
    assert cfg.feature_ai_agents is False
    assert cfg.feature_ai_validator is False
    assert cfg.validators_manifest_path == "validators.manifest.example.json"


def test_prometheus_alerts_include_rust_bridge_readiness():
    root = Path(__file__).resolve().parents[2]
    alerts = (root / "deploy" / "prometheus" / "alerts.yml").read_text(encoding="utf-8")
    assert "AbsoluteRustBridgeDown" in alerts
    assert "abs_rust_bridge_required == 1 and abs_rust_bridge_ok == 0" in alerts
    assert "AbsoluteL1RpcDown" in alerts
    assert "abs_l1_rpc_required == 1 and abs_l1_rpc_ok == 0" in alerts
    assert "AbsoluteP2PShapeRejectBurst" in alerts
    assert "rate(abs_p2p_shape_rejects_total[5m])" in alerts
    assert "AbsoluteP2PHandshakeRejectBurst" in alerts
    assert "AbsoluteP2PActiveBansHigh" in alerts
    assert "AbsoluteP2PRateLimitBurst" in alerts
    assert "abs_p2p_rate_limit_drops_total" in alerts
    assert "AbsoluteP2PPeerSendFailBurst" in alerts
    assert "abs_p2p_peer_send_fail_total" in alerts
    assert "AbsoluteP2POpsErrorsBurst" in alerts
    assert "abs_p2p_ops_errors" in alerts
    assert "AbsoluteP2PAttestationLocalFailBurst" in alerts
    assert "abs_p2p_attestation_local_fail_total" in alerts
    assert "AbsoluteRocksBlockCacheUnset" in alerts
    assert "abs_rocksdb_block_cache_mb" in alerts
    dash = (root / "deploy" / "grafana" / "dashboard.json").read_text(encoding="utf-8")
    assert "abs_p2p_shape_rejects_total" in dash
    assert "abs_p2p_active_bans" in dash
    assert "abs_p2p_rate_limit_drops_total" in dash
    assert "abs_p2p_peer_send_fail_total" in dash
    assert "abs_p2p_ops_errors" in dash
    assert "mid_session_handshake" in dash
    assert "abs_p2p_attestation_local_fail_total" in dash
    assert "abs_rocksdb_column_families" in dash
    env_ex = (root / ".env.example").read_text(encoding="utf-8")
    assert "P2P_MAX_MESSAGES_PER_SEC" in env_ex
    assert "P2P_BAN_SECONDS" in env_ex
    assert "P2P_HOST" in env_ex
    assert "MESH_MIN_PEERS_BEFORE_MINE" in env_ex
    assert "FOLLOWER_GENESIS_SYNC" in env_ex
    assert "BRIDGE_ENABLED=false" in env_ex


def test_apply_env_secrets_restores_bridge_enabled_after_json_merge(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "node.prod.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"deployment_mode": "prod", "bridge_enabled": False}, f)
        cfg = Config.from_json(path)
        assert cfg.bridge_enabled is False
        monkeypatch.setenv("BRIDGE_ENABLED", "true")
        cfg.apply_env_secrets()
        assert cfg.bridge_enabled is True


def test_apply_env_secrets_restores_rpc_keys_after_json_merge():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "node.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "deployment_mode": "prod",
                    "rpc_api_key_required": True,
                    "chain_id": 778888,
                },
                f,
            )
        cfg = Config.from_json(path)
        assert cfg.rpc_api_keys == []
        os.environ["RPC_API_KEYS"] = "prod-test-key-" + ("K" * 32)
        try:
            cfg.apply_env_secrets()
            assert cfg.rpc_api_keys == ["prod-test-key-" + ("K" * 32)]
        finally:
            os.environ.pop("RPC_API_KEYS", None)
