#!/usr/bin/env python3
"""ADR 0007 Wave A: consensus ports + pure domain types (no P2P)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consensus.bft.types import ValidatorInfo, ValidatorSetSnapshot, VoteType
from consensus.ports import (
    ConsensusEvidencePort,
    ConsensusLockdownPort,
    ConsensusPort,
    ValidatorRegistryPort,
)
from tests.unit.fakes.fake_consensus import (
    FakeConsensusEvidence,
    FakeConsensusLockdown,
    FakeValidatorRegistry,
)


def test_needles_adr0007_ports_exist():
    ports = (ROOT / "consensus" / "ports.py").read_text(encoding="utf-8")
    assert "class ConsensusPort" in ports
    assert "class ValidatorRegistryPort" in ports
    assert "class ConsensusEvidencePort" in ports
    assert "class ConsensusLockdownPort" in ports
    types = (ROOT / "consensus" / "bft" / "types.py").read_text(encoding="utf-8")
    assert "VoteType" in types
    assert "QuorumCertificate" in types
    assert "ConsensusSecurityEvidence" in types
    adr = (ROOT / "docs" / "adr" / "0007-consensus-boundary.md").read_text(
        encoding="utf-8"
    )
    assert "Accepted A–C" in adr or "Accepted A" in adr
    assert "finality_quorum_live" in adr


def test_bft_package_has_no_network_imports():
    bft_dir = ROOT / "consensus" / "bft"
    for path in bft_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("network"), path.name
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("network"), path.name
                assert "p2p_node" not in node.module, path.name


def test_fake_registry_snapshot_and_slash():
    reg = FakeValidatorRegistry()
    reg.register("v1", 100)
    reg.register("v2", 50)
    assert isinstance(reg, ValidatorRegistryPort)
    snap = reg.snapshot()
    assert isinstance(snap, ValidatorSetSnapshot)
    assert snap.total_active_stake() == 150_000_000  # Wave M: satoshi, not float ABS
    assert snap.is_active("v1")
    reg.mark_slashed("v1", "double_vote")
    assert not reg.is_active("v1")
    assert reg.total_active_stake() == 50_000_000


def test_fake_evidence_and_lockdown_ports():
    ev = FakeConsensusEvidence()
    ld = FakeConsensusLockdown()
    assert isinstance(ev, ConsensusEvidencePort)
    assert isinstance(ld, ConsensusLockdownPort)
    n = ev.note_malicious_attempt("v1", "double_vote")
    assert n == 1
    from consensus.bft.types import ConsensusSecurityEvidence

    evidence = ConsensusSecurityEvidence(
        reason_code="double_vote", validator_id="v1", attempt_count=1
    )
    ev.emit(evidence)
    assert len(ev.emitted) == 1
    ld.request_lockdown("consensus_double_sign")
    assert ld.locked is True
    assert VoteType.PREVOTE.value == "prevote"
