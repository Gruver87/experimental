#!/usr/bin/env python3
"""v1.3.114: prod-mandatory native P2P transport + skip dual shape re-validate."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.p2p_node import P2PNode
from runtime.config import Config


def test_needles_v13114():
    cfg_py = (ROOT / "runtime" / "config.py").read_text(encoding="utf-8")
    assert "p2p_native_transport" in cfg_py
    assert 'prod mode requires p2p_native_transport=true' in cfg_py
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "must_native_tx" in p2p
    assert "native_shape_revalidate" in p2p
    assert "check_ingress_shape_gates" in (
        ROOT / "native" / "abs_native" / "src" / "p2p_transport.rs"
    ).read_text(encoding="utf-8") or "skip dual" in p2p
    assert "native read path already ran check_ingress_shape_gates" in p2p
    prod_gate = (ROOT / "scripts" / "prod_gate.py").read_text(encoding="utf-8")
    assert '"p2p_native_transport"' in prod_gate
    notes = (ROOT / "RELEASE_NOTES_v1.3.114.md").read_text(encoding="utf-8")
    assert "1.3.114-industrial" in notes
    # Live Config().node_version advances with later waves; pin notes not config.
    assert "abs_p2p_native_shape_revalidate" in (
        ROOT / "observability" / "metrics.py"
    ).read_text(encoding="utf-8")
    prod = (ROOT / "docker" / "node.prod.json").read_text(encoding="utf-8")
    assert '"p2p_native_transport"' in prod and "true" in prod
    cm = (ROOT / "deploy" / "k8s" / "configmap.yaml").read_text(encoding="utf-8")
    assert '"p2p_native_transport": true' in cm
    smoke = (ROOT / "runtime" / "prod_smoke_profile.py").read_text(encoding="utf-8")
    assert '"p2p_native_transport": True' in smoke or "p2p_native_transport\": True" in smoke
    assert "P2P_NATIVE_TRANSPORT" in smoke
    http_py = (ROOT / "api" / "http.py").read_text(encoding="utf-8")
    assert 'getattr(p2p, "_native_listener", None) is not None' in http_py
    assert "native TCP+TLS uses ``_native_listener``" in http_py


def test_prod_config_defaults_native_transport():
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.chain_id = 778888
    cfg.require_native_crypto = True
    cfg.p2p_native_transport = False
    cfg.apply_env()
    # apply_env forces True for prod when env unset
    assert cfg.p2p_native_transport is True


def test_prod_config_rejects_disabled_native_transport():
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.chain_id = 778888
    cfg.require_native_crypto = True
    cfg.p2p_native_transport = False
    cfg.evm_create2_eip1014 = True
    cfg.evm_require_deploy_salt = True
    # Bypass apply_env prod default — validate raw false.
    errors = cfg.validate()
    assert any("p2p_native_transport" in e for e in errors)


def test_p2p_node_skips_shape_revalidate_when_native():
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.p2p_native_transport = True
    cfg.p2p_tls_enabled = False
    node = P2PNode(cfg, MagicMock(), MagicMock())
    status = node.get_p2p_security_status()
    if status.get("native_p2p_transport"):
        assert status.get("native_shape_revalidate") is False
    else:
        pytest.skip("abs_native transport not available in this environment")


def test_p2p_node_asyncio_still_revalidates():
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.p2p_native_transport = False
    cfg.p2p_tls_enabled = False
    node = P2PNode(cfg, MagicMock(), MagicMock())
    status = node.get_p2p_security_status()
    assert status.get("native_p2p_transport") is False
    assert status.get("native_shape_revalidate") is True
