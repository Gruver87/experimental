"""Feature availability flags for API gating and /features endpoint.

Tier taxonomy (ADR 0016):
  production   — industrial L1 core path (may still be OFF, e.g. bridge)
  app-profile  — staging/app sprout; blocked on deployment_mode=prod mesh
  routing      — logical shard layer; lab mesh only
  offchain     — feeds / sidecars; not consensus drivers
  analysis     — diagnostics; not forge
  dev-test     — working R&D, not mainnet-tier
  r-and-d      — educational / incomplete crypto or VMs
"""
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional

# production = L1 core surface; everything else is sprout / blocked in prod mode
MODULE_TIERS: Dict[str, str] = {
    "evm": "production",
    "bridge": "production",
    "mempool": "production",
    "p2p": "production",
    "consensus": "production",
    "sharding": "routing",
    "oracles": "offchain",
    "nft": "app-profile",
    "wasm": "r-and-d",
    "plasma": "dev-test",
    "lightning": "dev-test",
    "zk": "r-and-d",
    "pq": "r-and-d",
    "mev": "analysis",
    "ai_agents": "dev-test",
    "ai_validator": "dev-test",
    "minivm": "r-and-d",
    "smart_accounts": "r-and-d",
    "validator_selection": "analysis",
    "reorg_predictor": "analysis",
    "cross_bridge": "dev-test",
}

# Tiers allowed to report as not prod-blocked (config may still disable them).
_PROD_CORE_TIERS = frozenset({"production"})


@dataclass
class FeatureFlags:
    # Core EVM may stay on; sprouts default OFF (ADR 0016 / fail-closed).
    evm: bool = True
    bridge: bool = False
    nft: bool = False
    zk: bool = False
    sharding: bool = False
    oracles: bool = False
    wasm: bool = False
    plasma: bool = False
    lightning: bool = False
    pq: bool = False
    mev: bool = False
    ai_agents: bool = False

    @classmethod
    def from_config(cls, config) -> "FeatureFlags":
        return cls(
            evm=getattr(config, "evm_enabled", True),
            bridge=getattr(config, "bridge_enabled", False),
            nft=getattr(config, "feature_nft", False),
            zk=getattr(config, "feature_zk", False),
            sharding=getattr(config, "feature_sharding", False),
            oracles=getattr(config, "feature_oracles", False),
            wasm=getattr(config, "feature_wasm", False),
            plasma=getattr(config, "feature_plasma", False),
            lightning=getattr(config, "feature_lightning", False),
            pq=getattr(config, "feature_pq", False),
            mev=getattr(config, "feature_mev", False),
            ai_agents=getattr(config, "feature_ai_agents", False),
        )

    def to_api_dict(self, instances: Optional[Dict[str, Any]] = None, config=None) -> Dict:
        instances = instances or {}
        is_prod = getattr(config, "is_production", False) if config else False
        out = {"deployment_mode": getattr(config, "deployment_mode", "dev") if config else "dev"}
        for name, enabled in asdict(self).items():
            live = instances.get(name)
            tier = MODULE_TIERS.get(name, "dev-test")
            blocked_in_prod = is_prod and tier not in _PROD_CORE_TIERS
            out[name] = {
                "enabled": bool(enabled and live is not None and not blocked_in_prod),
                "configured": enabled,
                "loaded": live is not None,
                "tier": tier,
                "dev_only": tier in ("dev-test", "r-and-d", "offchain"),
                "analysis": tier == "analysis",
                "app_profile": tier == "app-profile",
                "prod_blocked_reason": (
                    f"{tier} sprout is not enabled on industrial L1 prod "
                    f"(ADR 0016); use a dedicated profile"
                    if blocked_in_prod
                    else ""
                ),
            }
        return out


def probe_optional_module(module_path: str, class_name: str) -> Dict[str, Any]:
    """Honest import probe for optional R&D modules (wasm, plasma, etc.)."""
    try:
        import importlib

        mod = importlib.import_module(module_path)
        getattr(mod, class_name)
        return {"module_importable": True, "import_error": None}
    except Exception as exc:
        return {"module_importable": False, "import_error": str(exc)}


OPTIONAL_MODULE_PROBES: Dict[str, tuple[str, str]] = {
    "wasm": ("features.wasm_vm", "WASMVirtualMachine"),
    "plasma": ("features.plasma", "PlasmaChain"),
    "lightning": ("features.lightning", "LightningNetwork"),
    "zk": ("features.zk", "ZKProofSystem"),
    "ai_agents": ("features.ai_manager", "AIAgentManager"),
    "mev": ("features.mev_analyzer", "MEVAnalyzer"),
    "pq": ("features.postquantum", "PostQuantumManager"),
}
