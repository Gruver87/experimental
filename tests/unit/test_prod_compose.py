#!/usr/bin/env python3
"""Production Docker/K8s manifest checks."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_prod_compose_includes_relayer_sidecar():
    text = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "relayer:" in text
    assert "profiles:" in text
    assert "- bridge" in text
    assert "BRIDGE_ENABLED" in text
    assert "BRIDGE_REQUIRE_L1_PROOF" in text
    assert "condition: service_healthy" in text
    assert "bridge_relayer.py" in text
    assert "ABS_REQUIRE_NATIVE_CRYPTO" in text
    assert "ROCKSDB_BLOCK_CACHE_MB" in text
    assert "ROCKSDB_WRITE_BUFFER_MB" in text
    assert "ROCKSDB_COLUMN_FAMILIES" in text
    assert "P2P_MAX_MESSAGES_PER_SEC" in text
    assert "P2P_BAN_SECONDS" in text
    assert "P2P_RATE_LIMIT_STRIKES" in text
    assert "P2P_EVICT_MIN_SCORE" in text


def test_docker_prod_node_bridge_disabled_by_default():
    cfg = json.loads((ROOT / "docker" / "node.prod.json").read_text(encoding="utf-8"))
    assert cfg.get("bridge_enabled") is False


def test_prod_mesh_compose_has_three_nodes():
    text = (ROOT / "docker-compose.prod.3node.yml").read_text(encoding="utf-8")
    assert "node1:" in text
    assert "node2:" in text
    assert "node3:" in text
    assert "prod_mesh/wallets/validator-1.wallet.json" in text
    assert "BRIDGE_ENABLED" in text
    assert "ABS_PROD_IMAGE" in text
    assert "Dockerfile.prod" in text
    assert "\n  redis:" in text
    assert "REDIS_RATE_LIMIT" in text
    assert "REDIS_URL" in text
    assert "abs-prod-mesh-redis" in text
    # Compose bootstrap healthcheck must be /live (not /ready) — peer quorum
    # chicken-egg with depends_on: node1 healthy before node2/3 start.
    assert "health/live" in text
    assert text.count("health/ready") == 0


def test_k8s_includes_relayer_deployment():
    text = (ROOT / "deploy" / "k8s" / "relayer-deployment.yaml").read_text(encoding="utf-8")
    assert "abs-bridge-relayer" in text
    assert "--watch-l1" in text
    assert "BRIDGE_L1_QUEUE_HTTP" in text
    kustomize = (ROOT / "deploy" / "k8s" / "kustomization.yaml").read_text(encoding="utf-8")
    assert "relayer-deployment.yaml" in kustomize


def test_dockerfile_prod_requires_native_crypto():
    text = (ROOT / "Dockerfile.prod").read_text(encoding="utf-8")
    assert "ABS_REQUIRE_NATIVE_CRYPTO=true" in text
    assert "/health/ready" in text
    assert "type=cache" in text
    assert "cargo fetch" in text


def test_prod_gate_requires_rocksdb_on_all_prod_profiles():
    import subprocess
    import sys

    from runtime.mainnet_constants import MAINNET_V1_CHAIN_ID

    proc = subprocess.run(
        [sys.executable, "scripts/prod_gate.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for name in (
        "node.prod.example.json",
        "node.prod.mainnet-v1.example.json",
        "node.prod.mainnet-v1.bridge.example.json",
        "docker/node.prod.json",
        "docker/node.prod.mesh1.json",
    ):
        cfg = json.loads((ROOT / name).read_text(encoding="utf-8"))
        assert cfg.get("db_engine") == "rocksdb", name
        assert int(cfg.get("chain_id", 0)) == MAINNET_V1_CHAIN_ID, name


def test_k8s_prod_gate_passes():
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "scripts/k8s_prod_gate.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_p2ptls_overlays_have_fail_closed_and_bind_identity():
    for name in (
        "docker-compose.prod.p2ptls.yml",
        "docker-compose.prod.3node.p2ptls.yml",
    ):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "P2P_TLS_FAIL_CLOSED" in text, name
        assert "P2P_TLS_BIND_IDENTITY" in text, name
        assert 'P2P_TLS_FAIL_CLOSED: "true"' in text, name
        assert 'P2P_TLS_BIND_IDENTITY: "true"' in text, name


def test_prod_single_compose_matches_node_json_knobs():
    import re

    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    cfg = json.loads((ROOT / "docker" / "node.prod.json").read_text(encoding="utf-8"))

    def compose_default(key: str) -> str:
        m = re.search(rf"(?m)^\s*{re.escape(key)}:\s*(.+?)\s*$", compose)
        assert m, key
        raw = m.group(1).strip().strip('"').strip("'")
        dm = re.match(r"^\$\{[^:]+:-([^}]+)\}$", raw)
        return (dm.group(1) if dm else raw).strip().strip('"').strip("'")

    assert compose_default("P2P_MAX_MESSAGES_PER_SEC") == str(cfg["p2p_max_messages_per_sec"])
    assert compose_default("ROCKSDB_BLOCK_CACHE_MB") == str(cfg["rocksdb_block_cache_mb"])
    bridge = compose_default("BRIDGE_ENABLED")
    assert bridge.lower() == ("true" if cfg["bridge_enabled"] else "false")


def test_prod_mesh_json_declares_redis():
    for name in (
        "docker/node.prod.mesh1.json",
        "docker/node.prod.mesh2.json",
        "docker/node.prod.mesh3.json",
    ):
        cfg = json.loads((ROOT / name).read_text(encoding="utf-8"))
        assert cfg.get("redis_rate_limit_enabled") is True, name
        assert str(cfg.get("redis_url") or "").startswith("redis://"), name


def test_prod_mesh_json_column_families_armed():
    for name in (
        "docker/node.prod.json",
        "docker/node.prod.mesh1.json",
        "docker/node.prod.mesh2.json",
        "docker/node.prod.mesh3.json",
        "deploy/k8s/node.prod.k8s.json",
    ):
        cfg = json.loads((ROOT / name).read_text(encoding="utf-8"))
        assert cfg.get("rocksdb_column_families") is True, name


def test_prod_mesh_requires_redis_rl():
    cfg = __import__("runtime.config", fromlist=["Config"]).Config()
    cfg.deployment_mode = "prod"
    cfg.mesh_min_peers_before_mine = 2
    cfg.require_wallet_file = False
    cfg.rpc_api_key_required = False
    cfg.redis_rate_limit_enabled = False
    errs = cfg.validate()
    assert any("redis_rate_limit_enabled" in e for e in errs)
