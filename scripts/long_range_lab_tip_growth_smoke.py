#!/usr/bin/env python3
"""Long-Range lab tip-growth smoke — refuse soak start if tip is dead.

Waits until max height across lab HTTP ports advances by ``--min-advance``
within ``--timeout-sec``. Catches the false-green pattern (mesh OK, tip stuck)
before a multi-hour soak burns wall-clock.

Usage:
  python scripts/long_range_lab_tip_growth_smoke.py
  python scripts/long_range_lab_tip_growth_smoke.py --timeout-sec 180 --min-advance 2
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Iterable

DEFAULT_PORTS = (29080, 29081, 29082)


def _height(port: int, timeout: float = 15.0) -> int:
    url = f"http://127.0.0.1:{port}/status"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return int(data.get("height", -1))


def _snapshot(ports: Iterable[int]) -> dict[int, int]:
    out: dict[int, int] = {}
    for p in ports:
        try:
            out[int(p)] = _height(int(p))
        except (urllib.error.URLError, TimeoutError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"port {p} status failed: {exc}") from exc
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ports", default=",".join(str(p) for p in DEFAULT_PORTS))
    ap.add_argument("--timeout-sec", type=int, default=180)
    ap.add_argument("--poll-sec", type=float, default=5.0)
    ap.add_argument("--min-advance", type=int, default=2)
    ap.add_argument("--max-delta", type=int, default=2, help="max height skew across nodes")
    args = ap.parse_args()
    ports = [int(x.strip()) for x in str(args.ports).split(",") if x.strip()]
    if not ports:
        print("FAIL: no ports", file=sys.stderr)
        return 2
    for p in ports:
        if p in (18180, 18181, 18182):
            print("FAIL: refuse prod mesh ports", file=sys.stderr)
            return 2

    start = _snapshot(ports)
    start_max = max(start.values())
    start_min = min(start.values())
    print(
        f"tip_growth_smoke start heights={start} max={start_max} "
        f"delta={start_max - start_min} need_advance={args.min_advance} "
        f"timeout={args.timeout_sec}s"
    )
    if start_max - start_min > int(args.max_delta):
        print(
            f"FAIL: initial height skew {start_max - start_min} > max_delta={args.max_delta}",
            file=sys.stderr,
        )
        return 1

    deadline = time.time() + max(30, int(args.timeout_sec))
    last = start
    while time.time() < deadline:
        time.sleep(max(1.0, float(args.poll_sec)))
        last = _snapshot(ports)
        cur_max = max(last.values())
        cur_min = min(last.values())
        delta = cur_max - cur_min
        advance = cur_max - start_max
        print(
            f"  poll heights={last} max={cur_max} advance={advance} skew={delta}"
        )
        if delta > int(args.max_delta):
            print(
                f"FAIL: height skew {delta} > max_delta={args.max_delta}",
                file=sys.stderr,
            )
            return 1
        if advance >= int(args.min_advance):
            print(
                f"OK: long_range_lab_tip_growth_smoke PASS "
                f"advance={advance} heights={last} (lab-only; not BLS)"
            )
            return 0

    print(
        f"FAIL: tip stagnant start_max={start_max} last={last} "
        f"advance={max(last.values()) - start_max} "
        f"need>={args.min_advance} within {args.timeout_sec}s",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
