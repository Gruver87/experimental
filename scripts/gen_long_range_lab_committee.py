#!/usr/bin/env python3
"""Generate lab Ed25519 WS committee keys (ADR 0017). Never commit private keys.

Writes:
  data/long_range_lab_committee/pubkeys.json   (safe to commit)
  data/long_range_lab_committee/secrets.json   (gitignored — lab only)

Usage:
  python scripts/gen_long_range_lab_committee.py
  python scripts/gen_long_range_lab_committee.py --force
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "data" / "long_range_lab_committee"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--members", type=int, default=3)
    args = parser.parse_args()
    if args.members < 2:
        print("FAIL: need at least 2 committee members", file=sys.stderr)
        return 1

    from consensus.long_range.committee import generate_keypair, threshold_for

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pub_path = OUT_DIR / "pubkeys.json"
    sec_path = OUT_DIR / "secrets.json"
    if pub_path.is_file() and not args.force:
        print(f"OK: exists {pub_path} (use --force to regenerate)")
        return 0

    privs = []
    pubs = []
    for i in range(int(args.members)):
        priv, pub = generate_keypair()
        privs.append({"id": f"lr-committee-{i}", "private_key": priv, "public_key": pub})
        pubs.append(pub)

    thr = threshold_for(len(pubs))
    pub_path.write_text(
        json.dumps({"pubkeys": pubs, "threshold": thr}, indent=2) + "\n",
        encoding="utf-8",
    )
    sec_path.write_text(
        json.dumps({"members": privs, "threshold": thr}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OK: wrote {pub_path} (n={len(pubs)} threshold={thr})")
    print(f"OK: wrote {sec_path} (DO NOT COMMIT)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
