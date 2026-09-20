#!/usr/bin/env python3
"""Consensus adapter exposes Explorer-expected feature flags."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from runtime.config import Config
from storage.database import Database
from consensus.adapter import ConsensusAdapter


def test_consensus_stats_feature_flags():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    cfg = Config()
    cfg.db_path = path
    db = Database(path)
    db.initialize()
    try:
        ca = ConsensusAdapter(cfg, db, None)
        stats = ca.get_stats()
        assert stats.get("enabled") is True
        assert stats.get("lmd_ghost_enabled") is True
        assert stats.get("casper_ffg") is True
        assert stats.get("slashing_enabled") is True
        # Sprouts default OFF: PBS follows feature_mev (fail-closed bare Config).
        assert stats.get("pbs_enabled") is False
        assert stats.get("validator_registry") is True
        assert stats["systems"]["lmd_ghost"] is True
        cfg.feature_mev = True
        ca2 = ConsensusAdapter(cfg, db, None)
        assert ca2.get_stats().get("pbs_enabled") is True
    finally:
        db.close()
        os.remove(path)
