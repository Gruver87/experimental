"""Wave F: input validators fail-closed (no identity sanitize stub)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_http_source_refuses_identity_sanitize_stub():
    root = Path(__file__).resolve().parents[2]
    src = (root / "api" / "http.py").read_text(encoding="utf-8")
    assert "def sanitize_input(x): return x" not in src
    assert "require_input_validators" in src
    assert "input validators not available" in src


def test_require_input_validators_ok_when_present():
    from api import http as http_mod

    assert http_mod._INPUT_VALIDATORS_AVAILABLE is True
    http_mod.require_input_validators(SimpleNamespace(deployment_mode="prod"))
    http_mod.require_input_validators(SimpleNamespace(deployment_mode="dev"))


def test_require_input_validators_prod_raises_when_missing(monkeypatch):
    from api import http as http_mod

    monkeypatch.setattr(http_mod, "_INPUT_VALIDATORS_AVAILABLE", False)
    monkeypatch.setattr(http_mod, "sanitize_input", None)
    with pytest.raises(RuntimeError, match="input validators required"):
        http_mod.require_input_validators(SimpleNamespace(deployment_mode="prod"))


def test_require_input_validators_dev_warns_when_missing(monkeypatch, caplog):
    from api import http as http_mod
    import logging

    monkeypatch.setattr(http_mod, "_INPUT_VALIDATORS_AVAILABLE", False)
    monkeypatch.setattr(http_mod, "sanitize_input", None)
    with caplog.at_level(logging.WARNING):
        http_mod.require_input_validators(SimpleNamespace(deployment_mode="dev"))
    assert any("input validators unavailable" in r.message for r in caplog.records)


def test_alerts_yml_has_demote_and_under_mesh():
    root = Path(__file__).resolve().parents[2]
    alerts = (root / "deploy" / "prometheus" / "alerts.yml").read_text(encoding="utf-8")
    assert "AbsoluteMempoolStoreDemoted" in alerts
    assert "AbsoluteMempoolStoreDemoteBurst" in alerts
    assert "AbsoluteP2PUnderMesh" in alerts
    assert "abs_mempool_store_demoted" in alerts
    assert "abs_p2p_under_mesh" in alerts


def test_middleware_validators_module_importable():
    # Keep Wave F honest: package must exist for real nodes.
    mod = importlib.import_module("middleware.validators")
    assert callable(mod.sanitize_input)
    assert "middleware.validators" in sys.modules
