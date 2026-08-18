#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Absolute Cross-Chain Bridge

Режим работы задаётся в Config.bridge_mode:
  "rust"      — вызов скомпилированного Rust-бинарника через subprocess
  "simulator" — явный dev/test-only режим на основе DevBridgeAdapter

Поддерживаемые сети (prod rust path): Ethereum, BSC, Polygon, Absolute (ABS).
Solana — только dev/test simulator; не поддерживается rust L1 RPC.
"""

import json
import sys
import os
import subprocess
import time
import threading
from typing import Dict, List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from bridge.dev_bridge_adapter import CrossChainBridge, BridgeTransaction, Chain
from runtime.amount import money_abs
from storage.database import Database
from runtime.config import Config
from kernel.event_bus import EventBus


class BridgeLock:
    """Запись о заблокированных средствах (ждут подтверждения на другой стороне)."""

    def __init__(self, tx_hash: str, from_addr: str, to_chain: str,
                 to_addr: str, amount: float):
        self.tx_hash = tx_hash
        self.from_addr = from_addr
        self.to_chain = to_chain
        self.to_addr = to_addr
        self.amount = amount
        self.status = "pending"  # pending | confirmed | failed
        self.created_at = int(time.time())
        self.confirmed_at: Optional[int] = None


class RustBridge:
    """
    Обёртка над Rust-бинарником кросс-чейн моста.
    Python dev/test adapter remains available only when selected explicitly.

    Жизненный цикл транзакции:
      1. lock_and_bridge()   — блокируем ABS на нашей цепи, инициируем перевод
      2. confirm_incoming()  — получаем подтверждение с внешней цепи, начисляем ABS
      3. refund()            — если перевод завершился ошибкой — возвращаем ABS
    """

    SUPPORTED_CHAINS = [c.value for c in Chain]
    RUST_L1_CHAINS = ("ethereum", "bsc", "polygon", "absolute")
    DEV_ONLY_CHAINS = ("solana",)

    CHAIN_ALIASES = {
        "eth": "ethereum",
        "ether": "ethereum",
        "ethereum": "ethereum",
        "bnb": "bsc",
        "bsc": "bsc",
        "binance": "bsc",
        "sol": "solana",
        "solana": "solana",
        "abs": "absolute",
        "absolute": "absolute",
    }

    def _normalize_chain(self, chain: str) -> str:
        key = (chain or "").strip().lower()
        return self.CHAIN_ALIASES.get(key, key)

    # Тарифы моста (% от суммы)
    BRIDGE_FEES = {
        "ethereum": 0.01,   # 1%
        "bsc":      0.002,  # 0.2%
        "solana":   0.001,  # 0.1%
        "absolute": 0.005,  # 0.5%
    }

    def __init__(self, config: Config, db: Database, bus: Optional[EventBus] = None):
        self.config = config
        self.db = db
        self.bus = bus
        self._running = False
        self._lock = threading.Lock()
        self._is_prod = getattr(config, "deployment_mode", "dev") == "prod"

        if self._is_prod and config.bridge_mode != "rust":
            raise RuntimeError("production bridge requires bridge_mode=rust")

        # Python dev/test adapter must be selected explicitly.
        self._simulator = (
            CrossChainBridge()
            if not self._is_prod and config.bridge_mode == "simulator"
            else None
        )

        # Подписываемся на входящие bridge-события
        if self.bus:
            self.bus.on("bridge.incoming", self._on_incoming)

        # Если включён Rust-режим — проверяем наличие бинарника
        self._rust_bin = self._resolve_rust_bin()
        self._rust_decode_fail = 0
        self._rust_timeout = 0
        self._rust_bin_fail = 0
        self._rust_cmd_fail = 0
        self._rust_last_error = ""
        if config.bridge_mode == "rust":
            if not self._rust_bin:
                msg = "Rust bridge binary not found"
                print(f"[Bridge] ERROR: {msg} at '{config.rust_bridge_path}'")
                # Prod + bridge OFF still pins bridge_mode=rust; do not crash the node
                # until the live cutover actually enables the bridge.
                if self._is_prod and bool(getattr(config, "bridge_enabled", False)):
                    raise RuntimeError(msg)
                self._mode = "unavailable"
            else:
                self._mode = "rust"
                print(f"[Bridge] Rust bridge: {self._rust_bin}")
        elif config.bridge_mode == "simulator":
            self._mode = "simulator"
        else:
            self._mode = "unavailable"

        print(f"[Bridge] Initialized in '{self._mode}' mode. "
              f"Supported chains: {', '.join(self.SUPPORTED_CHAINS)}")

    async def start(self):
        """Запускает фоновую обработку моста (подтверждения)."""
        self._running = True
        import asyncio
        while self._running:
            await asyncio.sleep(5)
            self._process_pending()

    def stop(self):
        self._running = False

    # ── Отправка ─────────────────────────────────────────────────────────────

    def lock_and_bridge(self, from_addr: str, to_chain: str,
                        to_addr: str, amount: float,
                        l1_tx_hash: str = "") -> Dict:
        """
        Блокирует ABS на нашей цепи и инициирует перевод на to_chain.

        Возвращает: {"tx_hash": str, "fee": float, "net_amount": float, "status": str}
        """
        to_chain = self._normalize_chain(to_chain)
        if self._is_prod:
            if to_chain in self.DEV_ONLY_CHAINS:
                return {
                    "error": f"Chain {to_chain} is not supported in production rust bridge "
                    f"(L1 RPC not implemented). Supported: {', '.join(self.RUST_L1_CHAINS)}",
                }
            if to_chain not in self.RUST_L1_CHAINS:
                return {
                    "error": f"Unsupported chain: {to_chain}. "
                    f"Production supported: {', '.join(self.RUST_L1_CHAINS)}",
                }
        elif to_chain not in self.SUPPORTED_CHAINS:
            return {"error": f"Unsupported chain: {to_chain}. "
                             f"Supported: {', '.join(self.SUPPORTED_CHAINS)}"}

        fee_rate = self.BRIDGE_FEES.get(to_chain, 0.01)
        fee = amount * fee_rate
        net_amount = amount - fee

        if net_amount <= 0:
            return {"error": "Amount too small after fee"}

        # Проверяем баланс отправителя (TOCTOU still possible until debit; debit fails closed)
        balance = self.db.get_balance(from_addr)
        if balance < amount:
            return {"error": "Insufficient balance"}

        # v1.3.68: prod + bridge_enabled requires semantic L1 event mode
        if self._is_prod and bool(getattr(self.config, "bridge_enabled", False)):
            if not bool(getattr(self.config, "bridge_require_l1_event", False)):
                return {
                    "error": "prod bridge requires bridge_require_l1_event=true (semantic L1 bind)"
                }

        # Выбираем режим
        if self._mode == "rust":
            rust_args = {
                "from_chain": "absolute",
                "to_chain": to_chain,
                "from_addr": from_addr,
                "to_addr": to_addr,
                "amount": net_amount,
            }
            if l1_tx_hash:
                rust_args["l1_tx_hash"] = l1_tx_hash
                if not self._call_rust_ok("lock", rust_args):
                    return {"error": "rust L1 lock verification failed"}
                tx_hash = l1_tx_hash
            elif self._is_prod:
                return {
                    "error": (
                        "prod outbound bridge requires l1_tx_hash (real L1 escrow). "
                        "Disable bridge_enabled for mainnet-v1 until L1 lock/mint contracts "
                        "and tx submission are implemented."
                    )
                }
            else:
                tx_hash = self._call_rust("bridge", rust_args)
                if not tx_hash:
                    return {"error": "rust bridge call failed"}
        elif self._mode == "simulator":
            if not self._simulator:
                return {"error": "simulator bridge not available"}
            tx_hash = self._simulator.bridge(
                "absolute", to_chain, from_addr, to_addr, net_amount
            )
        else:
            return {"error": "bridge unavailable: rust binary missing or bridge mode invalid"}

        bridge_burn = fee * self.config.burn_rate
        if hasattr(self.db, "debit_and_create_bridge_lock"):
            self.db.debit_and_create_bridge_lock(
                from_addr=from_addr,
                amount=amount,
                burn_address=self.config.burn_address,
                burn_amount=bridge_burn,
                to_chain=to_chain,
                to_addr=to_addr,
                net_amount=net_amount,
                tx_hash=tx_hash,
            )
        else:
            self.db.update_balance(from_addr, -amount)
            self.db.update_balance(self.config.burn_address, bridge_burn)
            self.db.save_bridge_lock(from_addr, to_chain, to_addr, net_amount, tx_hash)

        if l1_tx_hash:
            self._enqueue_l1_outbound(tx_hash, l1_tx_hash, to_chain)

        if self.bus:
            self.bus.emit("bridge.locked", {
                "tx_hash": tx_hash,
                "from": from_addr,
                "to_chain": to_chain,
                "to_addr": to_addr,
                "amount": net_amount,
                "fee": fee,
            })

        return {
            "tx_hash": tx_hash,
            "from_addr": from_addr,
            "to_chain": to_chain,
            "to_addr": to_addr,
            "amount": amount,
            "fee": fee,
            "net_amount": net_amount,
            "status": "pending",
            "l1_queued": bool(l1_tx_hash),
        }

    def _enqueue_l1_outbound(self, abs_tx_hash: str, l1_tx_hash: str, chain: str) -> None:
        """Append outbound L1 proof watch entry for bridge relayer."""
        from bridge.l1_rpc import load_l1_queue, save_l1_queue

        path = getattr(self.config, "bridge_l1_queue_path", "data/bridge_l1_queue.json")
        queue = load_l1_queue(path)
        outbound = list(queue.get("outbound", []))
        entry = {
            "abs_tx_hash": abs_tx_hash,
            "tx_hash": abs_tx_hash,
            "l1_tx_hash": l1_tx_hash,
            "chain": self._normalize_chain(chain),
            "queued_at": int(time.time()),
        }
        outbound = [e for e in outbound if e.get("abs_tx_hash") != abs_tx_hash]
        outbound.append(entry)
        queue["outbound"] = outbound[-500:]
        save_l1_queue(path, queue)

    def enqueue_l1_incoming(
        self,
        l1_tx_hash: str,
        recipient: str,
        amount: float,
        from_chain: str,
        tx_id: str = "",
    ) -> None:
        """Append incoming L1 proof watch entry for bridge relayer."""
        from bridge.l1_rpc import load_l1_queue, save_l1_queue

        if not l1_tx_hash or not recipient or amount <= 0:
            return
        path = getattr(self.config, "bridge_l1_queue_path", "data/bridge_l1_queue.json")
        queue = load_l1_queue(path)
        incoming = list(queue.get("incoming", []))
        entry = {
            "l1_tx_hash": l1_tx_hash,
            "tx_hash": l1_tx_hash,
            "tx_id": tx_id or l1_tx_hash,
            "recipient": recipient,
            "amount": money_abs(amount, field="amount"),
            "from_chain": self._normalize_chain(from_chain),
            "queued_at": int(time.time()),
        }
        incoming = [
            e for e in incoming
            if e.get("l1_tx_hash") != l1_tx_hash and e.get("tx_id") != entry["tx_id"]
        ]
        incoming.append(entry)
        queue["incoming"] = incoming[-500:]
        save_l1_queue(path, queue)

    # ── Подтверждение входящего перевода ─────────────────────────────────────

    def confirm_incoming(self, tx_hash: str, recipient: str,
                         amount: float, from_chain: str,
                         l1_tx_hash: str = "",
                         log_index: int = 0) -> Dict:
        """
        Подтверждает входящий перевод с внешней цепи — начисляет ABS получателю.
        Replay key is source-event derived: (from_chain, event_tx, log_index).
        """
        event_tx = (l1_tx_hash or tx_hash or "").strip()
        if not event_tx or not recipient or amount <= 0:
            return {"confirmed": False, "error": "event_tx, recipient, amount required"}

        credit_key = self.db.bridge_credit_key(from_chain, event_tx, int(log_index or 0))
        if self.db.has_bridge_credit(credit_key):
            return {
                "confirmed": True,
                "duplicate": True,
                "tx_hash": tx_hash,
                "event_tx_hash": event_tx,
                "log_index": int(log_index or 0),
                "recipient": recipient,
                "amount": amount,
                "mode": self._mode,
                "credit_key": credit_key,
            }

        if l1_tx_hash:
            self.enqueue_l1_incoming(
                l1_tx_hash, recipient, amount, from_chain, tx_id=tx_hash
            )

        if self._mode == "rust":
            import os
            chain_key = {
                "ethereum": "ETH_RPC_URL",
                "eth": "ETH_RPC_URL",
                "bsc": "BSC_RPC_URL",
            }.get(from_chain.lower(), "")
            if self._is_prod and not l1_tx_hash:
                return {"confirmed": False, "error": "l1_tx_hash required in production"}
            if chain_key and os.environ.get(chain_key) and not l1_tx_hash:
                return {"confirmed": False, "error": "l1_tx_hash required when L1 RPC configured"}
            rust_args = {
                "tx_hash": tx_hash,
                "recipient": recipient,
                "amount": amount,
                "from_chain": from_chain,
            }
            if l1_tx_hash:
                rust_args["l1_tx_hash"] = l1_tx_hash
            if not self._call_rust_ok("incoming", rust_args):
                return {"confirmed": False, "error": "rust incoming failed"}
        elif self._mode != "simulator":
            return {"confirmed": False, "error": "bridge unavailable: rust binary missing or bridge mode invalid"}

        if hasattr(self.db, "claim_and_credit_bridge_event"):
            claim = self.db.claim_and_credit_bridge_event(
                from_chain=from_chain,
                event_tx_hash=event_tx,
                recipient=recipient,
                amount=amount,
                log_index=int(log_index or 0),
                abs_tx_hash=tx_hash,
            )
            if claim.get("duplicate"):
                return {
                    "confirmed": True,
                    "duplicate": True,
                    "tx_hash": tx_hash,
                    "event_tx_hash": event_tx,
                    "log_index": int(log_index or 0),
                    "recipient": recipient,
                    "amount": amount,
                    "mode": self._mode,
                    "credit_key": claim.get("credit_key"),
                }
        else:
            self.db.update_balance(recipient, amount)
            self.db.save_bridge_credit(
                event_tx, recipient, amount, from_chain, log_index=int(log_index or 0)
            )
            self.db.confirm_bridge_lock(tx_hash)

        if self._simulator:
            self._simulator.confirm_transaction(tx_hash)

        if self.bus:
            self.bus.emit("bridge.confirmed", {
                "tx_hash": tx_hash,
                "event_tx_hash": event_tx,
                "log_index": int(log_index or 0),
                "recipient": recipient,
                "amount": amount,
                "from_chain": from_chain,
            })

        return {
            "confirmed": True,
            "tx_hash": tx_hash,
            "event_tx_hash": event_tx,
            "log_index": int(log_index or 0),
            "recipient": recipient,
            "amount": amount,
            "mode": self._mode,
            "l1_event_bound": bool(
                getattr(self.config, "bridge_require_l1_event", False)
                and str(getattr(self.config, "bridge_l1_lock_contract", "") or "").strip()
            ),
            "l1_event_abi_decoded": False,
            "credit_key": credit_key,
        }

    def refund(self, tx_hash: str) -> Dict:
        """Возвращает заблокированные средства при ошибке."""
        if hasattr(self.db, "refund_pending_bridge_lock"):
            return self.db.refund_pending_bridge_lock(tx_hash)
        return {"refunded": False, "error": "refund_pending_bridge_lock unavailable"}

    # ── Информация ───────────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        sim_stats = (
            self._simulator.get_bridge_stats()
            if self._simulator
            else {"enabled": False, "reason": "simulator disabled"}
        )
        locks = self.db.get_bridge_locks(limit=1000)
        require_event = bool(getattr(self.config, "bridge_require_l1_event", False))
        lock_contract = str(getattr(self.config, "bridge_l1_lock_contract", "") or "").strip()
        event_mode = (
            "contract_log_address" if require_event and lock_contract else "confirmations_only"
        )
        return {
            "mode": self._mode,
            "supported_chains": self.SUPPORTED_CHAINS,
            "bridge_fees": self.BRIDGE_FEES,
            "total_locks": len(locks),
            "pending_locks": sum(1 for l in locks if l["status"] == "pending"),
            "confirmed_locks": sum(1 for l in locks if l["status"] == "confirmed"),
            "dev_simulator_stats": sim_stats,
            # Address-level log binding when BRIDGE_REQUIRE_L1_EVENT — not ABI decode.
            "l1_event_bound": bool(require_event and lock_contract),
            "l1_event_abi_decoded": False,
            "event_binding_mode": event_mode,
            "replay_key": "from_chain:event_tx_hash:log_index",
        }

    def estimate_fee(self, to_chain: str, amount: float) -> Dict:
        fee_rate = self.BRIDGE_FEES.get(to_chain.lower(), 0.01)
        fee = amount * fee_rate
        return {
            "chain": to_chain,
            "amount": amount,
            "fee": fee,
            "fee_pct": fee_rate * 100,
            "net_amount": amount - fee,
        }

    # ── Служебные методы ─────────────────────────────────────────────────────

    def _on_incoming(self, event: Dict):
        """EventBus колбэк для входящих бридж-транзакций."""
        if isinstance(event, dict):
            self.confirm_incoming(
                tx_hash=event.get("tx_hash", ""),
                recipient=event.get("recipient", ""),
                amount=float(event.get("amount", 0)),
                from_chain=event.get("from_chain", ""),
            )

    def confirm_lock(self, tx_hash: str, l1_tx_hash: str = "") -> Dict:
        """Confirm outbound bridge lock (oracle / admin). No balance change — funds already locked."""
        locks = self.db.get_bridge_locks(limit=1000)
        for lock in locks:
            if lock["tx_hash"] == tx_hash and lock["status"] == "pending":
                if self._mode == "rust":
                    proof_tx = l1_tx_hash or self._lookup_outbound_l1_hash(tx_hash)
                    rust_args = {
                        "tx_hash": tx_hash,
                        "to_chain": self._normalize_chain(lock.get("to_chain", "")),
                    }
                    if proof_tx:
                        rust_args["l1_tx_hash"] = proof_tx
                    elif self._is_prod and getattr(self.config, "bridge_require_l1_proof", False):
                        return {
                            "confirmed": False,
                            "error": "l1_tx_hash required for outbound confirm in production",
                        }
                    if not self._call_rust_ok("confirm", rust_args):
                        return {"confirmed": False, "error": "rust confirm failed"}
                elif self._mode != "simulator":
                    return {"confirmed": False, "error": "bridge unavailable: rust binary missing or bridge mode invalid"}
                if self._simulator:
                    self._simulator.confirm_transaction(tx_hash)
                self.db.confirm_bridge_lock(tx_hash)
                if self.bus:
                    self.bus.emit("bridge.confirmed", {
                        "tx_hash": tx_hash,
                        "direction": "outbound",
                        "to_chain": lock.get("to_chain", ""),
                    })
                return {
                    "confirmed": True,
                    "tx_hash": tx_hash,
                    "direction": "outbound",
                    "mode": self._mode,
                }
        return {"confirmed": False, "error": "pending lock not found"}

    def confirm_pending_locks(self) -> Dict:
        """Confirm every pending outbound bridge lock (devnet / manual batch)."""
        confirmed: List[str] = []
        errors: List[Dict] = []
        for lock in self.db.get_bridge_locks(limit=1000):
            if lock.get("status") != "pending":
                continue
            tx_hash = lock.get("tx_hash", "")
            result = self.confirm_lock(tx_hash)
            if result.get("confirmed"):
                confirmed.append(tx_hash)
            else:
                errors.append({"tx_hash": tx_hash, "error": result.get("error", "failed")})
        return {
            "success": len(confirmed) > 0,
            "confirmed": confirmed,
            "count": len(confirmed),
            "pending_remaining": sum(
                1 for l in self.db.get_bridge_locks(limit=1000) if l.get("status") == "pending"
            ),
            "errors": errors,
            "mode": self._mode,
        }

    def _process_pending(self):
        """
        Auto-confirm pending outbound locks when bridge_auto_confirm_sec > 0.
        Set bridge_auto_confirm_sec=0 for manual oracle confirmation only.
        """
        sec = int(getattr(self.config, "bridge_auto_confirm_sec", 0) or 0)
        if self._mode != "simulator" or sec <= 0 or not self._simulator:
            return
        locks = self.db.get_bridge_locks()
        now = int(time.time())
        for lock in locks:
            if lock["status"] == "pending" and now - lock["created_at"] > sec:
                self.confirm_lock(lock["tx_hash"])

    def _resolve_rust_bin(self) -> Optional[str]:
        path = getattr(self.config, "resolve_rust_bridge_path", None)
        if callable(path):
            resolved = self.config.resolve_rust_bridge_path()
            return resolved if os.path.isfile(resolved) else None
        for candidate in (
            self.config.rust_bridge_path,
            self.config.rust_bridge_path + ".exe",
        ):
            if os.path.isfile(candidate):
                return candidate
        return None

    def _mint_abs_lock_hash(
        self,
        from_addr: str,
        to_chain: str,
        to_addr: str,
        net_amount: float,
    ) -> str:
        """Deterministic ABS-side lock receipt (not a synthetic L1 tx hash)."""
        from crypto import native

        ts = int(time.time())
        chain_id = int(getattr(self.config, "chain_id", 0) or 0)
        digest = native.hash_text(
            f"abs_bridge_lock|{chain_id}|{from_addr}|{to_chain}|{to_addr}|{net_amount}|{ts}"
        )
        return f"0x{digest}"

    def _lookup_outbound_l1_hash(self, abs_tx_hash: str) -> str:
        from bridge.l1_rpc import load_l1_queue

        path = getattr(self.config, "bridge_l1_queue_path", "data/bridge_l1_queue.json")
        queue = load_l1_queue(path)
        for entry in queue.get("outbound", []):
            if entry.get("abs_tx_hash") == abs_tx_hash or entry.get("tx_hash") == abs_tx_hash:
                return str(entry.get("l1_tx_hash") or "")
        return ""

    def _rust_subprocess_env(self) -> Dict[str, str]:
        env = dict(os.environ)
        if self._is_prod:
            env.pop("BRIDGE_ALLOW_SYNTHETIC", None)
        elif str(env.get("BRIDGE_ALLOW_SYNTHETIC", "")).lower() in ("1", "true", "yes", "on"):
            for key in (
                "ETH_RPC_URL",
                "BSC_RPC_URL",
                "POLYGON_RPC_URL",
                "BRIDGE_REQUIRE_L1_PROOF",
                "BRIDGE_REQUIRE_L1_EVENT",
            ):
                env.pop(key, None)
        lock = str(getattr(self.config, "bridge_l1_lock_contract", "") or "").strip()
        if lock:
            env["BRIDGE_L1_LOCK_CONTRACT"] = lock
        if getattr(self.config, "bridge_require_l1_event", False):
            env["BRIDGE_REQUIRE_L1_EVENT"] = "1"
        elif "BRIDGE_REQUIRE_L1_EVENT" not in env:
            env["BRIDGE_REQUIRE_L1_EVENT"] = "0"
        return env

    def _call_rust(self, command: str, args: Dict) -> Optional[str]:
        """Вызывает Rust-бинарник через subprocess и возвращает tx_hash."""
        out = self._call_rust_raw(command, args)
        return out.get("tx_hash") if out else None

    def _call_rust_ok(self, command: str, args: Dict) -> bool:
        out = self._call_rust_raw(command, args)
        if not out:
            return False
        if out.get("status") != "ok":
            return False
        if command in ("confirm", "incoming", "status", "lock"):
            return True
        return bool(out.get("tx_hash"))

    def _call_rust_raw(self, command: str, args: Dict) -> Optional[Dict]:
        """Вызывает Rust-бинарник и возвращает полный JSON-ответ."""
        exe = self._rust_bin or self._resolve_rust_bin()
        if not exe:
            self._rust_bin_fail += 1
            self._rust_last_error = "rust_binary_missing"
            return None
        try:
            payload = json.dumps({"command": command, "args": args})
            result = subprocess.run(
                [exe],
                input=payload.encode(),
                capture_output=True,
                timeout=10,
                env=self._rust_subprocess_env(),
            )
            if result.returncode == 0:
                try:
                    return json.loads(result.stdout.decode())
                except json.JSONDecodeError as e:
                    self._rust_decode_fail += 1
                    self._rust_last_error = f"decode:{e}"
                    print(f"[Bridge] Rust JSON decode failed: {e}.")
                    return None
            self._rust_cmd_fail += 1
            err = (result.stderr or b"").decode(errors="replace").strip()
            out = (result.stdout or b"").decode(errors="replace").strip()
            self._rust_last_error = err or f"rc={result.returncode}"
            print(
                f"[Bridge] Rust call rc={result.returncode}"
                f"{(': ' + err) if err else ''}"
                f"{(' stdout=' + out[:200]) if out else ''}"
            )
        except subprocess.TimeoutExpired as e:
            self._rust_timeout += 1
            self._rust_last_error = "timeout"
            print(f"[Bridge] Rust call failed: {e}.")
        except FileNotFoundError as e:
            self._rust_bin_fail += 1
            self._rust_last_error = str(e)
            print(f"[Bridge] Rust call failed: {e}.")
        except Exception as e:
            self._rust_cmd_fail += 1
            self._rust_last_error = str(e)
            print(f"[Bridge] Rust call failed: {e}.")
        return None

    def get_ops_errors(self) -> Dict:
        """Operational counters for metrics / status honesty."""
        return {
            "rust_decode_fail": int(self._rust_decode_fail),
            "rust_timeout": int(self._rust_timeout),
            "rust_bin_fail": int(self._rust_bin_fail),
            "rust_cmd_fail": int(self._rust_cmd_fail),
            "last_error": self._rust_last_error or "",
            "mode": getattr(self, "_mode", "unknown"),
            "running": bool(self._running),
        }
