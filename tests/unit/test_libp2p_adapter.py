"""ADR 0018 libp2p dual-stack adapter unit tests."""

from __future__ import annotations

import pytest

from network.transport.errors import TransportCapabilityError
from network.transport.libp2p_adapter import Libp2pTransportAdapter
from network.transport.types import PeerEndpoint
from runtime.config import Config


def test_default_config_libp2p_off() -> None:
    cfg = Config()
    assert cfg.feature_libp2p is False
    assert cfg.feature_long_range is False


def test_adapter_disabled_refuses_dial() -> None:
    ad = Libp2pTransportAdapter(enabled=False)
    with pytest.raises(TransportCapabilityError):
        ad.connect(PeerEndpoint(host="127.0.0.1", port=4001))


def test_adapter_enabled_returns_stub_handle() -> None:
    ad = Libp2pTransportAdapter(enabled=True)
    h = ad.connect(PeerEndpoint(host="127.0.0.1", port=4001))
    assert h["transport"] == "libp2p"
    assert h["connected"] is False
    assert ad.capability_status()["available"] is True


def test_prod_forces_libp2p_off(monkeypatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_MODE", "prod")
    monkeypatch.setenv("FEATURE_LIBP2P", "true")
    monkeypatch.setenv("FEATURE_LONG_RANGE", "true")
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.apply_env()
    assert cfg.feature_libp2p is False
    assert cfg.feature_long_range is False
