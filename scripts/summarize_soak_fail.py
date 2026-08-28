#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Host-side FAIL pack for an Experimental soak log. Never sets passed=true."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
PORT = re.compile(r"port\s+(1818[0-2])", re.IGNORECASE)
FULL_EVERY = re.compile(r"full_every=(\S+)")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-16", errors="replace")


def _parse_ts(line: str) -> datetime | None:
    m = TS.match(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _diagnose(fail_lines: list[str], report: dict) -> str:
    """Honest per-run diagnosis. Never invent a PASS or a stale root cause."""
    joined = "\n".join(fail_lines)
    exit_code = report.get("health_watch_exit")
    hard = (report.get("counts") or {}).get("hard_fail_lines")
    ready_only = (report.get("counts") or {}).get("ready_only_fail_lines")
    hours = report.get("hours_elapsed")
    parts = [
        f"hours_elapsed={hours} health_watch_exit={exit_code} "
        f"hard_fail_lines={hard} ready_only_fail={ready_only} fail_lines={len(fail_lines)}."
    ]
    if any("ready:" in line and "503" in line for line in fail_lines):
        parts.append(
            "Last-cycle /health/ready returned 503 and GET /status timed out on "
            "the same port. health_watch counts that as hard_fail (exit=1), so "
            "default 48h scoring is passed=false even when soak_monitor labels "
            "the line ready_only_fail."
        )
    elif any("status" in line.lower() for line in fail_lines):
        parts.append("FAIL lines include GET /status timeout/error.")
    elif fail_lines:
        parts.append("See first_fail/last_fail. Do not relabel as PASS.")
    else:
        parts.append("No FAIL lines in the log; if report.passed is false, see health_watch_exit.")
    if "status_slow" in joined:
        parts.append("status_slow also present on FAIL lines.")
    parts.append("This file remains FAIL evidence. Not Hybrid 375d14f. Not TCP+TLS 0a7932c4.")
    return " ".join(parts)


def summarize(
    *,
    log_path: Path,
    report_path: Path | None,
) -> dict:
    report: dict = {}
    if report_path and report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))

    lines = _read_text(log_path).splitlines() if log_path.is_file() else []
    start_ts = None
    full_every = ""
    fail_lines: list[str] = []
    warn_probe = 0
    mesh_ok = 0
    first_fail: str | None = None
    last_fail: str | None = None
    by_hour: Counter[int] = Counter()
    by_port: Counter[str] = Counter()

    for line in lines:
        if "health_watch start" in line and start_ts is None:
            start_ts = _parse_ts(line)
            mfe = FULL_EVERY.search(line)
            if mfe:
                full_every = mfe.group(1)
        if "OK mesh aligned" in line:
            mesh_ok += 1
        if "peer_probe_ok" in line and "WARN" in line:
            warn_probe += 1
        ts = _parse_ts(line)
        if ts is None or " FAIL" not in line:
            continue
        fail_lines.append(line)
        if first_fail is None:
            first_fail = line
        last_fail = line
        if start_ts is not None:
            hour = max(0, int((ts - start_ts).total_seconds() // 3600))
            by_hour[hour] += 1
        pm = PORT.search(line)
        if pm:
            by_port[pm.group(1)] += 1

    hours_zero_fail = 0
    first_fail_hour = None
    if by_hour and start_ts is not None:
        max_h = max(by_hour)
        for h in range(0, max_h + 1):
            if by_hour[h] == 0:
                hours_zero_fail += 1
            elif first_fail_hour is None:
                first_fail_hour = h

    passed_report = bool(report.get("passed"))
    payload = {
        "passed": False,
        "claim": "FAIL",
        "note": (
            "Experimental soak FAIL pack. Not a 48h PASS. "
            "Hybrid docs/evidence/runs/375d14f is a different tree."
        ),
        "log_file": str(log_path.as_posix()),
        "report_file": str(report_path.as_posix()) if report_path else "",
        "report_passed": passed_report,
        "hours_elapsed": report.get("hours_elapsed"),
        "hours_requested": report.get("hours_requested"),
        "health_watch_exit": report.get("health_watch_exit"),
        "counts_from_report": report.get("counts"),
        "full_every_logged": full_every,
        "mesh_ok_lines": mesh_ok,
        "fail_lines": len(fail_lines),
        "warn_peer_probe_ok": warn_probe,
        "first_fail": first_fail,
        "last_fail": last_fail,
        "first_fail_hour": first_fail_hour,
        "hours_with_zero_fails_before_max": hours_zero_fail,
        "fails_by_hour": {str(k): by_hour[k] for k in sorted(by_hour)},
        "fails_by_port": dict(by_port),
        "diagnosis_this_run": _diagnose(fail_lines, report),
    }
    if passed_report:
        payload["note"] = (
            "Report JSON says passed=true but this script never claims PASS; "
            "inspect the report separately. This file is a FAIL pack generator."
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Write an honest soak FAIL summary")
    parser.add_argument(
        "--log",
        default="logs/soak_48h_experimental.log",
        help="Soak log path relative to repo root",
    )
    parser.add_argument(
        "--report",
        default="logs/soak_report_48h_experimental.json",
        help="Soak report JSON (may be missing)",
    )
    parser.add_argument(
        "--out",
        default="logs/soak_48h_experimental_fail_summary.json",
        help="Output JSON (always passed=false)",
    )
    args = parser.parse_args()
    log_path = ROOT / args.log
    report_path = ROOT / args.report
    if not log_path.is_file():
        print(f"FAIL: log missing {log_path}")
        return 1
    payload = summarize(
        log_path=log_path,
        report_path=report_path if report_path.is_file() else None,
    )
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} passed={payload['passed']} fail_lines={payload['fail_lines']}")
    if payload["passed"] is True:
        print("FAIL: summarizer must never set passed=true")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
