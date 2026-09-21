#!/usr/bin/env python3
"""Live prod mesh: EVM deploy + storage persist across HTTP/RPC ports."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from verify_p2p_ci import (  # noqa: E402
    _admin_token,
    _api,
    _post_json,
    _probe_health,
)

# Constructor: SSTORE 1 @ slot0, return 1-byte runtime (STOP).
DEPLOY_BYTECODE = "6001600055600060005260016000f3"
STORAGE_SLOT = "0x0"


def _rpc(url: str, method: str, params: list, api_key: str, timeout: float = 15):
    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode())
    if body.get("error"):
        raise RuntimeError(body["error"])
    return body.get("result")


def _rpc_api_key() -> str:
    raw = os.environ.get("RPC_API_KEYS", "").strip()
    if not raw:
        return ""
    return raw.split(",")[0].strip()


def _wallet_address(wallet_path: str) -> str:
    from crypto.wallet import Wallet

    return Wallet.import_wallet(wallet_path).address


def _ensure_deployer_balance(http_url: str, deployer: str, min_balance: float = 5.0) -> None:
    info = _api(f"{http_url}/address/{deployer}")
    balance = float(info.get("balance", 0) or 0)
    if balance < min_balance:
        raise RuntimeError(
            f"deployer balance too low ({balance}); need >={min_balance} ABS on {http_url}"
        )


def _mempool_deploy_address(deployer: str, nonce: int, block_height: int, tx_hash: str) -> str:
    from crypto import native

    bytecode = bytes.fromhex(DEPLOY_BYTECODE)
    deploy_salt = f"{block_height}:{nonce}:{tx_hash}"
    salt_word = int.from_bytes(native.keccak256_digest(deploy_salt.encode())[:32], "big")
    return native.evm_create2_address_eip1014(deployer, salt_word, bytecode)


def _deploy_via_mempool(http_url: str, wallet_path: str, gas: int = 500_000) -> tuple[str, str, int]:
    """Signed deploy tx → block → CREATE2 address (replicated across mesh)."""
    from crypto.wallet import Wallet
    from runtime.mainnet_constants import MAINNET_V1_CHAIN_ID

    wallet = Wallet.import_wallet(wallet_path)
    deployer = wallet.address
    status = _api(f"{http_url}/status")
    chain_id = int(status.get("chain_id", MAINNET_V1_CHAIN_ID))
    start_height = int(status.get("height", 0) or 0)
    nonce = int(_api(f"{http_url}/address/{deployer}").get("nonce", 0) or 0)

    zero = "0x0000000000000000000000000000000000000000"
    data = DEPLOY_BYTECODE
    signed = wallet.sign_transaction(
        zero,
        0,
        nonce,
        chain_id=chain_id,
        data=data,
        gas_limit=gas,
    )
    _admin_token(http_url)
    resp = _post_json(
        http_url,
        "/tx/send",
        {**signed, "from": deployer, "gas": gas, "value": 0},
        timeout=30,
    )
    tx_hash = str(resp.get("tx_hash") or signed.get("hash") or "").strip()
    if not tx_hash:
        raise RuntimeError(f"mempool deploy missing tx_hash: {resp}")

    block_height = start_height
    for attempt in range(180):
        time.sleep(2)
        height = int(_api(f"{http_url}/status").get("height", 0) or 0)
        if height > start_height:
            block_height = height
            break
        if attempt > 0 and attempt % 15 == 0:
            print(f"  waiting mine… height={height} mempool={_api(f'{http_url}/status').get('mempool_size')}")
    else:
        raise RuntimeError(f"deploy tx not mined (start_height={start_height})")

    contract = _mempool_deploy_address(deployer, nonce, block_height, tx_hash)
    return tx_hash, contract, block_height


def _wait_storage_all(
    rpc_urls: list[str],
    contract: str,
    api_key: str,
    timeout_sec: int = 120,
) -> dict[int, str]:
    deadline = time.time() + timeout_sec
    last: dict[int, str] = {}
    while time.time() < deadline:
        ok_all = True
        for i, rpc_url in enumerate(rpc_urls, start=1):
            try:
                storage = _rpc(rpc_url, "eth_getStorageAt", [contract, STORAGE_SLOT, "latest"], api_key)
                last[i] = str(storage)
                if not _storage_ok(last[i]):
                    ok_all = False
            except Exception as exc:
                last[i] = f"err:{exc}"
                ok_all = False
        if ok_all:
            return last
        time.sleep(3)
    raise RuntimeError(f"storage not replicated on all RPC nodes (last={last})")


def _storage_ok(storage_hex: str) -> bool:
    try:
        return int(str(storage_hex), 16) == 1
    except ValueError:
        return False


def _wait_mesh_aligned(http_urls: list[str], timeout_sec: int = 300) -> None:
    """Wait for equal tip head+root via aggressive catch-up (BehindOpen tip+1 safe)."""
    from verify_p2p_ci import (
        _force_prod_mesh_catchup,
        _mesh_tip_snapshot,
    )

    budget = max(30.0, float(timeout_sec))
    if _force_prod_mesh_catchup(
        http_urls,
        budget_sec=budget,
        expected_peers=max(1, len(http_urls) - 1),
        label="evm-align",
    ):
        return
    try:
        heights, _heads, roots = _mesh_tip_snapshot(http_urls)
    except Exception:
        heights, roots = [], []
    raise RuntimeError(
        "mesh not aligned (heights/roots); wait for P2P sync or rebuild prod mesh "
        f"(heights={heights} roots={[r[:16] for r in roots]})"
    )


def _deploy_direct(http_url: str, deployer: str) -> str:
    _admin_token(http_url)
    salt = f"prod-evm-smoke-{time.time_ns()}"
    result = _post_json(
        http_url,
        "/contract/deploy",
        {"from": deployer, "bytecode": DEPLOY_BYTECODE, "salt": salt, "value": 0},
        timeout=30,
    )
    if not result.get("success"):
        raise RuntimeError(f"direct deploy failed: {result.get('error') or result}")
    contract = str(result.get("return_value") or "").strip()
    if not contract:
        raise RuntimeError("direct deploy returned no contract address")
    return contract


def main() -> int:
    parser = argparse.ArgumentParser(description="Prod mesh EVM deploy + RPC storage smoke")
    parser.add_argument("--url1", default="http://127.0.0.1:18180")
    parser.add_argument("--url2", default="http://127.0.0.1:18181")
    parser.add_argument("--url3", default="http://127.0.0.1:18182")
    parser.add_argument("--rpc1", default="http://127.0.0.1:18546")
    parser.add_argument("--rpc2", default="http://127.0.0.1:18547")
    parser.add_argument("--rpc3", default="http://127.0.0.1:18548")
    parser.add_argument(
        "--wallet",
        default="",
        help="Deployer wallet JSON (default: data/prod_mesh/wallets/validator-1.wallet.json)",
    )
    parser.add_argument(
        "--leader-only",
        action="store_true",
        help="Skip mempool; direct deploy on node1 only (partial evidence)",
    )
    args = parser.parse_args()

    wallet = (args.wallet or "").strip()
    if not wallet:
        wallet = os.path.join(ROOT, "data", "prod_mesh", "wallets", "validator-1.wallet.json")
    if not os.path.isfile(wallet):
        print(f"FAIL: wallet not found: {wallet}")
        return 1

    http_urls = [args.url1, args.url2, args.url3]
    rpc_urls = [args.rpc1, args.rpc2, args.rpc3]
    api_key = _rpc_api_key()
    if not api_key:
        print("FAIL: set RPC_API_KEYS env (prod mesh .env)")
        return 1

    for i, url in enumerate(http_urls, start=1):
        if not _probe_health(url):
            print(f"FAIL: node{i} HTTP not reachable at {url}")
            return 1

    try:
        deployer = _wallet_address(wallet)
    except Exception as exc:
        print(f"FAIL: wallet load: {exc}")
        return 1

    status = _api(f"{args.url1}/status")
    if str(status.get("deployment_mode", "")).lower() != "prod":
        print(f"FAIL: expected deployment_mode=prod, got {status.get('deployment_mode')!r}")
        return 1

    if args.leader_only:
        print("FAIL: --leader-only uses direct /contract/deploy, blocked in production")
        return 1

    align_timeout = int(os.environ.get("ABS_EVM_ALIGN_TIMEOUT_SEC", "300") or "300")
    try:
        _wait_mesh_aligned(http_urls, timeout_sec=align_timeout)
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 1

    print(f"Prod EVM smoke: deployer={deployer} http={args.url1}")
    cross_node = not args.leader_only
    try:
        _ensure_deployer_balance(args.url1, deployer)
        if args.leader_only:
            contract = _deploy_direct(args.url1, deployer)
            print(f"  direct deploy contract={contract}")
            storage = _rpc(rpc_urls[0], "eth_getStorageAt", [contract, STORAGE_SLOT, "latest"], api_key)
            if not _storage_ok(str(storage)):
                raise RuntimeError(f"leader storage={storage!r}")
            storage_by_node = {1: str(storage)}
        else:
            tx_hash, contract, block_height = _deploy_via_mempool(args.url1, wallet)
            print(f"  mempool deploy tx={tx_hash} block={block_height} contract={contract}")
            # Parent CI may freeze primary mining via ABS_EVM_POST_DEPLOY_GATE file.
            gate = (os.environ.get("ABS_EVM_POST_DEPLOY_GATE") or "").strip()
            if gate:
                marker = Path(gate)
                marker.write_text(
                    json.dumps(
                        {
                            "tx_hash": tx_hash,
                            "contract": contract,
                            "block_height": block_height,
                        }
                    ),
                    encoding="utf-8",
                )
                resume = Path(str(marker) + ".resume")
                print(f"  post-deploy gate armed: {marker} (waiting freeze/realign)")
                deadline = time.time() + max(60, align_timeout)
                while time.time() < deadline:
                    if resume.is_file():
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError(f"post-deploy gate timeout waiting {resume}")
                try:
                    resume.unlink()
                except OSError:
                    pass
            _wait_mesh_aligned(http_urls, timeout_sec=align_timeout)
            storage_by_node = _wait_storage_all(
                rpc_urls, contract, api_key, timeout_sec=max(120, align_timeout // 2)
            )
    except (urllib.error.URLError, RuntimeError, OSError) as exc:
        print(f"FAIL: deploy: {exc}")
        return 1

    # eth_getCode on leader RPC
    try:
        code = _rpc(rpc_urls[0], "eth_getCode", [contract, "latest"], api_key)
        if not code or code in ("0x", "0x0"):
            print(f"FAIL: eth_getCode empty on {rpc_urls[0]}")
            return 1
        print(f"  eth_getCode len={len(code)}")
    except Exception as exc:
        print(f"FAIL: eth_getCode: {exc}")
        return 1

    for i, storage in storage_by_node.items():
        print(f"  OK: node{i} eth_getStorageAt slot0={storage}")

    if cross_node and len(storage_by_node) >= len(rpc_urls):
        print("OK: prod EVM deploy + storage on all RPC nodes")
    elif args.leader_only:
        print("PARTIAL: prod EVM leader RPC only (--leader-only)")
    else:
        print(f"FAIL: cross-node storage incomplete ({storage_by_node})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
