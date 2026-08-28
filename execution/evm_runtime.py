"""EVM depth runtime honesty (Profile A lab packaging, ADR 0016).

Single apply path — not a FEATURE_* sprout. Snapshot surfaces compat matrix
rows for HTTP / gates without claiming full geth or soak proof.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

# Mirror docs/sprouts/EVM_COMPAT_MATRIX.md — update both when a wave closes a row.
_COMPAT_ROWS: List[Dict[str, str]] = [
    {"area": "transfer_fee_burn", "status": "supported", "notes": "Native apply + satoshi domain"},
    {
        "area": "create_create2_deploy_salt",
        "status": "supported_prod",
        "notes": "evm_create2_eip1014 + evm_require_deploy_salt on prod JSON",
    },
    {
        "area": "call_staticcall_host",
        "status": "partial",
        "notes": "Host-in-apply nested depth cap 4; sticky STATICCALL (EIP-214)",
    },
    {
        "area": "precompiles_0x01_0x09",
        "status": "partial",
        "notes": "execution/evm_precompiles.py on call + apply paths",
    },
    {"area": "eth_call", "status": "supported", "notes": "Hex ABI word encoding + precompile bytes"},
    {"area": "eth_estimateGas", "status": "partial", "notes": "Missing adapter → JSON null"},
    {"area": "eth_getTransactionReceipt", "status": "partial", "notes": "Null-honesty; no 21000 stub"},
    {"area": "eth_getLogs", "status": "partial", "notes": "Log index; missing fields → null"},
    {"area": "eth_getBlockByNumber", "status": "partial", "notes": "Absolute merkle roots; not Ethereum MPT"},
    {"area": "eth_feeHistory", "status": "partial", "notes": "baseFeePerGas/reward null (not EIP-1559)"},
    {"area": "eip_4844_blobs", "status": "not_claimed", "notes": "Out of scope"},
    {"area": "eof", "status": "not_claimed", "notes": "Out of scope"},
    {"area": "full_geth_json_rpc", "status": "not_claimed", "notes": "Wave-gated methods only"},
]

_NOT_CLAIMED = ("eip_4844_blobs", "eof", "full_geth_json_rpc")


def compat_matrix_rows() -> List[Dict[str, str]]:
    """Return a copy of the honest compat matrix rows."""
    return [dict(r) for r in _COMPAT_ROWS]


def evm_compat_honesty_snapshot(config: Any | None = None) -> Dict[str, Any]:
    """Honesty surface for GET /evm/status (not full geth / not soak proof)."""
    enabled = bool(getattr(config, "evm_enabled", True)) if config else True
    mode = str(getattr(config, "deployment_mode", "") or "").strip().lower() if config else ""
    create2 = bool(getattr(config, "evm_create2_eip1014", False)) if config else False
    deploy_salt = bool(getattr(config, "evm_require_deploy_salt", False)) if config else False
    gas_limit = int(getattr(config, "evm_gas_limit", 8_000_000) or 8_000_000) if config else 8_000_000
    prod_hardened = mode in ("prod", "production", "staging") and create2 and deploy_salt

    supported_n = sum(1 for r in _COMPAT_ROWS if r["status"] in ("supported", "supported_prod"))
    partial_n = sum(1 for r in _COMPAT_ROWS if r["status"] == "partial")
    not_claimed_n = sum(1 for r in _COMPAT_ROWS if r["status"] == "not_claimed")

    if not enabled:
        detail = "evm_disabled: execution VM off (unexpected on Profile A)"
    elif prod_hardened:
        detail = (
            f"evm_prod_profile: CREATE2+deploy_salt armed; gas_limit={gas_limit}; "
            "Shanghai/Cancun subset — not full geth / not EIP-4844"
        )
    elif mode in ("prod", "production", "staging"):
        detail = "evm_prod_incomplete: CREATE2 or deploy_salt not armed on config"
    else:
        detail = (
            f"evm_dev_profile: gas_limit={gas_limit}; "
            "lab waves 8–10 (precompile/rpc/nested); mesh smoke separate"
        )

    return {
        "evm_enabled": enabled,
        "deployment_mode": mode or "unknown",
        "evm_gas_limit": gas_limit,
        "evm_create2_eip1014": create2,
        "evm_require_deploy_salt": deploy_salt,
        "prod_hardened": bool(prod_hardened),
        "compat_matrix": compat_matrix_rows(),
        "supported_count": supported_n,
        "partial_count": partial_n,
        "not_claimed_count": not_claimed_n,
        "not_claimed": list(_NOT_CLAIMED),
        "lab_scripts": [
            "scripts/evm_precompile_lab.py",
            "scripts/evm_rpc_lab.py",
            "scripts/evm_nested_lab.py",
        ],
        "mesh_evidence_script": "scripts/prod_evm_smoke.py",
        "mesh_evidence_note": (
            "Live prod mesh deploy + eth_getStorageAt; requires Docker mesh — "
            "not a substitute for lab scripts"
        ),
        "detail": detail,
    }


def merge_compat_summary(existing: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Merge opcode summary with compat honesty (for /evm/status enrichment)."""
    base = dict(existing or {})
    snap = evm_compat_honesty_snapshot(None)
    base["compat_honesty"] = {
        "supported_count": snap["supported_count"],
        "partial_count": snap["partial_count"],
        "not_claimed_count": snap["not_claimed_count"],
        "detail": snap["detail"],
    }
    return base
