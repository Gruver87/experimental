#!/usr/bin/env python3
"""Static production gate for fail-closed prod configuration."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROD_FILES = [
    "docker/node.prod.json",
    "docker/node.prod.mesh1.json",
    "docker/node.prod.mesh2.json",
    "docker/node.prod.mesh3.json",
    "node.prod.example.json",
    "node.prod.mainnet-v1.example.json",
    "node.prod.mainnet-v1.bridge.example.json",
]

MAINNET_V1_PROFILE = "node.prod.mainnet-v1.example.json"

BRIDGE_PROD_FILES = [
    "node.prod.mainnet-v1.bridge.example.json",
]

BLOCKED_FEATURES = [
    "feature_zk",
    "feature_sharding",
    "feature_oracles",
    "feature_wasm",
    "feature_plasma",
    "feature_lightning",
    "feature_pq",
    "feature_mev",
    "feature_ai_agents",
    "feature_ai_validator",
]

REQUIRED_TRUE = [
    "require_signatures",
    "enforce_proposer",
    "verify_peer_state_root",
    "state_root_strict_p2p",
    "rpc_api_key_required",
    "jwt_enforce_admin",
    "require_wallet_file",
    "bridge_require_l1_proof",
    "require_native_crypto",
    "p2p_native_transport",
    "evm_create2_eip1014",
    "evm_require_deploy_salt",
    "tip_safety_enforce",
]

DEVNET_CHAIN_ID = 77777


def load_json(path: str) -> dict:
    with (ROOT / path).open(encoding="utf-8") as f:
        return json.load(f)


def check_file(path: str) -> list[str]:
    from runtime.mainnet_constants import MAINNET_V1_CHAIN_ID

    cfg = load_json(path)
    errors: list[str] = []

    if cfg.get("deployment_mode") != "prod":
        errors.append(f"{path}: deployment_mode must be prod")
    if cfg.get("bridge_enabled", True) and cfg.get("bridge_mode") != "rust":
        errors.append(f"{path}: prod bridge must use rust mode or be disabled")

    for key in REQUIRED_TRUE:
        if cfg.get(key) is not True:
            errors.append(f"{path}: {key} must be true")

    for key in BLOCKED_FEATURES:
        if cfg.get(key, False):
            errors.append(f"{path}: {key} must be false in prod")

    origins = cfg.get("cors_origins", [])
    if not origins:
        errors.append(f"{path}: cors_origins must be non-empty in prod")
    if origins == ["*"] or "*" in origins:
        errors.append(f"{path}: wildcard CORS is forbidden in prod")
    if any(str(origin).startswith(("http://localhost", "http://127.")) for origin in origins):
        errors.append(f"{path}: localhost CORS is forbidden in prod")

    if not cfg.get("validators_manifest_path"):
        errors.append(f"{path}: validators_manifest_path is required in prod")

    chain_id = int(cfg.get("chain_id", 0) or 0)
    if chain_id == DEVNET_CHAIN_ID:
        errors.append(
            f"{path}: chain_id {DEVNET_CHAIN_ID} is devnet default; "
            "assign unique mainnet chain_id before public launch"
        )
    elif chain_id != MAINNET_V1_CHAIN_ID:
        errors.append(
            f"{path}: chain_id {chain_id} must be MAINNET_V1_CHAIN_ID ({MAINNET_V1_CHAIN_ID})"
        )

    if path == MAINNET_V1_PROFILE and cfg.get("bridge_enabled"):
        errors.append(
            f"{path}: bridge_enabled must be false until L1 lock/mint contracts "
            "are deployed (use node.prod.mainnet-v1.bridge.example.json for cutover lab)"
        )

    if path in BRIDGE_PROD_FILES:
        if not cfg.get("bridge_enabled"):
            errors.append(f"{path}: bridge_enabled must be true for bridge cutover profile")
        if not cfg.get("bridge_probe_l1_rpc"):
            errors.append(f"{path}: bridge_probe_l1_rpc must be true for bridge cutover profile")

    mode = str(cfg.get("consensus_mode", "auto") or "auto").strip().lower()
    if mode == "parallel":
        errors.append(f"{path}: consensus_mode=parallel forbidden in prod (use unified or auto)")

    if cfg.get("db_engine", "sqlite") != "rocksdb":
        errors.append(f"{path}: db_engine must be rocksdb in prod")

    if cfg.get("allow_state_root_rewrite") is True:
        errors.append(f"{path}: allow_state_root_rewrite must not be true in prod")

    if cfg.get("allow_insecure_public_bind") is True:
        errors.append(f"{path}: allow_insecure_public_bind must not be true in prod")

    if int(cfg.get("rate_limit_rpm", 120) or 0) <= 0:
        errors.append(f"{path}: rate_limit_rpm must be > 0 in prod")

    # ADR 0020: Experimental mesh uses libp2p Noise. Native mTLS overlay is not default.
    if cfg.get("feature_libp2p") is True:
        if cfg.get("p2p_tls_enabled") is True:
            errors.append(
                f"{path}: ADR 0020 libp2p mesh must keep p2p_tls_enabled=false "
                "(Noise is session crypto; mTLS overlay is split-brain)"
            )
        if cfg.get("feature_long_range") is True:
            errors.append(f"{path}: feature_long_range must stay false")
    else:
        # Prod profiles require P2P TLS(+mTLS) for mainnet-prep wire.
        if cfg.get("p2p_tls_enabled") is not True:
            errors.append(f"{path}: p2p_tls_enabled must be true for prod profiles")
        if cfg.get("p2p_tls_require_client_cert") is not True:
            errors.append(f"{path}: p2p_tls_require_client_cert must be true for prod mTLS")
        for key in ("p2p_tls_cert_path", "p2p_tls_key_path", "p2p_tls_ca_path"):
            if not str(cfg.get(key) or "").strip():
                errors.append(f"{path}: {key} required when P2P TLS is enabled")
        if cfg.get("p2p_tls_fail_closed") is False:
            errors.append(f"{path}: p2p_tls_fail_closed must not be false in prod")
        if cfg.get("p2p_tls_bind_identity") is False:
            errors.append(f"{path}: p2p_tls_bind_identity must not be false in prod")

    if "mesh1" in path.replace("\\", "/"):
        if int(cfg.get("mesh_min_peers_before_mine", 0) or 0) < 1:
            errors.append(
                f"{path}: mesh_min_peers_before_mine must be >= 1 for mesh1 miner"
            )
    if "mesh2" in path.replace("\\", "/") or "mesh3" in path.replace("\\", "/"):
        if cfg.get("follower_genesis_sync") is not True:
            errors.append(f"{path}: follower_genesis_sync must be true for mesh followers")

    return errors


def check_mesh_compose_redis() -> list[str]:
    """Prod 3-node mesh must wire Redis for distributed rate limiting."""
    errors: list[str] = []
    path = ROOT / "docker-compose.prod.3node.yml"
    if not path.is_file():
        return [f"missing {path.name}"]
    text = path.read_text(encoding="utf-8")
    if "\n  redis:" not in text:
        errors.append("docker-compose.prod.3node.yml missing redis service")
    if "REDIS_RATE_LIMIT" not in text:
        errors.append("docker-compose.prod.3node.yml missing REDIS_RATE_LIMIT")
    if "REDIS_URL" not in text:
        errors.append("docker-compose.prod.3node.yml missing REDIS_URL")
    if "abs-prod-mesh-redis" not in text:
        errors.append("docker-compose.prod.3node.yml missing abs-prod-mesh-redis volume")
    return errors


def check_sync_consistency_surface() -> list[str]:
    """ADR 0003: sync consistency + solicit hub modules must exist."""
    errors: list[str] = []
    required = (
        "sync/ports.py",
        "sync/consistency/machine.py",
        "sync/consistency/service.py",
        "sync/solicit.py",
        "docs/adr/0003-sync-consistency.md",
    )
    for rel in required:
        if not (ROOT / rel).is_file():
            errors.append(f"missing sync consistency surface: {rel}")
    p2p = (ROOT / "network" / "p2p_node.py").read_text(encoding="utf-8")
    if "solicit_hub.fulfill_or_reject" not in p2p:
        errors.append("p2p_node.py missing SyncSolicitHub fulfill_or_reject wiring")
    if "ConsistencyService" not in (ROOT / "sync" / "sync_engine.py").read_text(
        encoding="utf-8"
    ):
        errors.append("sync_engine.py must use ConsistencyService")
    return errors


def main() -> int:
    errors: list[str] = []
    for path in PROD_FILES:
        errors.extend(check_file(path))
    errors.extend(check_mesh_compose_redis())
    errors.extend(check_sync_consistency_surface())

    if errors:
        print("FAIL: production gate")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("OK: production gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
