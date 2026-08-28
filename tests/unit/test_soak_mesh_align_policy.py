#!/usr/bin/env python3
"""Mesh misalign lines in 87f51b3e soak were poll-skew, not consensus forks."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOAK_LOG = ROOT / "docs" / "evidence" / "runs" / "87f51b3e" / "soak_48h_experimental.log"
MISALIGNED = re.compile(
    r"WARN mesh misaligned h18180=(\d+) h18181=(\d+) h18182=(\d+)"
)


def _delta(h0: int, h1: int, h2: int) -> int:
    return max(h0, h1, h2) - min(h0, h1, h2)


def test_87f51b3e_mesh_warns_are_poll_skew_not_forks():
    assert SOAK_LOG.is_file(), f"missing evidence log: {SOAK_LOG}"
    lines = SOAK_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    warns = [MISALIGNED.search(line) for line in lines if "WARN mesh misaligned" in line]
    warns = [w for w in warns if w]
    assert warns, "expected mesh misaligned lines in 87f51b3e evidence"
    deltas = [_delta(int(w.group(1)), int(w.group(2)), int(w.group(3))) for w in warns]
    assert max(deltas) <= 4
    assert sum(1 for d in deltas if d <= 2) >= 45
    # health_watch_core now accepts delta<=2 and resnapshots before WARN.
    assert sum(1 for d in deltas if d > 2) == 1
