#!/usr/bin/env python3
"""Unit tests for Long-Range WS checkpoint gossip (ADR 0017 wave-14)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consensus.long_range.checkpoint import CheckpointCertificate
from consensus.long_range.checkpoint_store import CheckpointStore
from consensus.long_range.gossip import (
    OUTCOME_ADOPTED,
    OUTCOME_DUPLICATE,
    OUTCOME_PARSE_ERROR,
    OUTCOME_STALE_HEIGHT,
    adopt_peer_certificate,
    merge_peer_certificate_dict,
    validate_ws_checkpoint_payload,
)
from network import p2p_node as pn
from network.p2p_dispatch.constants import DISPATCHABLE_TYPES, MSG_WS_CHECKPOINT


def _cert(h: int) -> CheckpointCertificate:
    return CheckpointCertificate.issue(height=h, block_hash=f"{h:064x}")


def test_validate_ws_checkpoint_payload_ok() -> None:
    cert = _cert(5)
    parsed = validate_ws_checkpoint_payload(dict(cert.to_dict()))
    assert parsed is not None
    assert parsed.digest == cert.digest


def test_validate_ws_checkpoint_payload_rejects_tamper() -> None:
    cert = _cert(5)
    bad = dict(cert.to_dict())
    bad["height"] = 99
    assert validate_ws_checkpoint_payload(bad) is None


def test_adopt_peer_certificate_stale_and_duplicate() -> None:
    store = CheckpointStore()
    c10 = _cert(10)
    c20 = _cert(20)
    assert adopt_peer_certificate(store, c10) == OUTCOME_ADOPTED
    assert adopt_peer_certificate(store, c20) == OUTCOME_ADOPTED
    assert adopt_peer_certificate(store, _cert(5)) == OUTCOME_STALE_HEIGHT
    assert adopt_peer_certificate(store, c20) == OUTCOME_DUPLICATE


def test_merge_peer_certificate_dict_parse_error() -> None:
    store = CheckpointStore()
    out = merge_peer_certificate_dict(store, {"height": "x"})
    assert out["outcome"] == OUTCOME_PARSE_ERROR
    assert out["adopted"] is False


def test_ws_checkpoint_wire_parity() -> None:
    assert MSG_WS_CHECKPOINT == pn.MSG_WS_CHECKPOINT
    assert MSG_WS_CHECKPOINT in pn.ALLOWED_WIRE_TYPES
    assert MSG_WS_CHECKPOINT in DISPATCHABLE_TYPES
