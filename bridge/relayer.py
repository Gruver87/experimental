#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bridge relayer core — oracle callbacks with prod L1-proof fail-closed."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from bridge.l1_rpc import (
    chain_rpc_url,
    is_tx_confirmed,
    load_l1_queue,
    min_confirmations,
    save_l1_queue,
)
from runtime.amount import money_abs
from bridge.oracle_auth import sign_payload


def l1_queue_http_mode() -> bool:
    from runtime.env_loader import env_bool

    return env_bool("BRIDGE_L1_QUEUE_HTTP", False)


def fetch_l1_queue(base: str, queue_path: str) -> Dict[str, list]:
    if l1_queue_http_mode():
        data = http_get_json(f"{base.rstrip('/')}/bridge/l1-queue")
        queue = data.get("queue") if isinstance(data, dict) else None
        if not isinstance(queue, dict):
            return {"outbound": [], "incoming": []}
        return {
            "outbound": list(queue.get("outbound", [])),
            "incoming": list(queue.get("incoming", [])),
        }
    return load_l1_queue(queue_path)


def persist_l1_queue(base: str, secret: str, queue_path: str, queue: Dict[str, list]) -> None:
    if l1_queue_http_mode():
        oracle_post(base, "/bridge/oracle/l1-queue-sync", queue, secret)
        return
    save_l1_queue(queue_path, queue)


def relayer_require_l1_proof() -> bool:
    from runtime.env_loader import env_bool

    return env_bool("BRIDGE_REQUIRE_L1_PROOF", False)


