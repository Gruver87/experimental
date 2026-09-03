#!/usr/bin/env python3
"""48h soak rescore: single ready-only FAIL + mesh aligned => passed after fix."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_soak_rescore_ready_only_fail_passes(tmp_path):
    log = tmp_path / "soak.log"
    lines = [
        "2026-08-30 10:08:21 health_watch start ports=18180,18181,18182 interval=300s full_every=6 log=x parallel=1",
        "2026-08-30 10:08:23 OK port 18180 [quick] height=12 peers=2 p2p=aligned aligned=True failed=",
        "2026-08-30 10:08:23 OK port 18181 [quick] height=12 peers=2 p2p=aligned aligned=True failed=",
        "2026-08-30 10:08:23 OK port 18182 [quick] height=12 peers=2 p2p=aligned aligned=True failed=",
        "2026-08-30 10:08:23 OK mesh aligned 18180:h12/p2 18181:h12/p2 18182:h12/p2",
        "2026-09-01 09:56:41 FAIL port 18182 ready: (503) Server Unavailable.; status: timeout",
        "2026-09-01 09:56:41 WARN mesh partial aligned 18180:h8415/p2 18181:h8415/p1",
        "2026-09-01 10:02:47 OK mesh aligned 18180:h8420/p2 18181:h8420/p1 18182:h8420/p2",
        "2026-09-01 10:08:46 OK mesh aligned 18180:h8427/p2 18181:h8427/p2 18182:h8427/p2",
        "2026-09-01 10:08:46 health_watch done (duration 2880m cycles=540 hard_fails=0 ready_only=1)",
        "2026-09-01 10:08:46 health_watch exit=0 ready_only_fails=1 (48h tolerated when mesh aligned)",
    ]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = tmp_path / "report.json"
    ps1 = ROOT / "scripts" / "soak_monitor.ps1"
    proc = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1),
            "-RescoreOnly",
            "-Hours",
            "48",
            "-LogFile",
            str(log),
            "-ReportFile",
            str(report),
            "-HealthWatchExit",
            "0",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["passed"] is True
    assert data["counts"]["ready_only_fail_lines"] == 1
    assert data["counts"]["hard_fail_lines"] == 0
