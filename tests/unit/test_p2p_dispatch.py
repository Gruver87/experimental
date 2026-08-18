#!/usr/bin/env python3
"""Unit tests for P2PDispatcher / Handler Registry (Step D)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from network.p2p_dispatch import (
    DispatchOutcome,
    HandlerRegistry,
    P2PDispatcher,
    TipSafetyEvidenceBridge,
    build_default_dispatcher,
)
from network.p2p_dispatch.constants import (
    DISPATCHABLE_TYPES,
    MSG_MEMPOOL,
    MSG_NEW_BLOCK,
    MSG_PING,
    MSG_PONG,
    MSG_STATE_ROOT_REQUEST,
    MSG_STATE_ROOT_RESPONSE,
    MSG_STATUS,
)


class _FakePeer:
    def __init__(self, peer_id: str = "peer-1") -> None:
        self.peer_id = peer_id
        self.host = "127.0.0.1"
        self.port = 1
        self.listen_port = 1
        self.height = 0
        self.head = ""
        self.sent: List[tuple] = []

    async def send(self, msg_type: str, data: Any = None) -> bool:
        self.sent.append((msg_type, data))
        return True


class _FakeHost:
    def __init__(self) -> None:
        self.config = MagicMock()
        self.config.p2p_discovery_allow_private = False
        self.config.p2p_peers_solicit_only = True
        self.config.p2p_height_cap_clear_head = True
        self.config.p2p_status_head_requires_height = True
        self.blockchain = MagicMock()
        self.blockchain.get_height = MagicMock(return_value=10)
        self.blockchain.get_block = MagicMock(return_value={"height": 5})
        self.peers: Dict[str, Any] = {}
        self.strikes: List[str] = []
        self.removed: List[str] = []
        self.counters: Dict[str, int] = {}
        self.new_block_calls: List[Any] = []

    def head(self) -> Optional[str]:
        return "aa" * 32

    def strike_peer(self, peer: Any, reason: str) -> bool:
        self.strikes.append(str(reason))
        return False

    def remove_peer(self, peer_id: str, peer: Any = None) -> None:
        self.removed.append(str(peer_id))

    def bump_counter(self, name: str, delta: int = 1) -> None:
        self.counters[name] = int(self.counters.get(name, 0)) + int(delta)

    async def handle_new_block(self, peer: Any, data: Any) -> None:
        self.new_block_calls.append(data)

    async def handle_get_blocks(self, peer: Any, data: Any) -> None:
        return None

    async def handle_new_tx(self, peer: Any, data: Any) -> None:
        return None

    async def handle_get_mempool(self, peer: Any) -> None:
        return None

    async def handle_attestation(self, peer: Any, data: Any) -> None:
        return None

    async def handle_validator_register(self, peer: Any, data: Any) -> None:
        return None

    async def handle_cross_shard_tx(self, peer: Any, data: Any) -> None:
        return None

    async def handle_cross_shard_ack(self, peer: Any, data: Any) -> None:
        return None

    async def handle_shard_migration(self, peer: Any, data: Any) -> None:
        return None

    def get_block_future_refuse_reason(self, height: int) -> str:
        return ""

    def cap_claimed_peer_height(self, height: int) -> tuple:
        return int(height), False

    def status_head_height_refuse_reason(self, head_hash: str, height: int) -> str:
        return ""

    def ingest_discovered_peers(self, peer: Any, data: Any) -> None:
        return None

    def state_root_response_for_height(self, height: int) -> Any:
        return {"height": height, "state_root": "00" * 32, "head_hash": "aa" * 32}


def test_constants_parity_with_p2p_node() -> None:
    from network import p2p_node as pn
    from network.p2p_dispatch import constants as c

    assert c.MSG_PING == pn.MSG_PING
    assert c.MSG_NEW_BLOCK == pn.MSG_NEW_BLOCK
    assert c.MSG_STATUS == pn.MSG_STATUS
    assert c.MSG_MEMPOOL == pn.MSG_MEMPOOL
    assert DISPATCHABLE_TYPES <= pn.ALLOWED_WIRE_TYPES


def test_registry_register_and_lookup() -> None:
    reg = HandlerRegistry()

    async def _h(host, peer, data):
        return None

    reg.register("ping", _h)
    assert reg.get("ping") is _h
    assert "ping" in reg.registered_types()
    assert reg.unregister("ping") is True
    assert reg.get("ping") is None


def test_registry_rejects_empty_type() -> None:
    reg = HandlerRegistry()
    with pytest.raises(ValueError):
        reg.register("", lambda h, p, d: None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_dispatch_ping_sends_pong() -> None:
    disp = build_default_dispatcher()
    host = _FakeHost()
    peer = _FakePeer()
    out = await disp.dispatch(host, peer, MSG_PING, None)
    assert out is DispatchOutcome.HANDLED
    assert peer.sent and peer.sent[0][0] == MSG_PONG
    assert disp.status()["dispatch_total"] == 1


@pytest.mark.asyncio
async def test_dispatch_unhandled() -> None:
    disp = P2PDispatcher(HandlerRegistry())
    host = _FakeHost()
    peer = _FakePeer()
    out = await disp.dispatch(host, peer, "not_registered", {})
    assert out is DispatchOutcome.UNHANDLED


@pytest.mark.asyncio
async def test_dispatch_unsolicited_mempool_strikes() -> None:
    disp = build_default_dispatcher()
    host = _FakeHost()
    peer = _FakePeer()
    out = await disp.dispatch(host, peer, MSG_MEMPOOL, [])
    assert out is DispatchOutcome.HANDLED
    assert "unsolicited_mempool" in host.strikes
    assert host.counters.get("unsolicited_mempool_rejects_total") == 1


@pytest.mark.asyncio
async def test_dispatch_new_block_calls_host() -> None:
    disp = build_default_dispatcher()
    host = _FakeHost()
    peer = _FakePeer()
    payload = {"height": 11, "hash": "bb" * 32, "parent_hash": "aa" * 32}
    out = await disp.dispatch(host, peer, MSG_NEW_BLOCK, payload)
    assert out is DispatchOutcome.HANDLED
    assert host.new_block_calls == [payload]


@pytest.mark.asyncio
async def test_dispatch_new_block_tip_enforce_refuse() -> None:
    shadow = MagicMock()
    shadow.enabled = True
    shadow.enforce = True
    shadow.tip_state = None

    # Force evaluate to reject via broken mapping under enforce.
    bridge = TipSafetyEvidenceBridge(shadow_provider=lambda: shadow)
    disp = build_default_dispatcher(tip_evidence=bridge)
    host = _FakeHost()
    peer = _FakePeer()
    # Missing hash → tip_evidence_error / validation → enforce refuse
    out = await disp.dispatch(host, peer, MSG_NEW_BLOCK, {"height": 99})
    assert out is DispatchOutcome.REFUSED
    assert host.new_block_calls == []
    assert host.counters.get("dispatch_tip_evidence_refuse_total") == 1
    assert host.strikes


@pytest.mark.asyncio
async def test_custom_handler_registration() -> None:
    disp = build_default_dispatcher()
    seen = []

    async def _custom(host, peer, data):
        seen.append(data)

    disp.register("custom_ext", _custom)
    host = _FakeHost()
    peer = _FakePeer()
    out = await disp.dispatch(host, peer, "custom_ext", {"x": 1})
    assert out is DispatchOutcome.HANDLED
    assert seen == [{"x": 1}]


def test_tip_evidence_shadow_provider_exception_logs_unbound(caplog) -> None:
    def _boom():
        raise RuntimeError("shadow down")

    bridge = TipSafetyEvidenceBridge(shadow_provider=_boom)
    with caplog.at_level(logging.WARNING, logger="P2P.TipEvidence"):
        d = bridge.evaluate_block_candidate({"height": 1, "hash": "11" * 32}, MagicMock())
    assert d.ok is True
    assert d.reason_code == "tip_evidence_unbound"
    assert "tip-safety shadow provider failed" in caplog.text


def test_tip_evidence_disabled_allows() -> None:
    shadow = MagicMock()
    shadow.enabled = False
    shadow.enforce = False
    bridge = TipSafetyEvidenceBridge(shadow_provider=lambda: shadow)
    d = bridge.evaluate_block_candidate({"height": 1, "hash": "11" * 32}, MagicMock())
    assert d.ok is True
    assert d.enforce_refuse is False


def test_tip_evidence_own_forge_echo_allows_under_enforce() -> None:
    from consensus.tip_safety.shadow import TipSafetyShadowObserver

    class _Chain:
        def get_height(self):
            return 9583

        def get_block(self, height: int):
            return {
                "height": 9583,
                "hash": "aa" * 32,
                "parent_hash": "bb" * 32,
            }

    shadow = TipSafetyShadowObserver(enabled=True, enforce=True)
    shadow.note_local_forge(9585)
    bridge = TipSafetyEvidenceBridge(shadow_provider=lambda: shadow)
    d = bridge.evaluate_block_candidate(
        {
            "height": 9585,
            "hash": "cc" * 32,
            "parent_hash": "dd" * 32,
        },
        _Chain(),
    )
    assert d.ok is True
    assert d.enforce_refuse is False
    assert d.reason_code == "own_forge_echo"


@pytest.mark.asyncio
async def test_dispatch_new_block_own_forge_echo_not_refused() -> None:
    from consensus.tip_safety.shadow import TipSafetyShadowObserver

    class _Chain:
        def get_height(self):
            return 9583

        def get_block(self, height: int):
            return {
                "height": 9583,
                "hash": "aa" * 32,
                "parent_hash": "bb" * 32,
            }

    shadow = TipSafetyShadowObserver(enabled=True, enforce=True)
    shadow.note_local_forge(9585)
    bridge = TipSafetyEvidenceBridge(shadow_provider=lambda: shadow)
    disp = build_default_dispatcher(tip_evidence=bridge)
    host = _FakeHost()
    host.blockchain = _Chain()
    peer = _FakePeer()
    payload = {"height": 9585, "hash": "cc" * 32, "parent_hash": "dd" * 32}
    out = await disp.dispatch(host, peer, MSG_NEW_BLOCK, payload)
    assert out is DispatchOutcome.HANDLED
    assert host.new_block_calls == [payload]
    assert "tip_unknown_parent" not in host.strikes


class _LagHost(_FakeHost):
    """Builder returns None above tip; height<=0 means local tip (honest lag)."""

    tip = 5

    def state_root_response_for_height(self, height: int) -> Any:
        h = int(height)
        if h <= 0:
            h = self.tip
        if h > self.tip:
            return None
        return {
            "height": h,
            "state_root": "00" * 32,
            "head_hash": "aa" * 32,
        }


@pytest.mark.asyncio
async def test_state_root_request_ahead_answers_local_tip() -> None:
    disp = build_default_dispatcher()
    host = _LagHost()
    peer = _FakePeer()
    out = await disp.dispatch(host, peer, MSG_STATE_ROOT_REQUEST, {"height": 9})
    assert out is DispatchOutcome.HANDLED
    assert host.counters.get("state_root_outbound_refuse_total") == 1
    assert host.counters.get("state_root_outbound_lag_total") == 1
    assert peer.sent and peer.sent[0][0] == MSG_STATE_ROOT_RESPONSE
    assert peer.sent[0][1]["height"] == 5
    assert host.strikes == []


@pytest.mark.asyncio
async def test_state_root_request_at_tip_is_exact() -> None:
    disp = build_default_dispatcher()
    host = _LagHost()
    peer = _FakePeer()
    out = await disp.dispatch(host, peer, MSG_STATE_ROOT_REQUEST, {"height": 5})
    assert out is DispatchOutcome.HANDLED
    assert host.counters.get("state_root_outbound_lag_total") in (None, 0)
    assert peer.sent[0][1]["height"] == 5


@pytest.mark.asyncio
async def test_state_root_missing_historical_does_not_inflate_tip() -> None:
    class _MissingHist(_LagHost):
        def state_root_response_for_height(self, height: int) -> Any:
            h = int(height)
            if h <= 0:
                h = self.tip
            if h == 3 or h > self.tip:
                return None
            return {
                "height": h,
                "state_root": "00" * 32,
                "head_hash": "aa" * 32,
            }

    disp = build_default_dispatcher()
    host = _MissingHist()
    peer = _FakePeer()
    out = await disp.dispatch(host, peer, MSG_STATE_ROOT_REQUEST, {"height": 3})
    assert out is DispatchOutcome.HANDLED
    assert peer.sent == []
    assert host.counters.get("state_root_outbound_refuse_total") == 1
    assert host.counters.get("state_root_outbound_lag_total") in (None, 0)


def test_node_wires_dispatcher() -> None:
    from network.p2p_node import P2PNode
    from runtime.config import Config

    cfg = Config()
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.p2p_native_transport = False
    chain = MagicMock()
    chain.height = 0
    chain.get_height = MagicMock(return_value=0)
    chain.get_tip_hash = MagicMock(return_value="")
    node = P2PNode(cfg, chain, MagicMock())
    assert isinstance(node.dispatcher, P2PDispatcher)
    st = node.get_p2p_security_status()
    assert st.get("dispatch_boundary") is True
    assert "ping" in st.get("dispatch_registered_types", [])
