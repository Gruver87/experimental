#!/usr/bin/env python3
"""Unit tests for tip-safety shadow observer (stage 2)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consensus.tip_safety.errors import TipValidationError
from consensus.tip_safety.shadow import (
    TipSafetyShadowObserver,
    block_ref_from_mapping,
    tip_state_from_chain,
)
from consensus.tip_safety.types import ApplyOutcome, BlockRef
from network.p2p_node import P2PNode
from runtime.config import Config


def _h(n: int) -> str:
    return f"{n:064x}"


def _block_dict(height: int, *, n: int | None = None) -> Dict[str, Any]:
    digest = _h(n if n is not None else height)
    parent = "0" * 64 if height == 0 else _h(height - 1)
    return {
        "height": height,
        "hash": digest,
        "parent_hash": parent,
        "transactions": [],
    }


class _FakeChain:
    GENESIS_HASH = "0" * 64

    def __init__(self, height: int = 0) -> None:
        self._height = height
        # Genesis block hash must differ from the pre-genesis GENESIS_HASH sentinel.
        self._blocks: Dict[int, Dict[str, Any]] = {
            0: _block_dict(0, n=0xA1),
        }
        for i in range(1, height + 1):
            prev = self._blocks[i - 1]["hash"]
            blk = _block_dict(i, n=0xA1 + i)
            blk["parent_hash"] = prev
            self._blocks[i] = blk

    def get_height(self) -> int:
        return self._height

    def get_block(self, height: int) -> Optional[Dict[str, Any]]:
        return self._blocks.get(height)

    def get_last_block(self) -> Optional[Dict[str, Any]]:
        return self._blocks.get(self._height)

    def import_block(self, data: Dict[str, Any]) -> bool:
        h = int(data["height"])
        if h != self._height + 1:
            return False
        if data.get("parent_hash") != self._blocks[self._height]["hash"]:
            return False
        self._blocks[h] = dict(data)
        self._height = h
        return True


def test_block_ref_from_mapping_ok() -> None:
    ref = block_ref_from_mapping(_block_dict(1))
    assert ref.height == 1
    assert ref.parent_hash == _h(0)


def test_block_ref_from_mapping_rejects_junk() -> None:
    with pytest.raises(TipValidationError):
        block_ref_from_mapping({"height": "x", "hash": _h(1)})


def test_tip_state_from_chain_genesis() -> None:
    state = tip_state_from_chain(_FakeChain(0))
    assert state.head.height == 0
    # Must use block #0 hash, not the pre-genesis GENESIS_HASH sentinel.
    assert state.head.block_hash == _h(0xA1)
    assert state.head.block_hash != _FakeChain.GENESIS_HASH


def test_tip_state_from_chain_empty() -> None:
    class _Empty:
        GENESIS_HASH = "0" * 64

        def get_height(self) -> int:
            return 0

        def get_last_block(self):
            return None

        def get_block(self, _h):
            return None

    state = tip_state_from_chain(_Empty())
    assert state.head.block_hash == _Empty.GENESIS_HASH


def test_disabled_observer_is_noop() -> None:
    obs = TipSafetyShadowObserver(enabled=False)
    chain = _FakeChain(1)
    cand = dict(chain.get_block(1) or {})
    cand["height"] = 2
    cand["parent_hash"] = chain.get_block(1)["hash"]
    cand["hash"] = _h(0xA3)
    assert obs.observe_before_import(cand, chain) is None
    obs.note_import_result(True, chain)
    st = obs.status()
    assert st["tip_safety_shadow_enabled"] is False
    assert st["tip_safety_shadow_observe_total"] == 0


def test_shadow_observe_accept_extend() -> None:
    obs = TipSafetyShadowObserver(enabled=True)
    chain = _FakeChain(1)
    assert obs.sync_from_chain(chain) is True
    tip = chain.get_last_block()
    cand = {
        "height": 2,
        "hash": _h(0xA3),
        "parent_hash": tip["hash"],
        "transactions": [],
    }
    decision = obs.observe_before_import(cand, chain)
    assert decision is not None
    assert decision.outcome == ApplyOutcome.ACCEPT_EXTEND
    assert obs.accept_total == 1


def test_shadow_observe_reject_gap_does_not_raise() -> None:
    obs = TipSafetyShadowObserver(enabled=True)
    chain = _FakeChain(1)
    obs.sync_from_chain(chain)
    decision = obs.observe_before_import(_block_dict(50), chain)
    assert decision is not None
    assert decision.outcome == ApplyOutcome.REJECT
    assert decision.reason_code == "tip_unknown_parent"
    assert obs.reject_total == 1
    assert obs.reject_by_code.get("tip_unknown_parent") == 1


def test_shadow_bad_hash_increments_observe_errors() -> None:
    obs = TipSafetyShadowObserver(enabled=True)
    chain = _FakeChain(0)
    obs.sync_from_chain(chain)
    decision = obs.observe_before_import(
        {"height": 1, "hash": "not-hex", "parent_hash": _h(0xA1)},
        chain,
    )
    assert decision is None
    assert obs.observe_errors >= 1


def test_diverge_policy_reject_import_ok() -> None:
    obs = TipSafetyShadowObserver(enabled=True)
    chain = _FakeChain(1)
    obs.sync_from_chain(chain)
    obs.observe_before_import(_block_dict(50), chain)
    obs.note_import_result(True, chain)
    assert obs.diverge_policy_reject_import_ok == 1


def test_diverge_policy_accept_import_fail() -> None:
    obs = TipSafetyShadowObserver(enabled=True)
    chain = _FakeChain(1)
    obs.sync_from_chain(chain)
    tip = chain.get_last_block()
    cand = {
        "height": 2,
        "hash": _h(0xA3),
        "parent_hash": tip["hash"],
        "transactions": [],
    }
    obs.observe_before_import(cand, chain)
    obs.note_import_result(False, chain)
    assert obs.diverge_policy_accept_import_fail == 1


def test_p2p_import_block_shadow_does_not_change_result() -> None:
    cfg = Config()
    cfg.p2p_native_transport = False
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.bootstrap_peers = []
    cfg.tip_safety_shadow = True
    cfg.tip_safety_enforce = False
    chain = _FakeChain(1)
    mp = MagicMock()
    node = P2PNode(cfg, chain, mp)
    node.tip_safety_shadow = TipSafetyShadowObserver(enabled=True, enforce=False)
    node.tip_safety_shadow.sync_from_chain(chain)

    tip = chain.get_last_block()
    cand = {
        "height": 2,
        "hash": _h(0xA3),
        "parent_hash": tip["hash"],
        "transactions": [],
    }
    ok = node.import_block(cand)
    assert ok is True
    assert node.tip_safety_shadow.observe_total == 1
    assert node.tip_safety_shadow.accept_total == 1

    ok2 = node.import_block(_block_dict(99))
    assert ok2 is False
    assert node.tip_safety_shadow.reject_total >= 1

    status = node.get_p2p_security_status()
    assert status.get("tip_safety_shadow_enabled") is True
    assert status.get("tip_safety_enforce") is False
    assert int(status.get("tip_safety_shadow_observe_total", 0)) >= 2


def test_p2p_enforce_refuses_gap_without_calling_chain() -> None:
    cfg = Config()
    cfg.p2p_native_transport = False
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.bootstrap_peers = []
    chain = _FakeChain(1)
    mp = MagicMock()
    node = P2PNode(cfg, chain, mp)
    node.tip_safety_shadow = TipSafetyShadowObserver(enabled=True, enforce=True)
    assert node.tip_safety_shadow.sync_from_chain(chain) is True
    chain.import_block = MagicMock(  # type: ignore[method-assign]
        side_effect=AssertionError("must not import")
    )

    ok = node.import_block(_block_dict(99))
    assert ok is False
    assert node.tip_safety_shadow.enforce_refuse_total >= 1
    chain.import_block.assert_not_called()


def _p2p_enforce_node(chain: _FakeChain) -> P2PNode:
    cfg = Config()
    cfg.p2p_native_transport = False
    cfg.require_native_crypto = False
    cfg.deployment_mode = "dev"
    cfg.bootstrap_peers = []
    node = P2PNode(cfg, chain, MagicMock())
    node.tip_safety_shadow = TipSafetyShadowObserver(enabled=True, enforce=True)
    return node


def test_p2p_import_refuses_below_persisted_ws_anchor(monkeypatch, tmp_path) -> None:
    """P2P import_block (enforce) must refuse a child below a persisted WS anchor.

    Lab-armed: FEATURE_LONG_RANGE env only. Industrial JSON stays false.
    """
    from consensus.long_range import bind_persisted_ws

    path = tmp_path / "ws.json"
    bind_persisted_ws(path=path, env_height="10", env_hash="ff" * 32)
    monkeypatch.setenv("FEATURE_LONG_RANGE", "true")
    monkeypatch.setenv("ABS_WS_CHECKPOINT_PATH", str(path))
    monkeypatch.delenv("ABS_WS_ANCHOR_HEIGHT", raising=False)
    monkeypatch.delenv("ABS_WS_ANCHOR_HASH", raising=False)

    chain = _FakeChain(2)
    node = _p2p_enforce_node(chain)
    assert node.tip_safety_shadow.sync_from_chain(chain) is True
    chain.import_block = MagicMock(  # type: ignore[method-assign]
        side_effect=AssertionError("must not import below WS anchor")
    )
    tip = chain.get_last_block()
    cand = {
        "height": 3,
        "hash": _h(0xB0),
        "parent_hash": tip["hash"],
        "transactions": [],
    }
    assert node.import_block(cand) is False
    assert int(node.tip_safety_shadow.reject_by_code.get("ws_below_ws_anchor", 0)) >= 1
    assert node.tip_safety_shadow.enforce_refuse_total >= 1
    chain.import_block.assert_not_called()


def test_p2p_import_accepts_child_of_persisted_ws_anchor(monkeypatch, tmp_path) -> None:
    """Valid extend above the persisted checkpoint still imports."""
    from consensus.long_range import bind_persisted_ws

    chain = _FakeChain(2)
    tip = chain.get_last_block()
    path = tmp_path / "ws.json"
    bind_persisted_ws(
        path=path,
        env_height=str(tip["height"]),
        env_hash=str(tip["hash"]),
    )
    monkeypatch.setenv("FEATURE_LONG_RANGE", "true")
    monkeypatch.setenv("ABS_WS_CHECKPOINT_PATH", str(path))
    monkeypatch.delenv("ABS_WS_ANCHOR_HEIGHT", raising=False)
    monkeypatch.delenv("ABS_WS_ANCHOR_HASH", raising=False)

    node = _p2p_enforce_node(chain)
    assert node.tip_safety_shadow.sync_from_chain(chain) is True
    cand = {
        "height": 3,
        "hash": _h(0xC0),
        "parent_hash": tip["hash"],
        "transactions": [],
    }
    assert node.import_block(cand) is True
    assert chain.get_height() == 3


def test_p2p_import_flag_off_does_not_apply_ws_anchor(monkeypatch, tmp_path) -> None:
    """Industrial default: persist exists but FEATURE_LONG_RANGE off → AncestryWindow only."""
    from consensus.long_range import bind_persisted_ws

    path = tmp_path / "ws.json"
    bind_persisted_ws(path=path, env_height="10", env_hash="ff" * 32)
    monkeypatch.setenv("FEATURE_LONG_RANGE", "false")
    monkeypatch.setenv("ABS_WS_CHECKPOINT_PATH", str(path))

    chain = _FakeChain(2)
    node = _p2p_enforce_node(chain)
    assert node.tip_safety_shadow.sync_from_chain(chain) is True
    tip = chain.get_last_block()
    cand = {
        "height": 3,
        "hash": _h(0xD0),
        "parent_hash": tip["hash"],
        "transactions": [],
    }
    assert node.import_block(cand) is True
    assert "ws_below_ws_anchor" not in node.tip_safety_shadow.reject_by_code


def test_enforce_implies_allows_import_false_on_none() -> None:
    obs = TipSafetyShadowObserver(enabled=True, enforce=True)
    assert obs.allows_import(None) is False


def test_config_env_defaults() -> None:
    cfg = Config()
    assert cfg.tip_safety_shadow is False
    assert cfg.tip_safety_enforce is False


def test_prod_validate_requires_tip_safety_enforce() -> None:
    cfg = Config()
    cfg.deployment_mode = "prod"
    cfg.require_native_crypto = True
    cfg.p2p_native_transport = False
    cfg.tip_safety_enforce = False
    errors = cfg.validate()
    assert any("tip_safety_enforce" in e for e in errors)


def test_tip_state_from_chain_prefers_get_block_at_height() -> None:
    """Stale last_block ahead of get_height must not become TipState head."""

    class _Split(_FakeChain):
        def get_height(self) -> int:
            return 339

        def get_last_block(self):
            return self._blocks[341]

    chain = _Split(341)
    state = tip_state_from_chain(chain)
    assert state.head.height == 339
    assert state.head.block_hash == chain.get_block(339)["hash"]


def test_tip_state_from_chain_refuses_height_mismatch_without_get_block() -> None:
    class _LastOnly:
        GENESIS_HASH = "0" * 64

        def get_height(self) -> int:
            return 339

        def get_last_block(self):
            return _block_dict(341)

    with pytest.raises(TipValidationError, match="tip height mismatch"):
        tip_state_from_chain(_LastOnly())


def test_observe_resyncs_stale_window_for_catch_up_extend() -> None:
    """Catch-up of local_height+1 must extend the chain tip, not a stale window.

    Live full1: get_height=339, TipState head=341 → PathA #340 was refused as
    deep reorg. Rebind the window before evaluate so #340 is ACCEPT_EXTEND.
    """
    chain = _FakeChain(341)
    obs = TipSafetyShadowObserver(enabled=True, enforce=True)
    assert obs.sync_from_chain(chain) is True
    assert obs.status()["tip_safety_shadow_head_height"] == 341

    chain._height = 339
    nxt = _block_dict(340, n=0xBEEF)
    nxt["parent_hash"] = chain.get_block(339)["hash"]
    decision = obs.observe_before_import(nxt, chain)
    assert decision is not None
    assert decision.accepted is True
    assert decision.reason_code == "ok"
    assert obs.status()["tip_safety_shadow_head_height"] == 339


def test_observe_still_refuses_true_deep_reorg_when_heights_match() -> None:
    chain = _FakeChain(341)
    obs = TipSafetyShadowObserver(enabled=True, enforce=True)
    assert obs.sync_from_chain(chain) is True
    nxt = _block_dict(340, n=0xCAFE)
    nxt["parent_hash"] = chain.get_block(339)["hash"]
    decision = obs.observe_before_import(nxt, chain)
    assert decision is not None
    assert decision.accepted is False
    assert decision.reason_code == "tip_unknown_parent"


def test_p2p_import_catch_up_after_stale_tip_window() -> None:
    chain = _FakeChain(341)
    node = _p2p_enforce_node(chain)
    assert node.tip_safety_shadow.sync_from_chain(chain) is True
    chain._height = 339
    nxt = _block_dict(340, n=0xF00)
    nxt["parent_hash"] = chain.get_block(339)["hash"]
    assert node.import_block(nxt) is True
    assert chain.get_height() == 340


def test_p2p_precheck_defers_own_forge_when_chain_tip_lags() -> None:
    """Miner restart race: get_height=9565 while gossip echo of forged 9567 arrives.

    apply_queue is idle (busy=False), so skip-ahead defer does not fire.
    note_local_forge(height=9567) must still skip tip_unknown_parent.
    """
    chain = _FakeChain(9565)
    node = _p2p_enforce_node(chain)
    assert node.tip_safety_shadow.sync_from_chain(chain) is True
    node.note_local_forge(0.0, height=9567)
    echo = _block_dict(9567, n=0xEE)
    echo["parent_hash"] = chain.get_block(9566)["hash"] if chain.get_block(9566) else _h(9566)
    assert node._tip_safety_precheck(echo) is True
