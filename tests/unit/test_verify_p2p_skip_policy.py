"""verify_p2p_ci fail-closed skip policy."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_p2p_ci.py"


def _load_verify():
    spec = importlib.util.spec_from_file_location("verify_p2p_ci", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_skip_or_fail_without_env(monkeypatch):
    mod = _load_verify()
    monkeypatch.delenv("VERIFY_P2P_ALLOW_SKIP", raising=False)
    assert mod._verify_p2p_skip_or_fail("native wheel missing") == 1


def test_skip_or_fail_with_env(monkeypatch):
    mod = _load_verify()
    monkeypatch.setenv("VERIFY_P2P_ALLOW_SKIP", "1")
    assert mod._verify_p2p_skip_or_fail("native wheel missing") == 0


def test_adversarial_wave_skip_fail_closed(monkeypatch):
    mod = _load_verify()
    monkeypatch.delenv("VERIFY_P2P_ALLOW_SKIP", raising=False)
    assert mod.verify_adversarial("http://127.0.0.1:8080", {"api_wave": 40, "deployment_mode": "dev"}) == 1


def test_adversarial_prod_skip_always(monkeypatch, capsys):
    """Prod blocks testnet/slashing drills — soft-skip without ALLOW_SKIP."""
    mod = _load_verify()
    monkeypatch.delenv("VERIFY_P2P_ALLOW_SKIP", raising=False)
    rc = mod.verify_adversarial(
        "http://127.0.0.1:8080",
        {"api_wave": 61, "deployment_mode": "prod"},
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "SKIP: adversarial checks" in out
    assert "blocked in prod" in out


def test_default_prod_smoke_wallet_relpath_is_posix_canonical():
    mod = _load_verify()
    assert mod._PROD_SMOKE_WALLET_REL == "data/prod_mesh/wallets/validator-1.wallet.json"
    expected = os.path.join(
        mod.ROOT, "data", "prod_mesh", "wallets", "validator-1.wallet.json"
    )
    assert mod._default_prod_smoke_wallet() == expected


def test_prod_smoke_wallet_defaults_to_mesh_file(tmp_path, monkeypatch):
    mod = _load_verify()
    monkeypatch.delenv("PROD_SMOKE_WALLET_PATH", raising=False)
    wallet = tmp_path / "validator-1.wallet.json"
    wallet.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "_default_prod_smoke_wallet", lambda: str(wallet))
    assert mod._prod_smoke_wallet_path() == str(wallet)


def test_prod_smoke_wallet_env_wins(tmp_path, monkeypatch):
    mod = _load_verify()
    env_wallet = tmp_path / "custom.json"
    env_wallet.write_text("{}", encoding="utf-8")
    default = tmp_path / "validator-1.wallet.json"
    default.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("PROD_SMOKE_WALLET_PATH", str(env_wallet))
    monkeypatch.setattr(mod, "_default_prod_smoke_wallet", lambda: str(default))
    assert mod._prod_smoke_wallet_path() == str(env_wallet)


def test_prod_tx_propagation_missing_wallet_is_fail_not_skip(monkeypatch, capsys):
    mod = _load_verify()
    monkeypatch.delenv("PROD_SMOKE_WALLET_PATH", raising=False)
    monkeypatch.delenv("VERIFY_P2P_ALLOW_SKIP", raising=False)
    monkeypatch.setattr(mod, "_prod_smoke_wallet_path", lambda: "")
    monkeypatch.setattr(
        mod, "_default_prod_smoke_wallet", lambda: "/missing/validator-1.wallet.json"
    )
    ok = mod._verify_tx_propagation_multi(
        "http://127.0.0.1:18180",
        ["http://127.0.0.1:18181"],
        {"api_wave": 52, "deployment_mode": "prod"},
    )
    assert ok is False
    out = capsys.readouterr().out
    assert "FAIL: tx propagation" in out
    assert "VERIFY_P2P_ALLOW_SKIP" not in out


def test_multi_node_proof_prod_skip_always(monkeypatch, capsys):
    """Prod blocks /testnet/* — skip without ALLOW_SKIP (same as adversarial)."""
    mod = _load_verify()
    monkeypatch.delenv("VERIFY_P2P_ALLOW_SKIP", raising=False)
    rc = mod.verify_multi_node_proof(
        ["http://127.0.0.1:18180", "http://127.0.0.1:18181"],
        {"api_wave": 61, "deployment_mode": "prod"},
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "SKIP: multi-node proof" in out
    assert "SKIP: adversarial checks" in out
    assert "VERIFY_P2P_ALLOW_SKIP" not in out