def http_get_json(url: str, timeout: float = 10.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def oracle_post(base: str, path: str, payload: dict, secret: str, timeout: float = 15.0) -> dict:
    body = json.dumps(payload).encode()
    sig = sign_payload(secret, body)
    req = urllib.request.Request(
        f"{base.rstrip('/')}{path}",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Bridge-Oracle-Signature": sig,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return {"error": exc.read().decode(), "status": exc.code}


def _cfg_proxy_from_status(status: dict) -> Any:
    class _Proxy:
        is_production = status.get("deployment_mode") == "prod"
        bridge_enabled = bool(status.get("bridge_enabled", False))
        bridge_require_l1_proof = relayer_require_l1_proof()

    return _Proxy()


def check_relayer_readiness(
    api_url: str,
    secret: str,
    *,
    probe_l1: bool = True,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Preflight for scripts/bridge_relayer.py and GET /bridge/relayer/status."""
    errors: List[str] = []
    node: Dict[str, Any] = {}

    if not (secret or "").strip():
        errors.append("BRIDGE_ORACLE_SECRET missing")

    try:
        node = http_get_json(f"{api_url.rstrip('/')}/status", timeout=timeout)
    except Exception as exc:
        errors.append(f"node unreachable: {exc}")

    if node:
        if not node.get("bridge_enabled"):
            errors.append("bridge disabled on node")
        if node.get("deployment_mode") == "prod" and node.get("bridge_mode") != "rust":
            errors.append("prod node must use rust bridge mode")
        if node.get("deployment_mode") == "prod" and not node.get("bridge_oracle_enabled"):
            errors.append("node missing BRIDGE_ORACLE_SECRET")

    l1_rpc: Dict[str, Any] = {"configured": False, "ok": True, "required": False}
    try:
        from bridge.health import check_l1_rpc_health

        cfg_proxy = _cfg_proxy_from_status(node) if node else None
        if probe_l1 and cfg_proxy is not None:
            l1_rpc = check_l1_rpc_health(cfg_proxy, timeout=min(timeout, 3.0))
        elif cfg_proxy is not None:
            l1_rpc = check_l1_rpc_health(cfg_proxy, timeout=0.1)
            l1_rpc.pop("probes", None)
    except Exception as exc:
        errors.append(f"l1 rpc health check failed: {exc}")

    if l1_rpc.get("required") and not l1_rpc.get("ok"):
        errors.append(l1_rpc.get("error") or "L1 RPC not ready")

    require_l1 = relayer_require_l1_proof()
    return {
        "ok": not errors,
        "errors": errors,
        "require_l1_proof": require_l1,
        "blind_pending_confirm_allowed": not require_l1,
        "node": {
            "deployment_mode": node.get("deployment_mode"),
            "bridge_mode": node.get("bridge_mode"),
            "bridge_enabled": node.get("bridge_enabled"),
            "height": node.get("height"),
        },
        "l1_rpc": l1_rpc,
    }


def process_pending(
    base: str,
    secret: str,
    dry_run: bool = False,
    *,
    require_l1_proof: Optional[bool] = None,
) -> int:
    """Confirm pending locks via oracle — skipped in prod L1-proof mode."""
    if require_l1_proof is None:
        require_l1_proof = relayer_require_l1_proof()
    if require_l1_proof:
        print(
            "Skip blind pending confirm (BRIDGE_REQUIRE_L1_PROOF=true); "
            "use --watch-l1 for L1-backed confirmation"
        )
        return 0

    locks = http_get_json(f"{base.rstrip('/')}/bridge/locks").get("locks", [])
    pending = [lock for lock in locks if (lock.get("status") or "pending") == "pending"]
    if not pending:
        print("No pending bridge locks")
        return 0

    confirmed = 0
    for lock in pending:
        tx = lock.get("tx_hash", "")
        if not tx:
            continue
        print(
            f"Confirm lock {tx[:16]}… amount={lock.get('amount')} "
            f"chain={lock.get('to_chain')}"
        )
        if dry_run:
            continue
        result = oracle_post(base, "/bridge/oracle/confirm-lock", {"tx_hash": tx}, secret)
        if result.get("confirmed") or result.get("success"):
            confirmed += 1
            print(f"  OK: {result}")
        else:
            print(f"  FAIL: {result}")
    return confirmed


def process_l1_queue(
    base: str,
    secret: str,
    queue_path: str,
    dry_run: bool = False,
) -> int:
    """Watch L1 RPC for queued outbound/incoming bridge proofs."""
    queue = fetch_l1_queue(base, queue_path)
    outbound = queue.get("outbound", [])
    incoming = queue.get("incoming", [])
    if not outbound and not incoming:
        print("L1 queue empty")
        return 0

    need = min_confirmations()
    processed = 0
    remaining_out = []
    for item in outbound:
        l1_tx = item.get("l1_tx_hash", "")
        abs_tx = item.get("abs_tx_hash", item.get("tx_hash", ""))
        chain = item.get("chain", item.get("to_chain", "ethereum"))
        rpc = item.get("rpc_url") or chain_rpc_url(chain)
        if not l1_tx or not abs_tx:
            remaining_out.append(item)
            continue
        if not is_tx_confirmed(rpc, l1_tx, need):
            print(f"L1 outbound wait: {l1_tx[:18]}… conf<{need} chain={chain}")
            remaining_out.append(item)
            continue
        print(f"L1 outbound ready: {l1_tx[:18]}… -> confirm {abs_tx[:18]}…")
        if dry_run:
            processed += 1
            continue
        result = oracle_post(base, "/bridge/oracle/confirm-lock", {"tx_hash": abs_tx}, secret)
        if result.get("confirmed") or result.get("success"):
            processed += 1
            print(f"  OK outbound: {result}")
        else:
            print(f"  FAIL outbound: {result}")
            remaining_out.append(item)

    remaining_in = []
    for item in incoming:
        l1_tx = item.get("l1_tx_hash", item.get("tx_hash", ""))
        recipient = item.get("recipient", item.get("to_address", ""))
        try:
            amount = money_abs(item.get("amount", 0), field="amount")
        except (TypeError, ValueError):
            remaining_in.append(item)
            continue
        from_chain = item.get("from_chain", item.get("source_chain", "ethereum"))
        tx_id = item.get("tx_id", item.get("abs_tx_hash", l1_tx))
        rpc = item.get("rpc_url") or chain_rpc_url(from_chain)
        if not l1_tx or not recipient or amount <= 0:
            remaining_in.append(item)
            continue
        if not is_tx_confirmed(rpc, l1_tx, need):
            print(f"L1 incoming wait: {l1_tx[:18]}… conf<{need} chain={from_chain}")
            remaining_in.append(item)
            continue
        print(f"L1 incoming ready: {l1_tx[:18]}… -> credit {recipient[:18]}… {amount}")
        if dry_run:
            processed += 1
            continue
        payload = {
            "tx_id": tx_id,
            "tx_hash": l1_tx,
            "recipient": recipient,
            "amount": amount,
            "from_chain": from_chain,
        }
        result = oracle_post(base, "/bridge/oracle/incoming", payload, secret)
        if result.get("confirmed") or result.get("success"):
            processed += 1
            print(f"  OK incoming: {result}")
        else:
            print(f"  FAIL incoming: {result}")
            remaining_in.append(item)

    if not dry_run:
        persist_l1_queue(
            base,
            secret,
            queue_path,
            {"outbound": remaining_out, "incoming": remaining_in},
        )
    return processed
