"""WASM VM — WebAssembly-style contracts with SQLite persistence (Wave 42)."""

import base64
from crypto import native
import json
import time
from typing import Dict, List, Optional, Any


def _looks_like_wasm_module(code: str) -> bool:
    raw = (code or "").strip()
    if raw.startswith("(module"):
        return True
    try:
        data = base64.b64decode(raw, validate=True)
        return len(data) >= 4 and data[:4] == b"\x00asm"
    except Exception:
        return False


class WASMContract:
    def __init__(self, address: str, code: str, owner: str, name: str,
                 created_at: int = None, call_count: int = 0):
        self.address = address
        self.code = code
        self.owner = owner
        self.name = name
        self.created_at = created_at if created_at is not None else int(time.time())
        self.abi = {
            "functions": ["constructor", "balanceOf", "transfer", "getInfo", "getOwner"]
        }
        self.call_count = call_count

    def to_dict(self) -> Dict:
        return {
            "address": self.address,
            "name": self.name,
            "owner": self.owner[:16] + "..." if len(self.owner) > 20 else self.owner,
            "created_at": self.created_at,
            "call_count": self.call_count,
            "abi": self.abi,
            "code_size": len(self.code),
        }

    def to_db(self, storage: Dict) -> Dict:
        return {
            "address": self.address,
            "code": self.code,
            "owner": self.owner,
            "name": self.name,
            "created_at": self.created_at,
            "call_count": self.call_count,
            "storage": storage,
        }


