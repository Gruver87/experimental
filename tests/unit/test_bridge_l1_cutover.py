#!/usr/bin/env python3
"""Bridge L1 cutover gate tests."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from bridge_l1_cutover import is_placeholder_rpc_url, run_cutover_gate
from bridge_l1_preflight import run_preflight


def test_is_placeholder_rpc_url():
    assert is_placeholder_rpc_url("https://rpc.example.com")
    assert is_placeholder_rpc_url("https://ваш-ethereum-rpc")
    assert not is_placeholder_rpc_url("https://mainnet.infura.io/v3/abc123")


def test_preflight_bridge_disabled_warns_only():
    errors, warnings = run_preflight(config_path="node.prod.mainnet-v1.example.json")
    assert errors == []
    assert any("bridge_disabled" in w for w in warnings)


def test_cutover_gate_fails_on_placeholder_rpc(monkeypatch):
    monkeypatch.setenv("ETH_RPC_URL", "https://rpc.example.com")
    monkeypatch.setenv("BRIDGE_REQUIRE_L1_EVENT", "true")
    monkeypatch.setenv("RUST_BRIDGE_PATH", __file__)
    with patch("bridge.health.check_rust_bridge_binary", return_value={"ok": True}):
        errors, warnings, meta = run_cutover_gate(probe_l1=False)
    assert errors == []
    assert any("placeholder" in w for w in warnings)
    assert meta["ok"] is True


def test_cutover_gate_static_ok_with_valid_rpc(monkeypatch):
    monkeypatch.setenv("ETH_RPC_URL", "https://mainnet.infura.io/v3/testkey")
    monkeypatch.setenv("BRIDGE_L1_LOCK_CONTRACT", "0x" + "11" * 20)
    monkeypatch.setenv("BRIDGE_L1_MINT_CONTRACT", "0x" + "22" * 20)
    monkeypatch.setenv("BRIDGE_REQUIRE_L1_EVENT", "true")
    monkeypatch.setenv("RUST_BRIDGE_PATH", __file__)
    monkeypatch.delenv("BRIDGE_ALLOW_SYNTHETIC", raising=False)
    with patch("bridge.health.check_rust_bridge_binary", return_value={"ok": True}):
        errors, _warnings, meta = run_cutover_gate(probe_l1=False)
    assert not any("rust_bridge" in e for e in errors), errors
    assert meta["ok"] is True


def test_cutover_probe_l1_fails_on_empty_contract_code(monkeypatch):
    monkeypatch.setenv("ETH_RPC_URL", "https://mainnet.infura.io/v3/testkey")
    monkeypatch.setenv("BRIDGE_L1_LOCK_CONTRACT", "0x" + "11" * 20)
    monkeypatch.setenv("BRIDGE_L1_MINT_CONTRACT", "0x" + "22" * 20)
    monkeypatch.setenv("BRIDGE_L1_CHAIN", "ethereum")
    monkeypatch.setenv("RUST_BRIDGE_PATH", __file__)
    # Skip real RPC probe; focus on contract code verification.
    import runtime.config as runtime_config

    monkeypatch.setattr(runtime_config.Config, "validate", lambda self: [])
    import bridge.health as health

    monkeypatch.setattr(health, "check_l1_rpc_health", lambda *a, **k: {"required": True, "ok": True})
    monkeypatch.setattr(health, "check_rust_bridge_binary", lambda *a, **k: {"ok": True})
    # Simulate eth_getCode returning empty.
    import bridge.l1_rpc as l1_rpc

    monkeypatch.setattr(l1_rpc, "get_contract_code", lambda *a, **k: "0x")
    errors, _warnings, _meta = run_cutover_gate(probe_l1=True)
    assert any("empty bytecode" in e for e in errors)


def test_probe_l1_rpc_only_warns_on_placeholder_contracts(monkeypatch):
    monkeypatch.setenv("ETH_RPC_URL", "https://mainnet.infura.io/v3/testkey")
    import runtime.config as runtime_config

    monkeypatch.setattr(runtime_config.Config, "validate", lambda self: [])
    import bridge.health as health

    monkeypatch.setattr(health, "check_l1_rpc_health", lambda *a, **k: {"required": True, "ok": True})
    monkeypatch.setattr(health, "check_rust_bridge_binary", lambda *a, **k: {"ok": True})
    errors, warnings, _meta = run_cutover_gate(probe_l1_rpc_only=True)
    assert not any("BRIDGE_L1_LOCK_CONTRACT" in e for e in errors)
    assert any("BRIDGE_L1_LOCK_CONTRACT" in w for w in warnings)


def test_resolve_live_base_url_prefers_docker_prod_without_bridge():
    from bridge_l1_cutover import resolve_live_base_url

    payload = json.dumps(
        {
            "deployment_mode": "prod",
            "chain_id": 778888,
            "bridge_enabled": False,
        }
    ).encode()

    class _Resp:
        def read(self):
            return payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("urllib.request.urlopen", return_value=_Resp()):
        assert resolve_live_base_url() == "http://127.0.0.1:18080"


def test_cutover_live_bridge_disabled_clear_error(monkeypatch):
    monkeypatch.setenv("ETH_RPC_URL", "https://mainnet.infura.io/v3/testkey")
    with patch("bridge.health.check_rust_bridge_binary", return_value={"ok": True}), patch(
        "bridge_l1_cutover._fetch_status",
        return_value={"deployment_mode": "prod", "chain_id": 778888, "bridge_enabled": False},
    ):
        errors, _warnings, meta = run_cutover_gate(
            live=True,
            base_url="http://127.0.0.1:18080",
            probe_l1=False,
        )
    assert any("bridge_enabled=false" in e for e in errors)
    assert not any("oracle" in e.lower() for e in errors)
    assert meta["base_url"] == "http://127.0.0.1:18080"


def test_cutover_live_uses_prod_smoke(monkeypatch):
    monkeypatch.setenv("ETH_RPC_URL", "https://mainnet.infura.io/v3/testkey")
    monkeypatch.setenv("BRIDGE_REQUIRE_L1_EVENT", "true")
    monkeypatch.setenv("BRIDGE_L1_LOCK_CONTRACT", "0x" + "11" * 20)
    monkeypatch.setenv("BRIDGE_L1_MINT_CONTRACT", "0x" + "22" * 20)
    monkeypatch.delenv("BRIDGE_ALLOW_SYNTHETIC", raising=False)
    monkeypatch.setenv("RUST_BRIDGE_PATH", __file__)
    fake_report = {
        "ok": True,
        "errors": [],
        "checks": {"bridge_rust_mode": True},
    }
    run_ok = type("R", (), {"returncode": 0, "stdout": "OK", "stderr": ""})()
    with patch("bridge.health.check_rust_bridge_binary", return_value={"ok": True}), patch(
        "bridge_l1_cutover._fetch_status",
        return_value={"deployment_mode": "prod", "chain_id": 778888, "bridge_enabled": True},
    ), patch(
        "prod_smoke.run_prod_smoke", return_value=fake_report
    ), patch(
        "subprocess.run",
        side_effect=[run_ok, run_ok],
    ):
        errors, _warnings, meta = run_cutover_gate(
            live=True,
            base_url="http://127.0.0.1:18080",
            probe_l1=False,
        )
    assert errors == [], errors
    assert meta["base_url"] == "http://127.0.0.1:18080"
