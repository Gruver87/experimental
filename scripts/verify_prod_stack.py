#!/usr/bin/env python3
"""Production stack readiness checks (static + optional live smoke)."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check_prod_gate() -> list[str]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "prod_gate.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return [proc.stdout.strip() or proc.stderr.strip() or "prod_gate failed"]
    return []


def check_config_validate(config_name: str = "node.prod.example.json") -> list[str]:
    from runtime.config import Config

    path = ROOT / config_name
    placeholders = {
        "JWT_SECRET": "Q" * 40,
        "RPC_API_KEYS": "R" * 40,
        "BRIDGE_ORACLE_SECRET": "S" * 40,
        "ETH_RPC_URL": "https://rpc.example.com",
        "CORS_ORIGINS": "https://explorer.example.com",
        "BRIDGE_PROBE_L1_RPC": "false",
    }
    saved = {key: os.environ.get(key) for key in placeholders}
    try:
        for key, value in placeholders.items():
            os.environ[key] = value
        cfg = Config.from_json(str(path))
        cfg.apply_env()
        errors = cfg.validate()
        bridge_candidates = [
            ROOT / "bridge" / "abs_bridge_bin.exe",
            ROOT / "bridge" / "abs_bridge_bin",
        ]
        # Only suppress rust-bridge presence/smoke errors when bridge is disabled.
        # If bridge_enabled=true, missing/invalid abs_bridge_bin must fail the gate.
        bridge_enabled = bool(getattr(cfg, "bridge_enabled", False))
        if (not bridge_enabled) and (not any(p.is_file() for p in bridge_candidates)):
            errors = [
                e
                for e in errors
                if "rust binary smoke-test" not in e and "binary missing" not in e
            ]
        return errors
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def check_docker_prod_compose() -> list[str]:
    compose = ROOT / "docker-compose.prod.yml"
    text = compose.read_text(encoding="utf-8")
    errors: list[str] = []
    for needle in ("relayer:", "BRIDGE_REQUIRE_L1_PROOF", "ABS_REQUIRE_NATIVE_CRYPTO"):
        if needle not in text:
            errors.append(f"docker-compose.prod.yml missing {needle}")
    compose_env = {
        "JWT_SECRET": "Q" * 40,
        "RPC_API_KEYS": "R" * 40,
        "BRIDGE_ORACLE_SECRET": "S" * 40,
        "ETH_RPC_URL": "https://rpc.example.com",
        "CORS_ORIGINS": "https://explorer.example.com",
    }
    saved = {key: os.environ.get(key) for key in compose_env}
    try:
        os.environ.update(compose_env)
        proc = subprocess.run(
            ["docker", "compose", "-f", str(compose), "config", "--quiet"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            errors.append(proc.stderr.strip() or "docker compose config failed")
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        errors.append("docker compose config timed out")
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
    return errors


def check_docker_prod_mesh_compose() -> list[str]:
    compose = ROOT / "docker-compose.prod.3node.yml"
    if not compose.is_file():
        return ["docker-compose.prod.3node.yml missing"]
    text = compose.read_text(encoding="utf-8")
    errors: list[str] = []
    for needle in ("node1:", "node2:", "node3:", "prod_mesh/wallets", "ABS_REQUIRE_NATIVE_CRYPTO"):
        if needle not in text:
            errors.append(f"docker-compose.prod.3node.yml missing {needle}")
    compose_env = {
        "JWT_SECRET": "Q" * 40,
        "RPC_API_KEYS": "R" * 40,
        "BRIDGE_ORACLE_SECRET": "S" * 40,
        "ETH_RPC_URL": "https://rpc.example.com",
        "CORS_ORIGINS": "https://explorer.example.com",
    }
    saved = {key: os.environ.get(key) for key in compose_env}
    try:
        os.environ.update(compose_env)
        proc = subprocess.run(
            ["docker", "compose", "-f", str(compose), "config", "--quiet"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            errors.append(proc.stderr.strip() or "docker compose prod.3node config failed")
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        errors.append("docker compose prod.3node config timed out")
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
    return errors


def check_mainnet_v1_config() -> list[str]:
    placeholders = {
        "JWT_SECRET": "Q" * 40,
        "RPC_API_KEYS": "R" * 40,
        "BRIDGE_ORACLE_SECRET": "S" * 40,
        "ETH_RPC_URL": "https://rpc.example.com",
        "CORS_ORIGINS": "https://explorer.example.com",
        "BRIDGE_PROBE_L1_RPC": "false",
    }
    saved = {key: os.environ.get(key) for key in placeholders}
    saved_pin = os.environ.pop("GENESIS_CEREMONY_HASH", None)
    try:
        for key, value in placeholders.items():
            os.environ[key] = value
        return check_config_validate("node.prod.mainnet-v1.example.json")
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        if saved_pin is not None:
            os.environ["GENESIS_CEREMONY_HASH"] = saved_pin


def check_mainnet_v1_bridge_cutover_config() -> list[str]:
    """Static check for bridge-enabled mainnet-v1 cutover profile."""
    placeholders = {
        "JWT_SECRET": "Q" * 40,
        "RPC_API_KEYS": "R" * 40,
        "BRIDGE_ORACLE_SECRET": "S" * 40,
        "ETH_RPC_URL": "https://rpc.example.com",
        "CORS_ORIGINS": "https://explorer.example.com",
        "BRIDGE_PROBE_L1_RPC": "false",
        "BRIDGE_REQUIRE_L1_EVENT": "true",
        "BRIDGE_L1_QUEUE_PATH": "data/bridge_l1_queue.json",
    }
    saved = {key: os.environ.get(key) for key in placeholders}
    saved_pin = os.environ.pop("GENESIS_CEREMONY_HASH", None)
    try:
        for key, value in placeholders.items():
            os.environ[key] = value
        errors: list[str] = []
        # Example cutover JSON keeps zero-address placeholders until L1 deploy.
        cfg_errors = check_config_validate("node.prod.mainnet-v1.bridge.example.json")
        errors.extend(
            e
            for e in cfg_errors
            if "requires a real BRIDGE_L1_LOCK_CONTRACT" not in e
        )
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            from bridge_l1_cutover import run_cutover_gate

            c_errors, _c_warnings, _meta = run_cutover_gate(
                live=False,
                probe_l1=False,
            )
            errors.extend([f"bridge_cutover:{e}" for e in c_errors])
        except Exception as exc:
            errors.append(f"bridge_cutover:{exc}")
        return errors
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        if saved_pin is not None:
            os.environ["GENESIS_CEREMONY_HASH"] = saved_pin


def check_prod_smoke_spawn() -> list[str]:
    spec = importlib.util.spec_from_file_location(
        "verify_p2p_ci", ROOT / "scripts" / "verify_p2p_ci.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(mod)
    rc = int(mod.run_prod_smoke_spawn())
    if rc != 0:
        return [f"prod_smoke_spawn exited {rc}"]
    return []


def check_prod_mesh3_spawn(ceremony_dir: str = "") -> list[str]:
    spec = importlib.util.spec_from_file_location(
        "verify_p2p_ci", ROOT / "scripts" / "verify_p2p_ci.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(mod)
    rc = int(mod.run_prod_mesh3_spawn(ceremony_dir=ceremony_dir))
    if rc != 0:
        return [f"prod_mesh3_spawn exited {rc}"]
    return []


def check_live_smoke(base: str) -> list[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    import prod_smoke

    report = prod_smoke.run_prod_smoke(base)
    return list(report.get("errors") or [])


PROD_MESH_HTTP_PORTS = (18180, 18181, 18182)


def check_live_prod_mesh() -> list[str]:
    """Live checks against Docker prod mesh on host ports :18180-:18182."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from verify_p2p_ci import _api, _probe_health

    urls = [f"http://127.0.0.1:{port}" for port in PROD_MESH_HTTP_PORTS]
    reachable = [url for url in urls if _probe_health(url)]
    errors: list[str] = []
    if not reachable:
        return ["prod_mesh: no nodes reachable on :18180-:18182 (start docker_prod_3node.ps1)"]
    if len(reachable) < len(urls):
        errors.append(f"prod_mesh: only {len(reachable)}/{len(urls)} nodes reachable")

    statuses = []
    for url in reachable:
        try:
            statuses.append(_api(f"{url}/status"))
        except OSError as exc:
            errors.append(f"prod_mesh status {url}: {exc}")

    if len(statuses) >= 2:
        heights = [int(s.get("height", 0) or 0) for s in statuses]
        heads = [
            str(s.get("head_hash") or "").lower()
            for s in statuses
            if s.get("head_hash")
        ]
        if max(heights) - min(heights) > 1:
            errors.append(f"prod_mesh height spread: {heights}")
        if heads and len(set(heads)) > 1:
            errors.append("prod_mesh head hash mismatch across nodes")
        for url, status in zip(reachable, statuses):
            if str(status.get("deployment_mode", "")).lower() != "prod":
                errors.append(
                    f"prod_mesh {url} deployment_mode={status.get('deployment_mode')!r}"
                )
            peers = int(status.get("peers", status.get("peer_count", 0)) or 0)
            if peers < 1 and len(reachable) >= 3:
                errors.append(f"prod_mesh {url} peers={peers} (expected >=1 on 3-node mesh)")

    import prod_smoke

    report = prod_smoke.run_prod_smoke(reachable[0])
    errors.extend(report.get("errors") or [])

    if len(reachable) == len(PROD_MESH_HTTP_PORTS):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "verify_p2p_ci", ROOT / "scripts" / "verify_p2p_ci.py"
        )
        vp = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(vp)
        for i, url in enumerate(reachable, start=1):
            try:
                sec, _source = vp._fetch_p2p_security(url)
            except OSError as exc:
                errors.append(f"prod_mesh {url} p2p security: {exc}")
                continue
            if not sec:
                errors.append(f"prod_mesh node{i} missing P2P security policy")

    return errors