class WASMVirtualMachine:
    """WebAssembly-style VM — deploy/call persisted in SQLite."""

    GAS_LIMIT = 10_000_000
    DEPLOY_FEE = 0.01

    def __init__(self, db=None):
        self.db = db
        self.contracts: Dict[str, WASMContract] = {}
        self.storage: Dict[str, Dict] = {}
        self.events: List[Dict] = []
        self._load_from_db()
        print(f"[WASM VM] Initialized ({len(self.contracts)} contracts, "
              f"persisted={bool(db)})")

    def _load_from_db(self) -> None:
        if not self.db or not hasattr(self.db, "get_wasm_contracts"):
            return
        for row in self.db.get_wasm_contracts(limit=500):
            c = WASMContract(
                address=row["address"],
                code=row["code"],
                owner=row["owner"],
                name=row["name"],
                created_at=row.get("created_at"),
                call_count=row.get("call_count", 0),
            )
            self.contracts[c.address] = c
            self.storage[c.address] = dict(row.get("storage", {}))
        if hasattr(self.db, "get_wasm_events"):
            for ev in self.db.get_wasm_events(limit=500):
                self.events.append({
                    "event_id": ev["event_id"],
                    **ev.get("payload", {}),
                    "type": ev.get("event_type", ""),
                    "timestamp": ev.get("timestamp", 0),
                })
            self.events.sort(key=lambda e: e.get("timestamp", 0))

    def _persist_contract(self, addr: str) -> None:
        c = self.contracts.get(addr)
        if not c or not self.db or not hasattr(self.db, "save_wasm_contract"):
            return
        self.db.save_wasm_contract(c.to_db(self.storage.get(addr, {})))

    def _persist_event(self, event: Dict) -> None:
        if not self.db or not hasattr(self.db, "save_wasm_event"):
            return
        eid = native.sha256_hex(
            json.dumps(event, sort_keys=True, default=str).encode()
        )[:24]
        self.db.save_wasm_event({
            "event_id": eid,
            "contract_addr": event.get("address", event.get("contract", "")),
            "event_type": event.get("type", ""),
            "payload": event,
            "timestamp": event.get("timestamp", int(time.time())),
        })

    def _charge_deploy_fee(self, owner: str) -> bool:
        if (
            not self.db
            or not hasattr(self.db, "get_balance")
            or not hasattr(self.db, "update_balance")
        ):
            return False
        if self.db.get_balance(owner) < self.DEPLOY_FEE:
            return False
        self.db.update_balance(owner, -self.DEPLOY_FEE)
        return True

    def deploy(self, code: str, owner: str, name: str = None,
               init_params: Dict = None) -> Optional[str]:
        if not code or not owner:
            return None
        # Binary WASM requires wasmtime; reject before charging fee.
        try:
            data = base64.b64decode((code or "").strip(), validate=True)
            is_bin = len(data) >= 4 and data[:4] == b"\x00asm"
        except Exception:
            is_bin = False
        if is_bin:
            from features.wasm_engine import WASMEngine

            if not WASMEngine.available():
                return None
        if not self._charge_deploy_fee(owner):
            return None
        contract_addr = "wasm_" + native.sha256_hex(
            f"{code}{owner}{time.time()}".encode()
        )[:40]
        name = name or f"Contract_{contract_addr[:8]}"
        contract = WASMContract(contract_addr, code, owner, name)
        self.contracts[contract_addr] = contract
        self.storage[contract_addr] = {}
        if init_params:
            self._run_constructor(contract_addr, init_params, owner)
        self._persist_contract(contract_addr)
        self._log_event({
            "type": "ContractDeployed",
            "address": contract_addr,
            "owner": owner,
            "name": name,
            "timestamp": int(time.time()),
        })
        print(f"[WASM VM] Deployed: {contract_addr[:20]}... name={name}")
        return contract_addr

    def call(self, contract_addr: str, function_name: str,
             params: Dict, caller: str, value: float = 0.0) -> Dict:
        contract = self.contracts.get(contract_addr)
        if not contract:
            return {"success": False, "error": "Contract not found", "gas_used": 0}
        gas_used = 5000 + len(function_name) * 100 + len(json.dumps(params)) * 50
        if gas_used > self.GAS_LIMIT:
            return {"success": False, "error": "Out of gas", "gas_used": gas_used}
        result = self._execute(contract, function_name, params, caller, value)
        contract.call_count += 1
        self._persist_contract(contract_addr)
        self._log_event({
            "type": "FunctionCall",
            "contract": contract_addr,
            "function": function_name,
            "caller": caller,
            "gas_used": gas_used,
            "timestamp": int(time.time()),
        })
        return {
            "success": result.get("success", False),
            "result": result.get("result"),
            "error": result.get("error"),
            "gas_used": gas_used,
            "data": result.get("data"),
        }

    def get_contract(self, addr: str) -> Optional[Dict]:
        c = self.contracts.get(addr)
        return c.to_dict() if c else None

    def get_all_contracts(self) -> List[Dict]:
        return [c.to_dict() for c in self.contracts.values()]

    def get_storage(self, addr: str) -> Dict:
        return dict(self.storage.get(addr, {}))

    def get_events(self, limit: int = 100) -> List[Dict]:
        return list(reversed(self.events[-limit:]))

    def get_stats(self) -> Dict:
        from features.wasm_engine import WASMEngine

        wt = bool(WASMEngine.available())
        return {
            "contracts_count": len(self.contracts),
            "total_calls": sum(c.call_count for c in self.contracts.values()),
            "storage_keys": sum(len(s) for s in self.storage.values()),
            "events_count": len(self.events),
            "gas_limit": self.GAS_LIMIT,
            "deploy_fee": self.DEPLOY_FEE,
            "persisted": bool(self.db),
            "wasm_engine": wt,
            "wasmtime_available": wt,
            "execution_bound": wt,
            "pseudo_token_host": True,
            "operational": wt,
            # Wave M: enabled only when real wasmtime is present.
            "enabled": bool(wt),
        }

    def _run_constructor(self, addr: str, params: Dict, owner: str):
        initial_supply = params.get("initialSupply", 1_000_000)
        if addr not in self.storage:
            self.storage[addr] = {}
        self.storage[addr][f"balance_{owner}"] = initial_supply
        self.storage[addr]["totalSupply"] = initial_supply

    def _execute(self, contract: WASMContract, fn: str,
                 params: Dict, caller: str, value: float) -> Dict:
        addr = contract.address
        store = self.storage.get(addr, {})
        if fn == "balanceOf":
            account = params.get("account", caller)
            return {"success": True, "result": store.get(f"balance_{account}", 0)}
        elif fn == "transfer":
            # Wave M: refuse pseudo-host money mutator (not real WASM execution).
            return {
                "success": False,
                "error": "wasm_pseudo_token_host_refused",
                "pseudo_token_host": True,
            }
        elif fn == "constructor":
            return {"success": False, "error": "Constructor cannot be called after deployment"}
        elif fn == "getInfo":
            return {"success": True, "result": contract.name}
        elif fn == "getOwner":
            return {"success": True, "result": contract.owner}
        elif fn == "totalSupply":
            return {"success": True, "result": store.get("totalSupply", 0)}
        elif fn == "setStorage":
            if caller != contract.owner:
                return {"success": False, "error": "Only contract owner can set storage"}
            key = params.get("key")
            val = params.get("value")
            if key:
                store[key] = val
                self.storage[addr] = store
                return {"success": True, "result": True}
            return {"success": False, "error": "Key required"}
        elif fn == "getStorage":
            key = params.get("key")
            return {"success": True, "result": store.get(key) if key else None}
        else:
            code = contract.code
            pseudo_source = (
                f"fn {fn}" in code
                or f"function {fn}" in code
                or f"def {fn}" in code
            )
            if pseudo_source and not _looks_like_wasm_module(code):
                return {
                    "success": False,
                    "error": "Custom WASM execution backend not available",
                }
            try:
                from features.wasm_engine import WASMEngine

                if WASMEngine.available() and _looks_like_wasm_module(code):
                    store = self.storage.setdefault(addr, {})
                    engine = WASMEngine(store, gas_limit=self.GAS_LIMIT)
                    wasm_bytes = WASMEngine.decode_module(contract.code)
                    out = engine.execute(wasm_bytes, fn, params, caller)
                    if out.get("success"):
                        self.storage[addr] = store
                        return {
                            "success": True,
                            "result": out.get("result"),
                            "data": {"engine": out.get("engine"), "logs": out.get("logs")},
                        }
                    return {
                        "success": False,
                        "error": out.get("error", "wasm execution failed"),
                    }
            except Exception as exc:
                return {"success": False, "error": f"WASM engine error: {exc}"}
            if pseudo_source:
                return {
                    "success": False,
                    "error": "Install wasmtime for custom WASM exports (pip install wasmtime)",
                }
            return {"success": False, "error": f"Function '{fn}' not found"}

    def _log_event(self, event: Dict):
        self.events.append(event)
        self._persist_event(event)
        if len(self.events) > 10_000:
            self.events = self.events[-10_000:]
