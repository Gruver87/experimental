#!/usr/bin/env python3
"""Seed ADR 0017 WS checkpoint from the live Long-Range lab tip.

Reads tip on lab HTTP, writes digest (+ optional Ed25519 committee sigs) to
bind-mounted persist paths for lr0/lr1/lr2, then restarts lab services.

Never touches prod mesh 18180–18182 / chain 778888.

Usage:
  python scripts/seed_long_range_lab_ws.py --restart
  python scripts/seed_long_range_lab_ws.py --base-url http://127.0.0.1:29080
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_BASE = "http://127.0.0.1:29080"
DEFAULT_PERSISTS = [
    ROOT / "data" / "long_range_lab0" / "ws_checkpoint.json",
    ROOT / "data" / "long_range_lab1" / "ws_checkpoint.json",
    ROOT / "data" / "long_range_lab2" / "ws_checkpoint.json",
]
COMMITTEE_SECRETS = ROOT / "data" / "long_range_lab_committee" / "secrets.json"
COMMITTEE_PUBKEYS = ROOT / "data" / "long_range_lab_committee" / "pubkeys.json"
COMPOSE_FILE = "docker-compose.long_range.lab.yml"
COMPOSE_PROJECT = "abs-lr-lab"
LAB_SERVICES = ("lr0", "lr1", "lr2")


def _get_json(url: str, timeout: float = 8.0) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _wait_ready(base: str, *, attempts: int = 40) -> dict:
    last_err = ""
    for _ in range(1, attempts + 1):
        try:
            live = _get_json(f"{base.rstrip('/')}/health/live", timeout=5)
            if str(live.get("status") or "") != "alive":
                last_err = f"live={live.get('status')!r}"
            else:
                try:
                    ready = _get_json(f"{base.rstrip('/')}/health/ready", timeout=8)
                    if str(ready.get("status") or "") == "ready":
                        return ready
                    last_err = f"ready={ready.get('status')!r}"
                except urllib.error.HTTPError as exc:
                    last_err = f"ready_http={exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_err = str(exc)
        time.sleep(2.0)
    raise RuntimeError(f"lab not ready after {attempts} attempts: {last_err}")


def _tip(base: str) -> tuple[int, str]:
    for path in ("/status?probe=1", "/status"):
        try:
            st = _get_json(f"{base.rstrip('/')}{path}", timeout=10)
            height = int(st.get("height") or 0)
            head = str(st.get("head_hash") or st.get("hash") or "").strip()
            if head:
                return height, head
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ):
            continue
    raise RuntimeError("could not read tip height/hash from lab /status")


def _committee_signatures(digest: str):
    from consensus.long_range.committee import sign_with_keys

    if not COMMITTEE_SECRETS.is_file():
        return ()
    raw = json.loads(COMMITTEE_SECRETS.read_text(encoding="utf-8"))
    members = list(raw.get("members") or [])
    thr = int(raw.get("threshold") or 0)
    if thr < 1:
        from consensus.long_range.committee import threshold_for

        thr = threshold_for(len(members))
    privs = [str(m["private_key"]) for m in members[:thr]]
    return sign_with_keys(digest=digest, private_keys_hex=privs)


def seed(*, persist: Path, height: int, block_hash: str) -> Path:
    from consensus.long_range import CheckpointCertificate, CheckpointStore

    persist.parent.mkdir(parents=True, exist_ok=True)
    cert = CheckpointCertificate.issue(
        height=int(height),
        block_hash=str(block_hash),
        issuer="seed_long_range_lab_ws",
    )
    sigs = _committee_signatures(cert.digest)
    if sigs:
        cert = cert.with_signatures(sigs)
    store = CheckpointStore()
    store.push(cert)
    store.save(persist)
    return persist


def seed_all(*, persists: list[Path], height: int, block_hash: str) -> list[Path]:
    return [seed(persist=p, height=height, block_hash=block_hash) for p in persists]


def _restart_lab(*, services: tuple[str, ...] = LAB_SERVICES) -> None:
    cmd = [
        "docker",
        "compose",
        "-p",
        COMPOSE_PROJECT,
        "-f",
        COMPOSE_FILE,
        "restart",
        *services,
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"docker compose restart exit {proc.returncode}")


def _assert_defense(base: str) -> dict:
    body = _get_json(f"{base.rstrip('/')}/consensus/weak-subjectivity", timeout=10)
    if not bool(body.get("long_range_defense")):
        raise RuntimeError(
            f"long_range_defense still false after seed: {json.dumps(body, sort_keys=True)}"
        )
    if not bool(body.get("long_range_armed")):
        raise RuntimeError(f"long_range_armed false: {body}")
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--persist", type=Path, default=None)
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Restart abs-lr-lab services after writing checkpoints",
    )
    parser.add_argument("--skip-wait", action="store_true")
    parser.add_argument(
        "--all-nodes",
        action="store_true",
        default=True,
        help="Seed lr0/lr1/lr2 persist paths (default)",
    )
    parser.add_argument("--single", action="store_true", help="Seed only --persist / lr0")
    args = parser.parse_args()
    base = str(args.base_url).strip()
    if any(p in base for p in (":18180", ":18181", ":18182")):
        print("FAIL: refuse prod mesh ports 18180–18182")
        return 1

    # Ensure committee env for local verify helpers matches compose.
    if COMMITTEE_PUBKEYS.is_file():
        os.environ.setdefault("ABS_WS_COMMITTEE_PUBKEYS_FILE", str(COMMITTEE_PUBKEYS))
        os.environ.setdefault("ABS_WS_COMMITTEE_REQUIRED", "true")

    try:
        if not args.skip_wait:
            _wait_ready(base)
        height, head = _tip(base)
        if args.single:
            persist = args.persist or DEFAULT_PERSISTS[0]
            paths = [seed(persist=persist, height=height, block_hash=head)]
        else:
            paths = seed_all(persists=list(DEFAULT_PERSISTS), height=height, block_hash=head)
        for path in paths:
            print(f"OK: wrote WS checkpoint h={height} hash={head[:16]}... -> {path}")
        if args.restart:
            _restart_lab()
            print(f"OK: restarted abs-lr-lab {','.join(LAB_SERVICES)}")
            time.sleep(5.0)
            _wait_ready(base)
            honesty = _assert_defense(base)
            print(
                "OK: long_range_defense=true "
                f"anchor_h={honesty.get('ws_anchor_height')} "
                f"detail={honesty.get('detail')!r}"
            )
        else:
            print(
                "NOTE: tip-safety loads WS at boot — re-run with --restart "
                "before claiming live defense."
            )
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
