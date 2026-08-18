#!/usr/bin/env python3
"""Run inside a prod-mesh container. Exit 0 only if get_state_root is committed-root."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

_app = Path("/app")
if (_app / "core" / "blockchain.py").is_file() and "/app" not in sys.path:
    sys.path.insert(0, "/app")

from core.blockchain import Blockchain

NEEDLE = "Last committed canonical root"


def main() -> int:
    src = inspect.getsource(Blockchain.get_state_root)
    if NEEDLE not in src:
        print("COMMITTED_STATE_ROOT_MISSING")
        return 1
    if "get_live_state_root_meta" not in src:
        print("COMMITTED_STATE_ROOT_NO_META")
        return 1
    if "return self._compute_state_root_from_db()" in src:
        print("COMMITTED_STATE_ROOT_STILL_SCANS")
        return 1
    print("COMMITTED_STATE_ROOT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
