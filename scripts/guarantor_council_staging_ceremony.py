#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Staging ceremony: POST /council/genesis-mint on Profile C node (778889).

Requires running staging compose (:19080) and admin JWT when jwt_enforce_admin.

Usage:
  docker compose -p abs-staging-app -f docker-compose.staging.app.yml up -d --build
  $env:JWT_SECRET = "..."   # same as container
  python scripts/guarantor_council_staging_ceremony.py --base-url http://127.0.0.1:19080

Dry-run (stats + manifest only):
  python scripts/guarantor_council_staging_ceremony.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
STAGING_CHAIN_ID = 778889
DEFAULT_BASE = "http://127.0.0.1:19080"


def _get(url: str, timeout: float = 30.0) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url: str, body: Dict[str, Any], token: str, timeout: float = 120.0) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"error": raw or exc.reason}
        payload["_http_status"] = exc.code
        return payload


def _mint_jwt(secret: str) -> str:
    env = os.environ.copy()
    env["JWT_SECRET"] = secret
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "mint_admin_jwt.py"), "--role", "admin"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "mint_admin_jwt failed")
    return proc.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Council genesis mint ceremony (staging)")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help="Staging HTTP base URL")
    parser.add_argument("--jwt", default="", help="Admin Bearer token (or use JWT_SECRET)")
    parser.add_argument("--jwt-secret", default="", help="JWT_SECRET for mint_admin_jwt.py")
    parser.add_argument("--dry-run", action="store_true", help="Preflight only; no POST mint")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    print(f"=== guarantor_council_staging_ceremony (ADR 0022) ===")
    print(f"base={base}")

    try:
        manifest = _get(f"{base}/council/manifest?summary=1")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"FAIL: staging node unreachable at {base}: {exc}")
        print("Hint: docker compose -p abs-staging-app -f docker-compose.staging.app.yml up -d")
        return 1

    if not manifest.get("ok"):
        print(f"FAIL: manifest endpoint: {manifest}")
        return 1
    if manifest.get("chain_id_staging") != STAGING_CHAIN_ID:
        print(f"FAIL: expected chain_id_staging {STAGING_CHAIN_ID}, got {manifest.get('chain_id_staging')}")
        return 1

    print(f"  OK: manifest supply_cap={manifest.get('supply_cap')} sha={manifest.get('manifest_tokens_sha256', '')[:16]}...")

    try:
        stats = _get(f"{base}/council/stats")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"FAIL: /council/stats: {exc}")
        return 1

    print(f"  OK: council minted_count={stats.get('minted_count')} genesis_complete={stats.get('genesis_complete')}")

    if stats.get("genesis_complete"):
        print("RESULT: PASS (already minted — idempotent skip)")
        return 0

    if args.dry_run:
        print("RESULT: PASS (dry-run preflight)")
        return 0

    secret = (args.jwt_secret or os.environ.get("JWT_SECRET", "")).strip()
    token = args.jwt.strip()
    if not token:
        if not secret:
            print("FAIL: set --jwt or JWT_SECRET / --jwt-secret for genesis-mint POST")
            return 1
        token = _mint_jwt(secret)

    result = _post_json(f"{base}/council/genesis-mint", {}, token)
    if result.get("ok") is not True:
        err = result.get("error", result)
        if result.get("_http_status") == 401:
            print("FAIL: JWT required — set JWT_SECRET to match staging container")
        print(f"FAIL: genesis-mint: {err}")
        return 1

    print(f"  OK: minted={result.get('minted')} collection={result.get('collection_id')}")

    stats2 = _get(f"{base}/council/stats")
    if not stats2.get("genesis_complete"):
        print(f"FAIL: post-mint genesis_complete false: {stats2}")
        return 1
    if stats2.get("minted_count") != 87:
        print(f"FAIL: minted_count {stats2.get('minted_count')} != 87")
        return 1

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
