#!/usr/bin/env python3
"""Disaster-recovery drill: backup chain DB and verify restored tip."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.blockchain import Blockchain  # noqa: E402
from kernel.event_bus import EventBus  # noqa: E402
from runtime.config import Config  # noqa: E402
from storage.database import Database  # noqa: E402


def run_backup_drill(source: str | None = None) -> int:
    """Backup a chain DB (or fresh temp chain) and verify tip survives roundtrip."""
    tmp = tempfile.mkdtemp(prefix="abs_dr_drill_")
    if source and os.path.isfile(source):
        chain_path = os.path.abspath(source)
        cfg = Config()
        cfg.db_path = chain_path
    else:
        chain_path = os.path.join(tmp, "chain.db")
        cfg = Config()
        cfg.db_path = chain_path
        cfg.chain_id = 778888
        db = Database(chain_path)
        db.initialize()
        Blockchain(cfg, db, EventBus())
        db.close()

    backup_path = os.path.join(tmp, "chain.backup.db")
    src_db = Database(chain_path)
    src_db.initialize()
    try:
        tip_before = int(src_db.get_chain_tip() or 0)
        genesis_before = src_db.get_block(0)
        try:
            src_db.backup_to(backup_path)
        except Exception as exc:
            # Fail-closed PersistError (or any backup failure) — never soft False.
            print(f"FAIL: backup_to raised: {exc}", file=sys.stderr)
            return 1
    finally:
        src_db.close()

    restored = Database(backup_path)
    restored.initialize()
    try:
        tip_after = int(restored.get_chain_tip() or 0)
        genesis_after = restored.get_block(0)
    finally:
        restored.close()

    if tip_after != tip_before:
        print(f"FAIL: tip mismatch before={tip_before} after={tip_after}", file=sys.stderr)
        return 2
    if not genesis_before or not genesis_after:
        print("FAIL: genesis block missing in source or backup", file=sys.stderr)
        return 3
    if genesis_before.get("hash") != genesis_after.get("hash"):
        print("FAIL: genesis hash mismatch after backup", file=sys.stderr)
        return 4

    print(
        f"OK: backup drill tip={tip_after} "
        f"genesis={str(genesis_after.get('hash', ''))[:16]}…"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="DR drill — backup + restore verification")
    parser.add_argument(
        "--source",
        default="",
        help="Optional live chain.db; default builds an isolated temp chain",
    )
    args = parser.parse_args()
    source = args.source.strip() or None
    return run_backup_drill(source)


if __name__ == "__main__":
    raise SystemExit(main())