def check_bridge_l1_live_probe(
    *,
    probe_l1: bool = False,
    probe_l1_rpc_only: bool = False,
    live: bool = False,
    base_url: str = "",
) -> list[str]:
    """Bridge L1 cutover probe (optional L1 RPC + live node checks)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from bridge_l1_live_probe import run_bridge_l1_live_probe

    errors, _warnings, _meta = run_bridge_l1_live_probe(
        probe_l1=probe_l1,
        probe_l1_rpc_only=probe_l1_rpc_only,
        live=live,
        base_url=base_url,
    )
    return [f"bridge_l1:{e}" for e in errors]


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify production stack readiness")
    parser.add_argument("--live", action="store_true", help="Also run prod_smoke against running node")
    parser.add_argument(
        "--live-prod-mesh",
        action="store_true",
        help="Live prod 3-node mesh on :18180-:18182 (implies --live on leader)",
    )
    parser.add_argument("--base-url", default=os.getenv("ABS_API_URL", "http://127.0.0.1:8080"))
    parser.add_argument(
        "--bridge-cutover",
        action="store_true",
        help="Include bridge L1 cutover static config checks",
    )
    parser.add_argument(
        "--probe-l1",
        action="store_true",
        help="With bridge cutover, probe L1 RPC and contract bytecode",
    )
    parser.add_argument(
        "--probe-l1-rpc-only",
        action="store_true",
        help="Probe ETH_RPC_URL only (contracts may stay placeholder)",
    )
    parser.add_argument(
        "--bridge-live",
        action="store_true",
        help="With bridge cutover, live checks on bridge-enabled prod node",
    )
    args = parser.parse_args()

    errors: list[str] = []
    errors.extend(check_prod_gate())
    errors.extend(check_config_validate())
    errors.extend(check_docker_prod_compose())
    if args.bridge_cutover:
        errors.extend(check_mainnet_v1_bridge_cutover_config())
    if args.probe_l1 or args.probe_l1_rpc_only or args.bridge_live:
        errors.extend(
            check_bridge_l1_live_probe(
                probe_l1=args.probe_l1,
                probe_l1_rpc_only=args.probe_l1_rpc_only and not args.probe_l1,
                live=args.bridge_live,
                base_url=args.base_url.rstrip("/"),
            )
        )
    if args.live_prod_mesh:
        errors.extend(check_live_prod_mesh())
    elif args.live:
        errors.extend(check_live_smoke(args.base_url.rstrip("/")))

    if errors:
        print("FAIL: production stack verification")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("OK: production stack verification")
    if args.live_prod_mesh:
        print("  live prod mesh: :18180-:18182")
    elif args.live:
        print(f"  live smoke: {args.base_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
