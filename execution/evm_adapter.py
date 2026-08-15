#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EVM Adapter — подключает evm_interpreter.py к живому состоянию блокчейна.

Обеспечивает:
  - Деплой смарт-контрактов (сохранение байткода в БД)
  - Вызов методов контрактов (загрузка/сохранение storage из БД)
  - Оценка газа
"""

import json
import sys
import os
import time
from typing import Optional, Dict, Any, List

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from evm_interpreter import EVM, EVMContext
from crypto import native
from storage.database import Database
from runtime.config import Config


class EVMResult:
    """Результат выполнения EVM-транзакции."""

    def __init__(self, success: bool, return_value: Any = None,
                 gas_used: int = 0, error: str = "", logs: list = None,
                 storage_changes: Dict = None):
        self.success = success
        self.return_value = return_value
        self.gas_used = gas_used
        self.error = error
        self.logs = logs or []
        self.storage_changes = storage_changes or {}

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "return_value": self.return_value,
            "gas_used": self.gas_used,
            "error": self.error,
            "logs": self.logs,
            "storage_changes": self.storage_changes,
        }


class EVMAdapter:
    """
    Адаптер EVM: связывает evm_interpreter.EVM с хранилищем узла.
    Загружает/сохраняет storage и bytecode в Database.
    """

    def __init__(self, db: Database, config: Config):
        self.db = db
        self.config = config
        self._storage_decode_failures = 0
        self._calldata_decode_failures = 0
        # v1.3.67: tx-scoped nested writeback journal (commit once on top-level success)
        self._writeback_journal: List[Dict[str, Any]] = []
        self._writeback_journaling = False

    def begin_writeback_journal(self) -> None:
        """Start buffering nested writeback ops (Priority 33 / v1.3.67)."""
        self._writeback_journal = []
        self._writeback_journaling = True

    def discard_writeback_journal(self) -> None:
        self._writeback_journal = []
        self._writeback_journaling = False

    def commit_writeback_journal(self) -> int:
        """Flush buffered nested ops once, then clear journal."""
        ops = list(self._writeback_journal)
        self._writeback_journal = []
        self._writeback_journaling = False
        if ops:
            self._apply_nested_writeback_ops_now(ops)
        return len(ops)

    def _code_bytes(self, addr: str) -> bytes:
        view = self._account_view(addr)
        if view.get("ok") and not view.get("corrupt"):
            code = bytes(view.get("code_bytes") or b"")
            if code:
                return code
        account = self.db.get_account(self._normalize_addr(addr))
        if not account or not account.get("code"):
            return b""
        try:
            return bytes.fromhex(account["code"].replace("0x", ""))
        except ValueError:
            return b""

    def _selfdestruct_contract(self, contract_addr: str, beneficiary: str) -> None:
        contract_addr = self._normalize_addr(contract_addr)
        beneficiary = self._normalize_addr(beneficiary)
        account = self.db.get_account(contract_addr) or {}
        balance = float(account.get("balance", 0) or 0)
        if balance > 0:
            self.db.update_balance(beneficiary, balance)
            self.db.update_balance(contract_addr, -balance)
        self.db.save_account(
            contract_addr,
            balance=0.0,
            nonce=int(account.get("nonce", 0) or 0),
            code="",
            storage="{}",
        )

    def _block_hash_word(self, height: int) -> int:
        current = int(self.db.get_chain_tip() if hasattr(self.db, "get_chain_tip") else 0)
        h = int(height)
        if h < 0 or h >= current or h < current - 256:
            return 0
        blk = self.db.get_block(h)
        if not blk:
            return 0
        raw = (blk.get("hash") or "").replace("0x", "")
        if len(raw) < 64:
            raw = raw.ljust(64, "0")
        return int.from_bytes(bytes.fromhex(raw[:64]), "big")

    def _persist_logs(
        self,
        contract_addr: str,
        logs: List[Dict],
        tx_hash: str = "",
    ) -> None:
        if not logs or not hasattr(self.db, "save_evm_logs"):
            return
        tip = int(self.db.get_chain_tip() if hasattr(self.db, "get_chain_tip") else 0)
        self.db.save_evm_logs(contract_addr, logs, block_height=tip, tx_hash=tx_hash)

    def _make_context(self, caller: str, contract_addr: str = "",
                      calldata: bytes = b"", value: int = 0,
                      *, read_only: bool = False) -> EVMContext:
        tip = self.db.get_chain_tip() if hasattr(self.db, "get_chain_tip") else 0
        last = self.db.get_last_block() if hasattr(self.db, "get_last_block") else None
        ts = int(last.get("timestamp", 0)) if last else int(time.time())

        def _selfdestruct(beneficiary: str) -> None:
            if read_only:
                raise RuntimeError("static_selfdestruct_rejected")
            self._selfdestruct_contract(contract_addr, beneficiary)

        ctx = EVMContext(
            caller=caller or "",
            origin=caller or "",
            address=contract_addr or "",
            calldata=calldata or b"",
            value=int(value),
            block_number=int(tip),
            timestamp=ts,
            chain_id=int(getattr(self.config, "chain_id", 77777)),
            balance_of=lambda addr: int(self.db.get_balance(addr) * 10**18),
            code_size_of=lambda addr: len(self._code_bytes(addr)),
            code_copy_of=lambda addr, off, size: self._code_bytes(addr)[off:off + size],
            selfdestruct=_selfdestruct,
            block_hash_of=self._block_hash_word,
        )
        return ctx

    def _loads_contract_storage(self, storage_raw: Any) -> Optional[Dict[int, int]]:
        """Fail-closed storage decode; None means corrupt."""
        if hasattr(native, "account_storage_map_from_raw"):
            out = native.account_storage_map_from_raw(storage_raw)
            if out is None:
                self._storage_decode_failures += 1
            return out
        try:
            raw = storage_raw or "{}"
            if isinstance(raw, dict):
                parsed = raw
            else:
                parsed = json.loads(raw)
            return {int(k): int(v) for k, v in parsed.items()}
        except Exception:
            self._storage_decode_failures += 1
            return None

    def _account_view(self, addr: str) -> Dict[str, Any]:
        """Native-preferring account view for nested CALL preload (v1.3.58)."""
        addr = self._normalize_addr(addr)
        engine = getattr(self.db, "_engine", None)
        if engine is None:
            core = getattr(self.db, "_core", None)
            engine = getattr(core, "_engine", None) if core is not None else None
        if engine is not None and hasattr(engine, "get_account_view"):
            try:
                view = dict(engine.get_account_view(addr))
                if view.get("native_account_view"):
                    if view.get("ok") and not view.get("corrupt"):
                        storage = view.get("storage") or {}
                        view["storage"] = {int(k): int(v) for k, v in dict(storage).items()}
                        code_bytes = view.get("code_bytes") or b""
                        view["code_bytes"] = bytes(code_bytes)
                    return view
            except Exception:
                pass
        account = self.db.get_account(addr) if hasattr(self.db, "get_account") else None
        return native.account_view_from_row(account)

    def _normalize_addr(self, word_or_addr: str) -> str:
        raw = str(word_or_addr).replace("0x", "").lower()
        if len(raw) <= 40 and all(c in "0123456789abcdef" for c in raw):
            return "0x" + raw.rjust(40, "0")[-40:]
        return word_or_addr

    def _precompile_nested_call(
        self, target: str, calldata: bytes, gas: int
    ) -> Optional[Dict[str, Any]]:
        """Apply-path CALL/STATICCALL into 0x01–0x09. None if not a precompile."""
        from execution.evm_precompiles import is_precompile, try_precompile

        if not is_precompile(target):
            return None
        pre = try_precompile(target, bytes(calldata or b"").hex())
        if pre is None:
            return {
                "success": False,
                "reverted": True,
                "return_data": b"",
                "gas_used": 0,
                "error": "precompile_unhandled",
            }
        ret = pre.return_value
        if isinstance(ret, (bytes, bytearray)):
            ret_b = bytes(ret)
        elif ret is None:
            ret_b = b""
        elif isinstance(ret, int):
            ret_b = int(ret).to_bytes(32, "big")
        else:
            ret_b = bytes(ret)
        used = int(pre.gas_used or 0)
        limit = int(gas or 0)
        if limit > 0 and used > limit:
            return {
                "success": False,
                "reverted": True,
                "return_data": b"",
                "gas_used": limit,
                "error": "precompile_out_of_gas",
            }
        if not pre.success:
            return {
                "success": False,
                "reverted": True,
                "return_data": ret_b,
                "gas_used": used,
                "error": str(pre.error or "precompile_failed"),
            }
        return {
            "success": True,
            "reverted": False,
            "return_data": ret_b,
            "gas_used": used,
        }

    @staticmethod
    def _nested_call_kind(delegate: bool, static: bool, callcode: bool) -> str:
        if static:
            return "staticcall"
        if delegate:
            return "delegatecall"
        if callcode:
            return "callcode"
        return "call"

    @staticmethod
    def _writeback_ops_without_storage(ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Drop set_storage / append_logs for callees that did not execute bytecode.

        Empty ``{}`` storage would wipe a DELEGATECALL caller or stamp a fake
        account at a precompile / EOA. Value transfer still applies.
        """
        keep: List[Dict[str, Any]] = []
        for op in ops or []:
            kind = str(op.get("op") or "")
            if kind in ("set_storage", "append_logs"):
                continue
            keep.append(op)
        return keep

    def _finish_no_code_nested_call(
        self,
        kind: str,
        parent_ro: bool,
        caller: str,
        target: str,
        call_value: int,
        base: Dict[str, Any],
    ) -> Dict[str, Any]:
        plan = native.evm_plan_nested_call_writeback(
            kind,
            parent_ro,
            caller,
            target,
            int(call_value or 0),
            True,
            None,
            None,
        )
        ops = self._writeback_ops_without_storage(list(plan.get("ops") or []))
        if ops:
            self._apply_nested_writeback_ops(ops)
        out = dict(base)
        if ops:
            out["native_writeback_ops"] = len(ops)
        return out

    def _caller_covers_call_value(self, caller: str, value_wei: int) -> bool:
        """Fail-closed: nested CALL value must be covered in satoshi (no writeback mint).

        Writeback converts wei→sat as ``wei // 10**12`` (1 ABS = 1e18 wei = 1e6 sat).
        Dust below one satoshi is a no-op transfer and does not fail the CALL.
        """
        need_wei = int(value_wei or 0)
        if need_wei <= 0:
            return True
        sat_need = need_wei // 1_000_000_000_000
        if sat_need <= 0:
            return True
        addr = self._normalize_addr(caller)
        if hasattr(self.db, "get_balance_satoshi"):
            have_sat = int(self.db.get_balance_satoshi(addr) or 0)
        else:
            have_sat = int(self.db.get_balance(addr) * 1_000_000)
        return have_sat >= sat_need

    def _abs_covers(self, addr: str, amount_abs: float) -> bool:
        from runtime.amount import to_satoshi

        need = int(to_satoshi(amount_abs or 0))
        if need <= 0:
            return True
        have = int(self.db.get_balance_satoshi(self._normalize_addr(addr)) or 0)
        return have >= need

    def _transfer_abs_fail_closed(
        self, from_addr: str, to_addr: str, amount_abs: float
    ) -> Optional[str]:
        """Move ABS value once in satoshi. None on success. No clamp-to-zero mint."""
        from runtime.amount import to_satoshi

        return self._transfer_sat_fail_closed(
            from_addr, to_addr, int(to_satoshi(amount_abs or 0))
        )

    def _transfer_sat_fail_closed(
        self, from_addr: str, to_addr: str, sat: int
    ) -> Optional[str]:
        from runtime.amount import from_satoshi_float

        need = int(sat or 0)
        if need <= 0:
            return None
        from_addr = self._normalize_addr(from_addr)
        to_addr = self._normalize_addr(to_addr)
        have = int(self.db.get_balance_satoshi(from_addr) or 0)
        if have < need:
            return "insufficient_call_value"
        to_have = int(self.db.get_balance_satoshi(to_addr) or 0)
        self.db.set_balance(from_addr, from_satoshi_float(have - need))
        self.db.set_balance(to_addr, from_satoshi_float(to_have + need))
        return None

    def _refund_sat(self, from_addr: str, to_addr: str, sat: int) -> None:
        err = self._transfer_sat_fail_closed(from_addr, to_addr, sat)
        if err:
            raise RuntimeError(err)

    def _contract_call_hook(self, target: str, calldata: bytes, value: int,
                            gas: int, delegate: bool, static: bool,
                            caller_ctx: EVMContext,
                            callcode: bool = False) -> Dict[str, Any]:
        target = self._normalize_addr(target)
        kind = self._nested_call_kind(delegate, static, callcode)
        parent_ro = bool(getattr(caller_ctx, "_abs_read_only", False))
        call_value = 0 if delegate else int(value or 0)
        if (
            call_value > 0
            and kind in ("call", "callcode")
            and not parent_ro
            and not self._caller_covers_call_value(caller_ctx.address, call_value)
        ):
            # Same as native inline Insufficient: CALL returns 0, no child, no mint.
            return {
                "success": False,
                "reverted": False,
                "return_data": b"",
                "gas_used": 0,
                "error": "insufficient_call_value",
            }
        pre_out = self._precompile_nested_call(target, calldata, gas)
        if pre_out is not None:
            if pre_out.get("reverted"):
                return pre_out
            return self._finish_no_code_nested_call(
                kind, parent_ro, caller_ctx.address, target, call_value, pre_out
            )
        view = self._account_view(target)
        if view.get("corrupt"):
            return {"success": False, "reverted": True, "return_data": b"", "error": "corrupt_storage"}
        bytecode = bytes(view.get("code_bytes") or b"")
        if not bytecode:
            # Fallback: legacy account row may still have code when view missed it.
            account = self.db.get_account(target)
            if account and account.get("code"):
                try:
                    bytecode = bytes.fromhex(str(account["code"]).replace("0x", ""))
                except ValueError:
                    return {"success": False, "reverted": True, "return_data": b""}
                if not bytecode:
                    return self._finish_no_code_nested_call(
                        kind,
                        parent_ro,
                        caller_ctx.address,
                        target,
                        call_value,
                        {
                            "success": True,
                            "reverted": False,
                            "return_data": b"",
                            "gas_used": 0,
                        },
                    )
            else:
                # Yellow-paper empty account: CALL succeeds, returndata empty.
                return self._finish_no_code_nested_call(
                    kind,
                    parent_ro,
                    caller_ctx.address,
                    target,
                    call_value,
                    {
                        "success": True,
                        "reverted": False,
                        "return_data": b"",
                        "gas_used": 0,
                    },
                )
            account_row = account
        else:
            account_row = self.db.get_account(target) or {
                "address": target,
                "storage": "{}",
                "code": view.get("code") or "",
            }

        if delegate or callcode:
            # v1.3.70: prefer in-flight parent storage (arena-flushed dict) so
            # recursive DELEGATECALL/CALLCODE sees parent SSTOREs, not stale DB.
            live = getattr(caller_ctx, "_abs_live_storage", None)
            if isinstance(live, dict):
                storage = live
            else:
                caller_view = self._account_view(caller_ctx.address)
                if caller_view.get("corrupt"):
                    return {"success": False, "reverted": True, "return_data": b"", "error": "corrupt_storage"}
                storage = dict(caller_view.get("storage") or {})
                if not storage and caller_view.get("missing"):
                    storage_raw = self.db.get_account(caller_ctx.address)
                    storage_src = (storage_raw or {}).get("storage") or "{}"
                    storage = self._loads_contract_storage(storage_src)
                    if storage is None:
                        return {"success": False, "reverted": True, "return_data": b"", "error": "corrupt_storage"}
            exec_addr = caller_ctx.address
            call_value = 0 if delegate else value
            caller = caller_ctx.caller if delegate else caller_ctx.address
        else:
            storage = dict(view.get("storage") or {})
            if view.get("missing") or (not storage and not view.get("ok")):
                storage_src = (account_row or {}).get("storage") or "{}"
                storage = self._loads_contract_storage(storage_src)
                if storage is None:
                    return {"success": False, "reverted": True, "return_data": b"", "error": "corrupt_storage"}
            exec_addr = target
            call_value = value
            caller = caller_ctx.address

        plan_pre = native.evm_plan_nested_call_effects(
            kind, parent_ro, caller_ctx.address, target, int(call_value or 0), True
        )
        nested_ro = bool(plan_pre.get("nested_read_only"))
        sub_ctx = self._make_context(
            caller, exec_addr, calldata, call_value, read_only=nested_ro
        )
        sub_ctx._abs_read_only = nested_ro
        # Same object the runner mutates — recursive DELEGATECALL reads it (v1.3.70).
        sub_ctx._abs_live_storage = storage
        sub_ctx.contract_call = lambda t, d, v, g, delg, st, cc=False: self._contract_call_hook(
            t, d, v, g, delg, st, sub_ctx, callcode=cc
        )
        if nested_ro or plan_pre.get("reject_create"):
            sub_ctx.contract_create = lambda code, val, ctx, salt=None: {
                "success": False,
                "reverted": True,
                "gas_used": 0,
                "error": "static_create_rejected",
            }
        else:
            sub_ctx.contract_create = lambda code, val, ctx, salt=None: self._contract_create_hook(
                code, val, ctx, salt
            )

        result: Optional[Dict[str, Any]] = None
        gas_budget = int(gas or self.config.evm_gas_limit)
        host_ctx_for_wb: Any = None
        # v1.3.55: bridge-eligible (BALANCE/EXTCODE*) via nested pure + allow_bridge.
        if native.evm_bytecode_is_nested_native_eligible(bytecode):
            try:
                host_ctx_for_wb = native.evm_host_context_from_evm(sub_ctx)
                nested = native.evm_run_nested_pure_frame(
                    bytecode,
                    gas_budget,
                    bytes(calldata or b""),
                    host_ctx_for_wb,
                    storage,
                    allow_bridge=True,
                )
                reason = str(nested.get("stop_reason") or "")
                if reason in ("halt", "return", "revert", "out_of_gas"):
                    reverted = bool(nested.get("reverted")) or reason == "out_of_gas"
                    result = {
                        "success": (not reverted) and reason in ("halt", "return"),
                        "reverted": reverted,
                        "return_data": nested.get("return_data", b"") or b"",
                        "storage": nested.get("storage", dict(storage)),
                        "gas_used": int(nested.get("gas_used", 0) or 0),
                        "logs": [],
                        "native_nested_pure": True,
                        "native_nested_bridge": True,
                    }
            except Exception:
                result = None

        # v1.3.56: recursive CALL/CREATE/LOG via Rust runner + runtime host_bridge.
        if result is None and hasattr(native, "evm_run_nested_host_frame"):
            try:
                from execution.evm_host_bridge import make_evm_runtime_bridge

                evm = EVM(gas_limit=gas_budget, context=sub_ctx)
                evm.storage = storage
                bridge = make_evm_runtime_bridge(evm)
                host_ctx_for_wb = native.evm_host_context_from_evm(sub_ctx)
                nested = native.evm_run_nested_host_frame(
                    bytecode,
                    gas_budget,
                    bytes(calldata or b""),
                    host_ctx_for_wb,
                    evm.storage,
                    bridge,
                )
                reason = str(nested.get("stop_reason") or "")
                if reason in ("halt", "return", "revert", "out_of_gas"):
                    evm.gas_used = int(nested.get("gas_used", 0) or 0)
                    evm.return_data = bytes(nested.get("return_data", b"") or b"")
                    evm.reverted = bool(nested.get("reverted")) or reason == "out_of_gas"
                    evm.running = bool(nested.get("running", False))
                    if "stack" in nested:
                        evm.stack = [int(x) for x in nested["stack"]]
                    if "memory" in nested:
                        evm.memory = bytearray(nested["memory"])
                    reverted = bool(evm.reverted)
                    result = {
                        "success": (not reverted) and reason in ("halt", "return"),
                        "reverted": reverted,
                        "return_data": evm.return_data,
                        "storage": nested.get("storage", dict(evm.storage)),
                        "gas_used": int(evm.gas_used),
                        "logs": list(nested.get("logs") or evm.logs),
                        "native_nested_host": True,
                    }
            except Exception:
                result = None

        if result is None:
            evm = EVM(gas_limit=gas_budget, context=sub_ctx)
            evm.storage = dict(storage)
            result = evm.execute_bytecode(bytecode)

        success = not result.get("reverted")
        plan = native.evm_plan_nested_call_writeback(
            kind,
            parent_ro,
            caller_ctx.address,
            target,
            int(call_value or 0),
            success,
            result.get("storage"),
            result.get("logs"),
        )

        # Fail-closed: never persist storage/value/logs for reverted nested calls.
        if not result.get("reverted"):
            ops = list(plan.get("ops") or [])
            # v1.3.83: flush inline value transfers planned on bridge_state.
            inline_ops = self._take_bridge_pending_writeback(host_ctx_for_wb)
            if inline_ops:
                ops.extend(inline_ops)
            native_flags = {
                k: result[k]
                for k in (
                    "native_nested_pure",
                    "native_nested_bridge",
                    "native_nested_host",
                )
                if k in result
            }
            if inline_ops:
                native_flags["native_inline_writeback"] = True
                native_flags["native_inline_writeback_ops"] = len(inline_ops)
            if not ops:
                return {
                    "success": success,
                    "reverted": False,
                    "return_data": result.get("return_data", b"") or b"",
                    "gas_used": result.get("gas_used", 0),
                    **native_flags,
                }

            self._apply_nested_writeback_ops(ops)

            return {
                "success": success,
                "reverted": False,
                "return_data": result.get("return_data", b"") or b"",
                "storage": result.get("storage", {}),
                "gas_used": result.get("gas_used", 0),
                "logs": result.get("logs", []),
                "native_writeback_ops": len(ops),
                **native_flags,
            }

        return {
            "success": False,
            "reverted": True,
            "return_data": result.get("return_data", b"") or b"",
            "gas_used": result.get("gas_used", 0),
        }

    def _take_bridge_pending_writeback(self, host_ctx: Any) -> List[Dict[str, Any]]:
        """Pop Rust-planned inline transfer_value ops (v1.3.83)."""
        if host_ctx is None:
            return []
        try:
            bs = host_ctx.get("bridge_state")
            if bs is None:
                return []
            raw = None
            if hasattr(bs, "pop"):
                raw = bs.pop("pending_writeback_ops", None)
            elif hasattr(bs, "get"):
                raw = bs.get("pending_writeback_ops")
                if raw is not None:
                    try:
                        del bs["pending_writeback_ops"]
                    except Exception:
                        pass
            if not raw:
                return []
            out: List[Dict[str, Any]] = []
            for item in list(raw):
                out.append(dict(item))
            return out
        except Exception:
            return []

    def _writeback_store(self):
        """Rocks/hybrid store exposing commit_writeback_accounts (v1.3.62)."""
        if hasattr(self.db, "commit_writeback_accounts"):
            return self.db
        core = getattr(self.db, "_core", None)
        if core is not None and hasattr(core, "commit_writeback_accounts"):
            return core
        return None

    def _apply_nested_writeback_ops(self, ops: List[Dict[str, Any]]) -> None:
        """Buffer into tx journal when active; otherwise apply immediately (v1.3.67)."""
        if not ops:
            return
        if self._writeback_journaling:
            self._writeback_journal.extend(list(ops))
            return
        self._apply_nested_writeback_ops_now(ops)

    def _apply_nested_writeback_ops_now(self, ops: List[Dict[str, Any]]) -> None:
        """Apply writeback ops: native apply + Rocks preload/bundle (v1.3.64+)."""
        if not ops:
            return
        if hasattr(native, "evm_apply_writeback_ops"):
            try:
                touch_addrs: List[str] = []
                seen = set()
                for op in ops:
                    for key in ("address", "from", "to"):
                        raw = op.get(key)
                        if not raw:
                            continue
                        addr = self._normalize_addr(str(raw))
                        if addr in seen:
                            continue
                        seen.add(addr)
                        touch_addrs.append(addr)
                store = self._writeback_store()
                if store is not None and hasattr(store, "load_writeback_accounts"):
                    accounts = store.load_writeback_accounts(touch_addrs)
                else:
                    accounts = {}
                    for addr in touch_addrs:
                        row = (
                            self.db.get_account(addr)
                            if hasattr(self.db, "get_account")
                            else None
                        )
                        accounts[addr] = dict(row) if row else {
                            "address": addr,
                            "balance_satoshi": 0,
                            "balance": 0.0,
                            "nonce": 0,
                            "code": "",
                            "storage": "{}",
                        }
                # Normalize op addresses for native apply.
                norm_ops = []
                for op in ops:
                    item = dict(op)
                    for key in ("address", "from", "to"):
                        if key in item and item[key]:
                            item[key] = self._normalize_addr(str(item[key]))
                    norm_ops.append(item)
                applied = native.evm_apply_writeback_ops(accounts, norm_ops)
                rows = dict(applied.get("accounts") or {})
                log_batches = list(applied.get("log_batches") or [])
                if store is not None and hasattr(store, "commit_writeback_bundle"):
                    tip = int(
                        self.db.get_chain_tip() if hasattr(self.db, "get_chain_tip") else 0
                    )
                    store.commit_writeback_bundle(
                        rows,
                        log_batches,
                        block_height=tip,
                        tx_hash="",
                    )
                else:
                    if store is not None and rows:
                        store.commit_writeback_accounts(rows)
                    else:
                        for addr, row in rows.items():
                            storage = row.get("storage")
                            if isinstance(storage, dict):
                                storage_str = json.dumps(
                                    {str(k): int(v) for k, v in storage.items()}
                                )
                            else:
                                storage_str = str(storage or "{}")
                            self.db.save_account(
                                address=self._normalize_addr(str(addr)),
                                balance=float(row.get("balance") or 0.0),
                                nonce=int(row.get("nonce") or 0),
                                code=str(row.get("code") or "")
                                if row.get("code") is not None
                                else "",
                                storage=storage_str,
                            )
                    for batch in log_batches:
                        addr = self._normalize_addr(str(batch.get("address") or ""))
                        logs = list(batch.get("logs") or [])
                        if logs:
                            self._persist_logs(addr, logs)
                return
            except Exception as exc:
                if "insufficient_writeback_value" in str(exc):
                    raise
                pass
        # Fallback: per-op Python DB apply.
        for op in ops:
            kind = str(op.get("op") or "")
            if kind == "set_storage":
                addr = self._normalize_addr(str(op.get("address") or ""))
                storage = op.get("storage") or {}
                new_storage = {str(k): int(v) for k, v in dict(storage).items()}
                self.db.update_account_storage(addr, new_storage)
            elif kind == "save_account":
                addr = self._normalize_addr(str(op.get("address") or ""))
                storage = op.get("storage")
                if isinstance(storage, dict):
                    storage_str = json.dumps({str(k): int(v) for k, v in storage.items()})
                else:
                    storage_str = str(storage or "{}")
                self.db.save_account(
                    address=addr,
                    balance=float(op.get("balance") or 0.0),
                    nonce=int(op.get("nonce") or 0),
                    code=str(op.get("code") or ""),
                    storage=storage_str,
                )
            elif kind == "transfer_value":
                value_wei = int(op.get("value_wei") or 0)
                if value_wei <= 0:
                    continue
                from_addr = self._normalize_addr(str(op.get("from") or ""))
                to_addr = self._normalize_addr(str(op.get("to") or ""))
                sat_need = value_wei // 1_000_000_000_000
                if sat_need > 0:
                    have = int(self.db.get_balance_satoshi(from_addr) or 0)
                    if have < sat_need:
                        raise RuntimeError("insufficient_writeback_value")
                wei_to_abs = value_wei / 10**18
                self.db.update_balance(from_addr, -wei_to_abs)
                self.db.update_balance(to_addr, wei_to_abs)
            elif kind == "append_logs":
                addr = self._normalize_addr(str(op.get("address") or ""))
                logs = list(op.get("logs") or [])
                if logs:
                    self._persist_logs(addr, logs)
            else:
                raise RuntimeError(f"unsupported_nested_writeback_op:{kind}")

    def _contract_create_hook(self, init_code: bytes, value: int,
                              caller_ctx: EVMContext,
                              salt: Optional[int] = None) -> Dict[str, Any]:
        deployer = caller_ctx.address or caller_ctx.caller
        if not deployer:
            return {"success": False, "reverted": True, "gas_used": 0}
        if salt is not None:
            if getattr(self.config, "evm_create2_eip1014", False):
                contract_addr = native.evm_create2_address_eip1014(
                    deployer,
                    int(salt),
                    init_code,
                )
            else:
                contract_addr = native.evm_deploy_address_create2_legacy(
                    deployer,
                    int(salt),
                    init_code,
                )
        else:
            contract_addr = native.evm_deploy_address_create(
                deployer,
                int(caller_ctx.block_number),
                len(init_code),
            )
        endowment_sat = int(value or 0) // 1_000_000_000_000
        if endowment_sat > 0:
            if not self._caller_covers_call_value(deployer, int(value or 0)):
                return {
                    "success": False,
                    "reverted": True,
                    "gas_used": 0,
                    "error": "insufficient_call_value",
                }
            err = self._transfer_sat_fail_closed(deployer, contract_addr, endowment_sat)
            if err:
                return {
                    "success": False,
                    "reverted": True,
                    "gas_used": 0,
                    "error": err,
                }
        journal_snap = len(self._writeback_journal)
        try:
            result = self._run_evm(
                init_code, {}, self.config.evm_gas_limit,
                caller=deployer,
                contract_addr=contract_addr,
                value=value,
            )
        except Exception:
            self._writeback_journal = self._writeback_journal[:journal_snap]
            if endowment_sat > 0:
                self._refund_sat(contract_addr, deployer, endowment_sat)
            return {"success": False, "reverted": True, "gas_used": 0}

        if result.get("reverted"):
            self._writeback_journal = self._writeback_journal[:journal_snap]
            if endowment_sat > 0:
                self._refund_sat(contract_addr, deployer, endowment_sat)
            return {
                "success": False,
                "reverted": True,
                "gas_used": result.get("gas_used", 0),
            }

        ret_code = result.get("return_data") or b""
        code_hex = ret_code.hex() if ret_code else init_code.hex()
        # Endowment already on the account so constructor could spend it.
        plan = native.evm_plan_create_writeback(
            deployer,
            contract_addr,
            0,
            True,
            code_hex,
            result.get("storage"),
        )
        ops = list(plan.get("ops") or [])
        from runtime.amount import from_satoshi_float

        live = int(
            self.db.get_balance_satoshi(self._normalize_addr(contract_addr)) or 0
        )
        for op in ops:
            if str(op.get("op") or "") == "save_account":
                op["balance"] = from_satoshi_float(live)
                op["balance_satoshi"] = live
        if self._writeback_journaling:
            save_ops = [op for op in ops if str(op.get("op") or "") == "save_account"]
            rest = [op for op in ops if str(op.get("op") or "") != "save_account"]
            self._writeback_journal = (
                self._writeback_journal[:journal_snap]
                + save_ops
                + self._writeback_journal[journal_snap:]
                + rest
            )
        elif ops:
            self._apply_nested_writeback_ops(ops)

        return {
            "success": True,
            "reverted": False,
            "address": contract_addr,
            "gas_used": result.get("gas_used", 0),
            "native_create_writeback_ops": len(ops),
        }

    def _run_evm(self, bytecode: bytes, storage: Dict[int, int], gas_limit: int,
                 caller: str = "", contract_addr: str = "",
                 calldata: bytes = b"", value: int = 0,
                 *, read_only: bool = False) -> Dict:
        ctx = self._make_context(
            caller, contract_addr, calldata, value, read_only=read_only
        )
        ctx._abs_read_only = bool(read_only)
        ctx.contract_call = lambda t, d, v, g, delg, st, cc=False: self._contract_call_hook(
            t, d, v, g, delg, st, ctx, callcode=cc
        )
        if read_only:
            ctx.contract_create = lambda code, val, c, salt=None: {
                "success": False,
                "reverted": True,
                "gas_used": 0,
                "error": "static_create_rejected",
            }
        else:
            ctx.contract_create = lambda code, val, c, salt=None: self._contract_create_hook(
                code, val, c, salt
            )
        evm = EVM(gas_limit=gas_limit, context=ctx)
        evm.storage = dict(storage)
        ctx._abs_live_storage = evm.storage
        result = evm.execute_bytecode(bytecode)
        result["logs"] = evm.logs
        return result

    @staticmethod
    def _deploy_salt_to_word(salt: str) -> int:
        digest = native.keccak256_digest(str(salt).encode())
        return int.from_bytes(digest[:32], "big")

    def _resolve_deploy_address(
        self,
        deployer: str,
        bytecode: bytes,
        salt: str | None,
        block_number: int = 0,
    ) -> tuple[str | None, str | None]:
        """Block-execution deploy address (CREATE2 legacy / EIP-1014 when salted)."""
        if salt is None:
            if getattr(self.config, "evm_require_deploy_salt", False):
                return None, "deploy_salt_required"
            # Deterministic CREATE address (same rule as in-block 0xF0 hook)
            return (
                native.evm_deploy_address_create(
                    deployer, int(block_number), len(bytecode)
                ),
                None,
            )

        if getattr(self.config, "evm_create2_eip1014", False):
            salt_word = self._deploy_salt_to_word(salt)
            return native.evm_create2_address_eip1014(deployer, salt_word, bytecode), None

        return native.evm_deploy_address_create2_legacy(deployer, salt, bytecode), None

    def deploy_contract(self, deployer: str, bytecode_hex: str,
                        value: float = 0.0, gas_limit: int = 0,
                        salt: str = None, block_number: int = 0) -> EVMResult:
        """
        Деплоит смарт-контракт.
        Сохраняет байткод и начальное состояние в БД.
        Возвращает адрес контракта.
        """
        gas_limit = gas_limit or self.config.evm_gas_limit

        try:
            bytecode = bytes.fromhex(bytecode_hex.replace("0x", ""))
        except ValueError as e:
            return EVMResult(success=False, error=f"invalid_bytecode: {e}")

        if not bytecode:
            return EVMResult(success=False, error="empty_bytecode")

        from execution.evm_bytecode_validator import validate_bytecode_hex
        v = validate_bytecode_hex(bytecode_hex)
        if not v.get("valid"):
            bad = v.get("unsupported") or []
            detail = bad[0]["name"] if bad else v.get("error", "unsupported_bytecode")
            return EVMResult(success=False, error=f"bytecode_invalid:{detail}")

        contract_addr, addr_err = self._resolve_deploy_address(
            deployer,
            bytecode,
            salt,
            block_number=block_number,
        )
        if addr_err:
            return EVMResult(success=False, error=addr_err)

        if float(value or 0) > 0 and not self._abs_covers(deployer, value):
            return EVMResult(success=False, error="insufficient_deploy_value")

        from runtime.amount import from_satoshi_float, to_satoshi

        endowment_sat = int(to_satoshi(value or 0))
        if endowment_sat > 0:
            err = self._transfer_sat_fail_closed(deployer, contract_addr, endowment_sat)
            if err:
                return EVMResult(success=False, error="insufficient_deploy_value")

        # Constructor sees the endowment (BALANCE / value-CALL). Journal rolls nested ops.
        self.begin_writeback_journal()
        try:
            result = self._run_evm(
                bytecode, {}, gas_limit,
                caller=deployer,
                contract_addr=contract_addr,
                value=int(value * 10**18) if value else 0,
            )
        except Exception as e:
            self.discard_writeback_journal()
            if endowment_sat > 0:
                self._refund_sat(contract_addr, deployer, endowment_sat)
            return EVMResult(success=False, error=str(e))

        if result.get("reverted"):
            self.discard_writeback_journal()
            if endowment_sat > 0:
                self._refund_sat(contract_addr, deployer, endowment_sat)
            return EVMResult(success=False, error="constructor_reverted",
                             gas_used=result["gas_used"])

        self.commit_writeback_journal()
        live = int(self.db.get_balance_satoshi(self._normalize_addr(contract_addr)) or 0)
        self.db.save_account(
            address=contract_addr,
            balance=from_satoshi_float(live),
            nonce=0,
            code=bytecode_hex,
            storage=json.dumps(result.get("storage", {})),
        )
        self._persist_logs(contract_addr, result.get("logs", []))

        return EVMResult(
            success=True,
            return_value=contract_addr,
            gas_used=result["gas_used"],
            storage_changes=result.get("storage", {}),
            logs=result.get("logs", []),
        )

    # ── Вызов контракта ──────────────────────────────────────────────────────

    def call_contract(self, caller: str, contract_addr: str,
                      calldata_hex: str = "", value: float = 0.0,
                      gas_limit: int = 0) -> EVMResult:
        """
        Вызывает метод смарт-контракта (изменяет состояние).
        Загружает bytecode и storage из БД, после выполнения сохраняет изменения.
        """
        gas_limit = gas_limit or self.config.evm_gas_limit

        if float(value or 0) > 0 and not self._abs_covers(caller, value):
            return EVMResult(success=False, error="insufficient_call_value")

        from execution.evm_precompiles import try_precompile

        pre = try_precompile(contract_addr, calldata_hex)
        if pre is not None:
            if int(pre.gas_used or 0) > int(gas_limit):
                return EVMResult(
                    success=False,
                    error="out_of_gas",
                    gas_used=int(gas_limit),
                )
            if pre.success and float(value or 0) > 0:
                err = self._transfer_abs_fail_closed(caller, contract_addr, value)
                if err:
                    return EVMResult(success=False, error=err, gas_used=int(pre.gas_used or 0))
            return pre

        account = self.db.get_account(contract_addr)
        if not account or not account.get("code"):
            return EVMResult(success=False, error="not_a_contract")

        try:
            bytecode = bytes.fromhex(account["code"].replace("0x", ""))
        except ValueError as e:
            return EVMResult(success=False, error=f"invalid_stored_bytecode: {e}")

        storage = self._loads_contract_storage(account.get("storage") or "{}")
        if storage is None:
            return EVMResult(success=False, error="corrupt_storage")

        try:
            calldata = bytes.fromhex(calldata_hex.replace("0x", "")) if calldata_hex else b""
        except ValueError:
            return EVMResult(success=False, error="invalid_calldata")

        from runtime.amount import to_satoshi

        value_sat = int(to_satoshi(value or 0))
        if value_sat > 0:
            err = self._transfer_sat_fail_closed(caller, contract_addr, value_sat)
            if err:
                return EVMResult(success=False, error=err)

        self.begin_writeback_journal()
        try:
            result = self._run_evm(
                bytecode, storage, gas_limit,
                caller=caller,
                contract_addr=contract_addr,
                calldata=calldata,
                value=int(value * 10**18) if value else 0,
            )
        except Exception as e:
            self.discard_writeback_journal()
            if value_sat > 0:
                self._refund_sat(contract_addr, caller, value_sat)
            return EVMResult(success=False, error=str(e))

        if result.get("reverted"):
            self.discard_writeback_journal()
            if value_sat > 0:
                self._refund_sat(contract_addr, caller, value_sat)
            return EVMResult(success=False, error="execution_reverted",
                             gas_used=result["gas_used"])

        # Сохраняем изменённое storage + flush nested journal once
        new_storage = {str(k): v for k, v in result.get("storage", {}).items()}
        self.db.update_account_storage(contract_addr, new_storage)
        self._persist_logs(contract_addr, result.get("logs", []))
        self.commit_writeback_journal()

        # Возвращаемое значение — return_data или стек
        ret = result.get("return_data") or b""
        if ret:
            return_value = int.from_bytes(ret[:32].ljust(32, b"\x00"), "big")
        else:
            stack = result.get("stack", [])
            return_value = stack[-1] if stack else None

        return EVMResult(
            success=not result.get("reverted", False),
            return_value=return_value,
            gas_used=result["gas_used"],
            storage_changes=new_storage,
            logs=result.get("logs", []),
        )

    # ── Статический вызов (read-only) ────────────────────────────────────────

    def static_call(self, contract_addr: str,
                    calldata_hex: str = "", gas_limit: int = 0) -> EVMResult:
        """
        Вызывает контракт без изменения состояния (eth_call).
        Storage НЕ сохраняется. Nested CREATE/SELFDESTRUCT are rejected.
        """
        gas_limit = gas_limit or self.config.evm_gas_limit

        # Experimental: Ethereum precompile subset (identity / sha256).
        from execution.evm_precompiles import try_precompile

        pre = try_precompile(contract_addr, calldata_hex)
        if pre is not None:
            return pre

        account = self.db.get_account(contract_addr)
        if not account or not account.get("code"):
            return EVMResult(success=False, error="not_a_contract")

        try:
            bytecode = bytes.fromhex(account["code"].replace("0x", ""))
        except ValueError as e:
            return EVMResult(success=False, error=f"invalid_bytecode: {e}")

        storage = self._loads_contract_storage(account.get("storage") or "{}")
        if storage is None:
            return EVMResult(success=False, error="corrupt_storage")

        try:
            calldata = bytes.fromhex(calldata_hex.replace("0x", "")) if calldata_hex else b""
        except ValueError:
            return EVMResult(success=False, error="invalid_calldata")

        try:
            result = self._run_evm(
                bytecode, storage, gas_limit,
                caller="",
                contract_addr=contract_addr,
                calldata=calldata,
                read_only=True,
            )
        except Exception as e:
            return EVMResult(success=False, error=str(e), gas_used=0)

        ret = result.get("return_data") or b""
        if ret:
            return_value = int.from_bytes(ret[:32].ljust(32, b"\x00"), "big")
        else:
            stack = result.get("stack", [])
            return_value = stack[-1] if stack else None

        return EVMResult(
            success=not result.get("reverted", False),
            return_value=return_value,
            gas_used=result["gas_used"],
        )

    # ── Оценка газа ──────────────────────────────────────────────────────────

    def estimate_gas(self, contract_addr: str, calldata_hex: str = "") -> int:
        """Оценивает количество газа для вызова. Запускает dry-run."""
        result = self.static_call(contract_addr, calldata_hex,
                                  gas_limit=self.config.evm_gas_limit)
        if result.success:
            return int(result.gas_used * 1.2)  # +20% буфер
        return self.config.evm_gas_limit

    # ── Справочная информация ────────────────────────────────────────────────

    def get_contract_info(self, contract_addr: str) -> Dict:
        """Возвращает информацию о смарт-контракте."""
        account = self.db.get_account(contract_addr)
        if not account:
            return {"exists": False}
        return {
            "exists": True,
            "address": contract_addr,
            "is_contract": bool(account.get("code")),
            "balance": account.get("balance", 0.0),
            "code_size": len(account.get("code") or "") // 2,
            "storage_slots": len(json.loads(account.get("storage") or "{}")),
        }
