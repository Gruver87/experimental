#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Staging ceremony: POST /council/genesis-mint on Profile C node (778889).

Requires running staging compose (:19080). Admin JWT only when jwt_enforce_admin.

Usage:
  docker compose -p abs-staging-app -f docker-compose.staging.app.yml up -d --build
  python scripts/guarantor_council_staging_ceremony.py --base-url http://127.0.0.1:19080

Optional (when jwt_enforce_admin=true on staging JSON):
  $env:JWT_SECRET = "..."   # >= 32 bytes, same as container

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
MIN_HS256_SECRET_BYTES = 32


def _get(url: str, timeout: float = 30.0) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(
    url: str,
    body: Dict[str, Any],
    token: Optional[str] = None,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers=headers,
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


def _jwt_enforced(base: str) -> bool:
    try:
        status = _get(f"{base}/status")
    except (urllib.error.URLError, TimeoutError, OSError):
        return True
    return bool(status.get("jwt_enforce_admin"))


def _resolve_admin_token(
    *,
    base: str,
    jwt_arg: str,
    jwt_secret_arg: str,
) -> Optional[str]:
    """Return Bearer token when jwt_enforce_admin; else None (open POST on staging)."""
    if not _jwt_enforced(base):
        print("  OK: jwt_enforce_admin=false — genesis-mint without admin JWT")
        return None

    token = jwt_arg.strip()
    if token:
        return token

    secret = jwt_secret_arg.strip() or os.environ.get("JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError(
            "staging jwt_enforce_admin=true — set --jwt or JWT_SECRET "
            "(>= 32 bytes, same as container)"
        )

    secret_len = len(secret.encode("utf-8"))
    if secret_len < MIN_HS256_SECRET_BYTES:
        raise RuntimeError(
            f"JWT_SECRET too short for HS256 "
            f"(need >= {MIN_HS256_SECRET_BYTES} bytes, got {secret_len}). "
            "Rotate to >=32 bytes in .env and restart staging, or pass --jwt"
        )

    return _mint_jwt(secret)


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

    try:
        token = _resolve_admin_token(
            base=base,
            jwt_arg=args.jwt,
            jwt_secret_arg=args.jwt_secret,
        )
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 1

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
