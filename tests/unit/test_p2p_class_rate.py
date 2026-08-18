#!/usr/bin/env python3
"""Per-peer P2P class quotas: attest / tx / block announce cannot share one window."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.p2p_node import (
    MSG_ATTESTATION,
    MSG_NEW_BLOCK,
    MSG_NEW_TX,
    MSG_PING,
    P2PNode,
    RATE_LIMIT_EXEMPT_TYPES,
)
from runtime.config import Config


def _node(**caps) -> P2PNode:
    cfg = Config()
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.p2p_max_messages_per_sec = 500
    cfg.p2p_exempt_messages_per_sec = 2000
    cfg.p2p_attest_messages_per_sec = 2
    cfg.p2p_tx_messages_per_sec = 2
    cfg.p2p_block_announce_messages_per_sec = 2
    for key, val in caps.items():
        setattr(cfg, key, val)
    return P2PNode(cfg, None, None)


def test_attestation_class_does_not_starve_tx():
    node = _node()
    assert node._rate_limit_ok("p1", MSG_ATTESTATION) is True
    assert node._rate_limit_ok("p1", MSG_ATTESTATION) is True
    assert node._rate_limit_ok("p1", MSG_ATTESTATION) is False
    assert node._rate_limit_ok("p1", MSG_NEW_TX) is True
    assert node._rate_limit_ok("p1", MSG_NEW_TX) is True
    assert node._rate_limit_ok("p1", MSG_NEW_TX) is False


def test_tx_class_does_not_starve_attestation():
    node = _node()
    assert node._rate_limit_ok("p1", MSG_NEW_TX) is True
    assert node._rate_limit_ok("p1", MSG_NEW_TX) is True
    assert node._rate_limit_ok("p1", MSG_NEW_TX) is False
    assert node._rate_limit_ok("p1", MSG_ATTESTATION) is True


def test_block_announce_class_on_exempt_type():
    node = _node()
    assert MSG_NEW_BLOCK in RATE_LIMIT_EXEMPT_TYPES
    assert node._rate_limit_ok("p1", MSG_NEW_BLOCK) is True
    assert node._rate_limit_ok("p1", MSG_NEW_BLOCK) is True
    assert node._rate_limit_ok("p1", MSG_NEW_BLOCK) is False
    assert node._rate_limit_ok("p1", MSG_PING) is True


def test_class_cap_zero_disables_quota():
    node = _node(
        p2p_attest_messages_per_sec=0,
        p2p_max_messages_per_sec=500,
    )
    for _ in range(5):
        assert node._rate_limit_ok("p1", MSG_ATTESTATION) is True


def test_class_windows_are_per_peer():
    node = _node()
    assert node._rate_limit_ok("p1", MSG_ATTESTATION) is True
    assert node._rate_limit_ok("p1", MSG_ATTESTATION) is True
    assert node._rate_limit_ok("p1", MSG_ATTESTATION) is False
    assert node._rate_limit_ok("p2", MSG_ATTESTATION) is True


def test_security_status_exposes_class_caps():
    node = _node()
    st = node.get_p2p_security_status()
    assert st.get("attest_messages_per_sec") == 2
    assert st.get("tx_messages_per_sec") == 2
    assert st.get("block_announce_messages_per_sec") == 2
    assert "rate_limit_class_drops" in st


def test_needles():
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    assert "def _class_rate_ok" in p2p
    assert "rate_limit_class_exceeded" in p2p
    cfg = (ROOT / "runtime" / "config.py").read_text(encoding="utf-8")
    assert "p2p_attest_messages_per_sec" in cfg
    reject = (ROOT / "network" / "transport" / "reject.py").read_text(encoding="utf-8")
    assert "rate_limit_class_exceeded" in reject
