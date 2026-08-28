#!/usr/bin/env python3
"""Long-Range lab 2h harness — preflight only by default (ADR 0017).

Does **not** start a timed soak. Does **not** touch prod mesh ``778888`` JSON.
Default: assert prod flags off + run LR labs (wave 12–14).

Timed 2h is operator-only **after** libp2p 48h PASS (EXECUTION_ORDER Phase 2):

  set ABS_ALLOW_LR_LAB_2H=1
  python scripts/long_range_lab_2h_harness.py --start-2h
  # → currently refuses with next-step instructions (no silent soak)

Usage:
  python scripts/long_range_lab_2h_harness.py
  python scripts/long_range_lab_2h_harness.py --preflight-only
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROD_MESH_JSON = [
    ROOT / "docker" / "node.prod.json",
    ROOT / "docker" / "node.prod.mesh1.json",
    ROOT / "docker" / "node.prod.mesh2.json",
    ROOT / "docker" / "node.prod.mesh3.json",
]

LAB_COMPOSE = ROOT / "docker-compose.long_range.lab.yml"
LAB_NODE = ROOT / "node.long_range.lab.json"
LR_PROFILE = ROOT / "docs" / "sprouts" / "LONG_RANGE_LAB_PROFILE.md"

LR_LABS = [
    "scripts/long_range_lab.py",
    "scripts/long_range_p2p_lab.py",
    "scripts/long_range_gossip_lab.py",
]


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _check_prod_flags_off() -> int:
    for path in PROD_MESH_JSON:
        if not path.is_file():
            return _fail(f"missing prod mesh JSON: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("feature_long_range") is not False:
            return _fail(f"{path.name}: feature_long_range must be false")
        if data.get("feature_oracles") is True:
            return _fail(f"{path.name}: feature_oracles must not be true on prod mesh")
        if data.get("feature_sharding") is True:
            return _fail(f"{path.name}: feature_sharding must not be true on prod mesh")
    print("OK: prod mesh JSON keeps feature_long_range=false (and oracle/shard off)")
    return 0


def _check_lab_compose() -> int:
    if not LAB_COMPOSE.is_file():
        return _fail(f"missing {LAB_COMPOSE.name}")
    text = LAB_COMPOSE.read_text(encoding="utf-8")
    if "abs-lr-lab" not in text or "FEATURE_LONG_RANGE" not in text:
        return _fail("long_range lab compose must document abs-lr-lab + FEATURE_LONG_RANGE")
    if "778888" in text or "node.prod" in text:
        return _fail("long_range lab compose must not reference prod mesh JSON / 778888")
    if not LAB_NODE.is_file():
        return _fail(f"missing {LAB_NODE.name}")
    node = json.loads(LAB_NODE.read_text(encoding="utf-8"))
    if node.get("deployment_mode") != "dev":
        return _fail("node.long_range.lab.json deployment_mode must be dev")
    if node.get("feature_long_range") is not True:
        return _fail("node.long_range.lab.json feature_long_range must be true")
    if node.get("feature_oracles") is True or node.get("feature_sharding") is True:
        return _fail("LR lab node must keep oracles/sharding off")
    if int(node.get("chain_id") or 0) == 778888:
        return _fail("LR lab must not reuse prod chain_id 778888")
    print("OK: LR lab compose + node.long_range.lab.json (dev, separate chain_id)")
    return 0


def _check_lr_profile_doc() -> int:
    if not LR_PROFILE.is_file():
        return _fail(f"missing {LR_PROFILE.relative_to(ROOT)}")
    text = LR_PROFILE.read_text(encoding="utf-8")
    for needle in ("abs-lr-lab", "29080", "ABS_WS_CHECKPOINT_PATH", "feature_long_range=false"):
        if needle not in text:
            return _fail(f"LONG_RANGE_LAB_PROFILE.md must mention {needle!r}")
    print("OK: LONG_RANGE_LAB_PROFILE.md documents lab compose + WS env")
    return 0


def _check_compose_isolation() -> int:
    text = LAB_COMPOSE.read_text(encoding="utf-8")
    if "ABS_WS_CHECKPOINT_PATH" not in text:
        return _fail("LR compose must set ABS_WS_CHECKPOINT_PATH")
    for prod_port in ("18180", "18181", "18182", "778888"):
        if prod_port in text:
            return _fail(f"LR compose must not reference prod port/chain {prod_port}")
    for lab_port in ("29080", "29545", "26000"):
        if lab_port not in text:
            return _fail(f"LR compose must expose lab port {lab_port}")
    node = json.loads(LAB_NODE.read_text(encoding="utf-8"))
    if node.get("feature_libp2p") is True:
        return _fail("LR lab node must keep feature_libp2p=false (TCP lab path)")
    print("OK: LR compose ports isolated + WS checkpoint env + libp2p off")
    return 0


def _run_long_range_unit_smoke() -> int:
    py = sys.executable
    proc = subprocess.run(
        [py, "-m", "pytest", "tests/unit", "-k", "long_range", "-q"],
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return _fail(f"pytest -k long_range exit {proc.returncode}")
    print("OK: pytest -k long_range")
    return 0


def _run_labs() -> int:
    py = sys.executable
    for lab in LR_LABS:
        print(f"==> {lab}")
        proc = subprocess.run(
            [py, str(ROOT / lab)],
            cwd=str(ROOT),
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            return _fail(f"{lab} exit {proc.returncode}")
        print(f"OK: {lab}")
    return 0


def _refuse_start_2h() -> int:
    allow = os.environ.get("ABS_ALLOW_LR_LAB_2H", "").strip() == "1"
    if not allow:
        print(
            "REFUSE: timed LR lab 2h requires ABS_ALLOW_LR_LAB_2H=1 "
            "(and libp2p 48h PASS first — EXECUTION_ORDER Phase 2)."
        )
        return 2
    print(
        "REFUSE: --start-2h is armed by env but this harness does not auto-launch "
        "health_watch yet. After B1 PASS, operator brings up dedicated compose:\n"
        "  docker compose -p abs-lr-lab -f docker-compose.long_range.lab.yml up -d --build\n"
        "then health_watch on lab ports 29080 (never docker/node.prod*.json). "
        "See docs/sprouts/LONG_RANGE_LAB_PROFILE.md."
    )
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Same as default: flags + LR labs (no timed soak)",
    )
    parser.add_argument(
        "--start-2h",
        action="store_true",
        help="Operator path for timed lab 2h (refuse until compose wired + B1)",
    )
    args = parser.parse_args()

    rc = _check_prod_flags_off()
    if rc != 0:
        return rc
    rc = _check_lab_compose()
    if rc != 0:
        return rc
    rc = _check_lr_profile_doc()
    if rc != 0:
        return rc
    rc = _check_compose_isolation()
    if rc != 0:
        return rc
    rc = _run_labs()
    if rc != 0:
        return rc
    rc = _run_long_range_unit_smoke()
    if rc != 0:
        return rc

    if args.start_2h:
        return _refuse_start_2h()

    print(
        "OK: long_range_lab_2h_harness PREFLIGHT PASS "
        "(2h soak NOT started; not prod mesh; not BLS)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
