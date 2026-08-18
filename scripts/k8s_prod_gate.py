#!/usr/bin/env python3
"""Validate Kubernetes prod manifests for mainnet-ready settings."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
K8S = ROOT / "deploy" / "k8s"


def main() -> int:
    from runtime.mainnet_constants import MAINNET_V1_CHAIN_ID

    errors: list[str] = []

    cfg_path = K8S / "node.prod.k8s.json"
    if not cfg_path.is_file():
        errors.append("missing deploy/k8s/node.prod.k8s.json")
    else:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        if cfg.get("deployment_mode") != "prod":
            errors.append("node.prod.k8s.json: deployment_mode must be prod")
        if int(cfg.get("chain_id", 0) or 0) != MAINNET_V1_CHAIN_ID:
            errors.append(f"node.prod.k8s.json: chain_id must be {MAINNET_V1_CHAIN_ID}")
        if cfg.get("db_engine") != "rocksdb":
            errors.append("node.prod.k8s.json: db_engine must be rocksdb")
        if str(cfg.get("rocksdb_sync") or "").upper() != "FULL":
            errors.append("node.prod.k8s.json: rocksdb_sync must be FULL")
        if int(cfg.get("rocksdb_block_cache_mb", 0) or 0) <= 0:
            errors.append("node.prod.k8s.json: rocksdb_block_cache_mb required")
        if int(cfg.get("rocksdb_write_buffer_mb", 0) or 0) <= 0:
            errors.append("node.prod.k8s.json: rocksdb_write_buffer_mb required")
        if cfg.get("rocksdb_column_families") is not True:
            errors.append(
                "node.prod.k8s.json: rocksdb_column_families must be true"
            )
        for key in (
            "p2p_max_message_bytes",
            "p2p_max_messages_per_sec",
            "p2p_attest_messages_per_sec",
            "p2p_tx_messages_per_sec",
            "p2p_block_announce_messages_per_sec",
            "p2p_ban_seconds",
            "p2p_rate_limit_strikes",
        ):
            if key not in cfg:
                errors.append(f"node.prod.k8s.json: {key} required")
            elif int(cfg.get(key) or 0) <= 0:
                errors.append(f"node.prod.k8s.json: {key} must be > 0")
        if not cfg.get("follower_genesis_sync"):
            errors.append("node.prod.k8s.json: follower_genesis_sync required for k8s scale-out")
        if cfg.get("p2p_tls_enabled") is not True:
            errors.append("node.prod.k8s.json: p2p_tls_enabled must be true")
        if cfg.get("bridge_enabled") is not False:
            errors.append("node.prod.k8s.json: bridge_enabled must be false until L1 audit")
        if cfg.get("tip_safety_enforce") is not True:
            errors.append("node.prod.k8s.json: tip_safety_enforce must be true")
        for key in ("p2p_tls_cert_path", "p2p_tls_key_path", "p2p_tls_ca_path"):
            if not str(cfg.get(key) or "").strip():
                errors.append(f"node.prod.k8s.json: {key} required when P2P TLS enabled")

    cm = (K8S / "configmap.yaml").read_text(encoding="utf-8")
    if 'DEPLOYMENT_MODE: "prod"' not in cm:
        errors.append("configmap.yaml: DEPLOYMENT_MODE must be prod")
    if 'DB_ENGINE: "rocksdb"' not in cm:
        errors.append("configmap.yaml: DB_ENGINE must be rocksdb")
    if f'CHAIN_ID: "{MAINNET_V1_CHAIN_ID}"' not in cm:
        errors.append(f"configmap.yaml: CHAIN_ID must be {MAINNET_V1_CHAIN_ID}")
    if "ABS_REQUIRE_NATIVE_CRYPTO" not in cm:
        errors.append("configmap.yaml: ABS_REQUIRE_NATIVE_CRYPTO required")
    if 'TIP_SAFETY_ENFORCE: "true"' not in cm:
        errors.append('configmap.yaml: TIP_SAFETY_ENFORCE must be "true"')
    if 'BRIDGE_ENABLED: "false"' not in cm:
        errors.append('configmap.yaml: BRIDGE_ENABLED must be "false"')
    if 'ROCKSDB_COLUMN_FAMILIES: "true"' not in cm:
        errors.append('configmap.yaml: ROCKSDB_COLUMN_FAMILIES must be "true"')
    for key in (
        "ROCKSDB_BLOCK_CACHE_MB",
        "ROCKSDB_WRITE_BUFFER_MB",
        "ROCKSDB_COLUMN_FAMILIES",
        "P2P_MAX_MESSAGES_PER_SEC",
        "P2P_BAN_SECONDS",
        "P2P_RATE_LIMIT_STRIKES",
        "P2P_EVICT_MIN_SCORE",
    ):
        if key not in cm:
            errors.append(f"configmap.yaml: {key} required")
    if "REDIS_RATE_LIMIT" not in cm:
        errors.append("configmap.yaml: REDIS_RATE_LIMIT required")
    if "REDIS_URL" not in cm:
        errors.append("configmap.yaml: REDIS_URL required")

    redis_yaml = (K8S / "redis.yaml").read_text(encoding="utf-8")
    if "readinessProbe" not in redis_yaml or "redis-cli" not in redis_yaml:
        errors.append("redis.yaml: readinessProbe with redis-cli ping required")
    if "livenessProbe" not in redis_yaml:
        errors.append("redis.yaml: livenessProbe required")

    sts = (K8S / "statefulset.yaml").read_text(encoding="utf-8")
    if "readinessProbe" not in sts or "/health/ready" not in sts:
        errors.append("statefulset.yaml: readinessProbe /health/ready required")
    if "livenessProbe" not in sts or "/health/live" not in sts:
        errors.append("statefulset.yaml: livenessProbe /health/live required")
    if "entrypoint.sh" not in sts:
        errors.append("statefulset.yaml: must use deploy/k8s/entrypoint.sh")
    if "wait-redis" not in sts:
        errors.append("statefulset.yaml: initContainer wait-redis required")
    if "abs-p2p-tls" not in sts or "p2p_tls_secrets" not in sts:
        errors.append("statefulset.yaml: abs-p2p-tls secret mount required")
    if "projected:" not in sts or "abs-p2p-tls-node-0" not in sts:
        errors.append("statefulset.yaml: projected per-pod P2P TLS secrets required")

    cm_json_start = cm.find("node.prod.k8s.json:")
    if cm_json_start < 0:
        errors.append("configmap.yaml: embedded node.prod.k8s.json missing")
    else:
        cm_json_blob = cm[cm_json_start:]
        for key in (
            "p2p_tls_enabled",
            "redis_rate_limit_enabled",
            "redis_url",
            "p2p_tls_cert_path",
            "rust_bridge_path",
            "state_root_legacy_cutoff_height",
        ):
            if key not in cm_json_blob:
                errors.append(f"configmap.yaml: embedded node JSON missing {key}")
        # Freeze embedded JSON == deploy/k8s/node.prod.k8s.json (key/value).
        brace = cm.find("{", cm_json_start)
        if brace < 0:
            errors.append("configmap.yaml: embedded JSON object missing")
        else:
            depth = 0
            end = None
            for idx, ch in enumerate(cm[brace:]):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = brace + idx + 1
                        break
            if end is None:
                errors.append("configmap.yaml: embedded JSON not closed")
            else:
                try:
                    embedded = json.loads(cm[brace:end])
                    file_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                    if embedded != file_cfg:
                        only_file = sorted(set(file_cfg) - set(embedded))
                        only_emb = sorted(set(embedded) - set(file_cfg))
                        diffs = sorted(
                            k
                            for k in set(file_cfg) & set(embedded)
                            if file_cfg[k] != embedded[k]
                        )
                        errors.append(
                            "configmap.yaml embedded JSON != node.prod.k8s.json "
                            f"(only_file={only_file[:8]} only_emb={only_emb[:8]} "
                            f"diffs={diffs[:8]})"
                        )
                except (OSError, json.JSONDecodeError, TypeError) as exc:
                    errors.append(f"configmap.yaml embedded JSON parse failed: {exc}")

    entry = (K8S / "entrypoint.sh").read_text(encoding="utf-8")
    if "p2p_tls_secrets" not in entry:
        errors.append("entrypoint.sh: must wire P2P TLS secrets by pod ordinal")

    cert_mgr = K8S / "cert-manager-p2p.example.yaml"
    if not cert_mgr.is_file():
        errors.append("missing deploy/k8s/cert-manager-p2p.example.yaml")
    elif "cert-manager.io/v1" not in cert_mgr.read_text(encoding="utf-8"):
        errors.append("cert-manager-p2p.example.yaml: must document cert-manager Certificate")

    perpod = K8S / "cert-manager-p2p-perpod.example.yaml"
    if not perpod.is_file():
        errors.append("missing deploy/k8s/cert-manager-p2p-perpod.example.yaml")
    else:
        perpod_txt = perpod.read_text(encoding="utf-8")
        for ordinal in ("abs-node-0-p2p-tls", "abs-node-1-p2p-tls", "abs-node-2-p2p-tls"):
            if ordinal not in perpod_txt:
                errors.append(f"cert-manager-p2p-perpod.example.yaml: missing {ordinal}")

    merge_job = K8S / "p2p-tls-merge-job.example.yaml"
    merge_sh = K8S / "merge_p2p_tls_secrets.sh"
    if not merge_sh.is_file():
        errors.append("missing deploy/k8s/merge_p2p_tls_secrets.sh")
    if not merge_job.is_file() or "abs-p2p-tls-merge" not in merge_job.read_text(encoding="utf-8"):
        errors.append("missing deploy/k8s/p2p-tls-merge-job.example.yaml")

    if errors:
        print("FAIL: k8s prod gate")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("OK: k8s prod gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
