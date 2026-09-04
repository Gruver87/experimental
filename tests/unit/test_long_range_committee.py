"""Unit tests for ADR 0017 Ed25519 committee WS certs."""

from __future__ import annotations

import os

from consensus.long_range.checkpoint import CheckpointCertificate
from consensus.long_range.committee import (
    CommitteeConfig,
    generate_keypair,
    sign_with_keys,
    threshold_for,
    verify_committee_quorum,
)
from consensus.long_range.gossip import (
    OUTCOME_ADOPTED,
    OUTCOME_COMMITTEE_INVALID,
    adopt_peer_certificate,
    merge_peer_certificate_dict,
)
from consensus.long_range.checkpoint_store import CheckpointStore


def test_threshold_two_thirds():
    assert threshold_for(3) == 2
    assert threshold_for(1) == 1
    assert threshold_for(0) == 0


def test_committee_quorum_sign_verify():
    keys = [generate_keypair() for _ in range(3)]
    pubs = tuple(p for _, p in keys)
    privs = [s for s, _ in keys]
    committee = CommitteeConfig(pubkeys=pubs, threshold=2)
    cert = CheckpointCertificate.issue(height=5, block_hash="ab" * 32)
    sigs = sign_with_keys(digest=cert.digest, private_keys_hex=privs[:2])
    assert verify_committee_quorum(
        digest=cert.digest, signatures=sigs, committee=committee
    )
    signed = cert.with_signatures(sigs)
    assert signed.verify_digest()
    assert signed.verify_committee(committee)


def test_gossip_refuses_unsigned_when_committee_required(monkeypatch):
    keys = [generate_keypair() for _ in range(3)]
    pubs = ",".join(p for _, p in keys)
    monkeypatch.setenv("ABS_WS_COMMITTEE_PUBKEYS", pubs)
    monkeypatch.setenv("ABS_WS_COMMITTEE_REQUIRED", "true")
    monkeypatch.setenv("ABS_WS_COMMITTEE_THRESHOLD", "2")
    store = CheckpointStore()
    unsigned = CheckpointCertificate.issue(height=1, block_hash="cd" * 32)
    assert adopt_peer_certificate(store, unsigned) == OUTCOME_COMMITTEE_INVALID
    sigs = sign_with_keys(
        digest=unsigned.digest, private_keys_hex=[keys[0][0], keys[1][0]]
    )
    signed = unsigned.with_signatures(sigs)
    assert adopt_peer_certificate(store, signed) == OUTCOME_ADOPTED
    result = merge_peer_certificate_dict(store, dict(signed.to_dict()))
    assert result["outcome"] == "duplicate"


def test_digest_only_mode_without_committee(monkeypatch):
    monkeypatch.delenv("ABS_WS_COMMITTEE_PUBKEYS", raising=False)
    monkeypatch.delenv("ABS_WS_COMMITTEE_PUBKEYS_FILE", raising=False)
    monkeypatch.delenv("ABS_WS_COMMITTEE_REQUIRED", raising=False)
    store = CheckpointStore()
    cert = CheckpointCertificate.issue(height=2, block_hash="ef" * 32)
    assert adopt_peer_certificate(store, cert) == OUTCOME_ADOPTED
