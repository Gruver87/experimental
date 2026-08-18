#!/usr/bin/env python3
"""ADR 0007 Wave C: ConsensusAdapter façade + deployment_mode contract."""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from consensus.adapter import ConsensusAdapter
from consensus.bft import Proposal, RoundId, Vote, VoteType
from kernel.event_bus import EventBus
from runtime.config import Config
from storage.database import Database


def _adapter(mode: str = "auto", deployment: str = "dev"):
    tmp = tempfile.mkdtemp()
    cfg = Config()
    cfg.db_path = os.path.join(tmp, "c.db")
    cfg.deployment_mode = deployment
    cfg.consensus_mode = mode
    db = Database(cfg.db_path)
    db.initialize()
    return ConsensusAdapter(cfg, db, EventBus()), cfg


def test_adapter_implements_consensus_port_surface():
    adapter, _ = _adapter(mode="unified", deployment="dev")
    assert hasattr(adapter, "round_state")
    assert adapter.round_state is adapter.round_sm
    assert adapter._registry_port is not None
    for name in (
        "submit_proposal",
        "submit_vote",
        "current_round",
        "round_phase",
        "canonical_head",
        "finality_status",
        "quorum_certificate",
        "add_block",
    ):
        assert callable(getattr(adapter, name))
    view = adapter.finality_status()
    assert view.quorum_live is False
    stats = adapter.get_stats()
    assert stats["consensus_ports_enabled"] is True
    assert stats["finality_quorum_live"] is False
    assert "bft_round_phase" in stats
    assert stats.get("deployment_mode") == "dev"


def test_staging_auto_resolves_unified():
    adapter, cfg = _adapter(deployment="staging")
    assert cfg.resolved_consensus_mode() == "unified"
    assert adapter._unified_consensus is True
    assert adapter.casper_engine is None
    assert adapter.beacon_engine is None


def test_adapter_submit_vote_unknown_returns_locked_outcome():
    adapter, _ = _adapter(mode="unified", deployment="dev")
    adapter.add_validator("0x" + "11" * 20, 100)
    rid = adapter.round_sm.open_round(1, expected_proposer="0x" + "11" * 20)
    adapter.submit_proposal(
        Proposal(
            proposer_id="0x" + "11" * 20,
            round_id=rid,
            block_hash="aa" * 32,
            parent_hash="bb" * 32,
        )
    )
    out = adapter.submit_vote(
        Vote(
            validator_id="0x" + "99" * 20,
            vote_type=VoteType.PREVOTE,
            round_id=rid,
            block_hash="aa" * 32,
            verified=True,
        )
    )
    assert out.status.value == "locked"
    assert out.reason_code == "unknown_validator_vote"
    assert adapter._consensus_lockdown_reason or adapter.get_stats().get(
        "consensus_lockdown_reason"
    )


def test_legacy_attest_still_works_with_explicit_dev_mode():
    adapter, cfg = _adapter(mode="unified", deployment="dev")
    assert cfg.deployment_mode == "dev"
    addr = "0x" + "22" * 20
    adapter.add_validator(addr, 50)
    hh = "ab" * 32
    adapter.add_block_to_fork_choice(
        {"hash": hh, "parent_hash": "00" * 32, "number": 1}
    )
    ok = adapter.attest(addr, hh, slot=1)
    assert ok is True


def test_add_validator_refuses_bool_stake():
    adapter, _ = _adapter(mode="unified", deployment="dev")
    raised = False
    try:
        adapter.add_validator("0x" + "33" * 20, True)
    except TypeError:
        raised = True
    assert raised
