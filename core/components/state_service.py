# core/components/state_service.py — state mutations / native apply / state_root
"""Extracted from Blockchain apply/state helpers (facade decomposition)."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from crypto import native
from core.components.ports import ApplyBlockResult
from execution.state_root import compute_db_state_root
from runtime.tokenomics import MAX_SUPPLY_ABS

_logger = logging.getLogger("StateService")


class StateService:
    """Owns account mutations, native block apply, and state_root computation.

    Holds a back-reference to the Blockchain facade for storage/config/evm/bus
    wiring that is completed after ``__init__`` (pool_locks, evm, etc.).
    """

    def __init__(self, host: Any):
        self._host = host

    @property
    def config(self):
        return self._host.config

    @property
    def storage(self):
        return self._host.storage

    @property
    def bus(self):
        return self._host.bus

    @property
    def pool_locks(self):
        return getattr(self._host, "pool_locks", None)

    @property
    def evm(self):
        return getattr(self._host, "evm", None)

    def _native_apply_fail_closed(self) -> bool:
        return self._host._native_apply_fail_closed()

    def _verify_tx_signature(self, tx):
        return self._host.tx_pipeline.verify_tx_signature(tx).as_dict()

    def ensure_at_tip(self) -> bool:
        return self._host.ensure_state_at_tip()

    def replay_from_ancestor(self, ancestor_height: int, alloc: Dict[str, Any]) -> float:
        if (
            ancestor_height >= 1
            and native.native_available()
            and hasattr(native, "blockchain_replay_simple_blocks")
            and self._blocks_range_are_simple(1, ancestor_height)
        ):
            return self._replay_simple_range_native(ancestor_height, alloc)
        burned = 0.0
        from core.blockchain import Block

        for h in range(1, int(ancestor_height) + 1):
            block_dict = self.storage.get_block(h)
            if not block_dict:
                raise RuntimeError(f"missing_block_at_replay_{h}")
            block = Block.from_dict(block_dict)
            for tx in block.transactions:
                result = self.apply_transaction(
                    tx, block.height, proposer=block.miner, in_atomic=True
                )
                if not result["success"]:
                    raise RuntimeError(result.get("error", "replay_tx_failed"))
                burned += float(getattr(tx, "burned", 0) or 0)
            self.apply_block_reward(block.miner, in_atomic=True)
        return burned

    def apply_block_mutations(self, block: Any, *, preserve_peer_hash: bool = False) -> ApplyBlockResult:
        """Apply txs + reward; caller owns atomic + UoW tip fence.

        Transaction-class gates and state_root go through the Blockchain host so
        tests / adapters can monkeypatch ``bc._block_transactions_are_*`` and
        ``bc._compute_state_root_from_db``.
        """
        block_burned_sat = 0
        native_applied = False
        host = self._host
        if (
            native.native_available()
            and hasattr(native, "blockchain_apply_simple_block")
            and host._block_transactions_are_simple(block.transactions)
        ):
            try:
                block_burned_sat = self._apply_simple_block_native(block)
                native_applied = True
            except Exception as native_exc:
                if self._native_apply_fail_closed():
                    raise
                _logger.debug(
                    "[StateService] native simple apply fallback #%s: %s",
                    block.height,
                    native_exc,
                )
        if (
            not native_applied
            and native.native_available()
            and hasattr(native, "blockchain_apply_host_effects")
            and host._block_transactions_are_all_evm(block.transactions)
        ):
            try:
                block_burned_sat = self._apply_evm_host_block_native(block)
                native_applied = True
            except Exception as native_exc:
                if self._native_apply_fail_closed():
                    raise
                _logger.debug(
                    "[StateService] native host-effects apply fallback #%s: %s",
                    block.height,
                    native_exc,
                )
        if (
            not native_applied
            and native.native_available()
            and hasattr(native, "blockchain_apply_host_effects")
            and host._block_transactions_are_mixed(block.transactions)
        ):
            try:
                block_burned_sat = self._apply_mixed_block_native(block)
                native_applied = True
            except Exception as native_exc:
                if self._native_apply_fail_closed():
                    raise
                _logger.debug(
                    "[StateService] native mixed apply fallback #%s: %s",
                    block.height,
                    native_exc,
                )
        if not native_applied:
            for tx in block.transactions:
                result = self.apply_transaction(
                    tx, block.height, proposer=block.miner, in_atomic=True
                )
                if not result["success"]:
                    raise RuntimeError(result.get("error", "tx_failed"))
                block_burned_sat += int(result.get("burned_sat", 0) or 0)
            self.apply_block_reward(block.miner, in_atomic=True)
        root = host._compute_state_root_from_db()
        return ApplyBlockResult(
            success=True,
            burned=int(block_burned_sat),
            state_root=root,
            native_applied=native_applied,
        )

    @staticmethod
    def _tx_is_simple(tx) -> bool:
        data = (getattr(tx, "data", None) or "").strip()
        if not data or data in ("0x", "0X"):
            return True
        return False


    def _block_transactions_are_simple(self, transactions) -> bool:
        return all(self._tx_is_simple(tx) for tx in transactions)


    def _block_transactions_are_all_evm(self, transactions) -> bool:
        if not transactions:
            return False
        if not getattr(self, "evm", None):
            return False
        return all(not self._tx_is_simple(tx) for tx in transactions)


    def _block_transactions_are_mixed(self, transactions) -> bool:
        """True when block has both simple transfers and EVM calldata txs."""
        if not transactions:
            return False
        if not getattr(self, "evm", None):
            return False
        has_simple = False
        has_evm = False
        for tx in transactions:
            if self._tx_is_simple(tx):
                has_simple = True
            else:
                has_evm = True
            if has_simple and has_evm:
                return True
        return False


    def _collect_addrs_for_simple_block(self, block: "Block") -> set:
        addrs = set()
        proposer = block.miner or ""
        if proposer:
            addrs.add(proposer)
        burn = getattr(self.config, "burn_address", "") or ""
        if burn:
            addrs.add(burn)
        for tx in block.transactions:
            if getattr(tx, "from_addr", None):
                addrs.add(tx.from_addr)
            if getattr(tx, "to_addr", None):
                addrs.add(tx.to_addr)
        return addrs


    def _accounts_sat_snapshot(self, addresses) -> Dict[str, Dict[str, int]]:
        out: Dict[str, Dict[str, int]] = {}
        for addr in addresses:
            if not addr:
                continue
            out[addr] = {
                "balance": int(self.storage.get_balance_satoshi(addr)),
                "nonce": int(self.storage.get_nonce(addr)),
            }
        return out


    def _writeback_accounts_sat(self, accounts: Dict[str, Any]) -> None:
        from runtime.amount import from_satoshi_float

        for addr, row in accounts.items():
            sat = int(row.get("balance", 0) or 0)
            nonce = int(row.get("nonce", 0) or 0)
            bal_abs = from_satoshi_float(sat)
            existing = None
            if hasattr(self.storage, "get_account"):
                existing = self.storage.get_account(addr)
            # Match Python apply: do not materialize empty burn/dust accounts,
            # and never wipe EVM code/storage when rewriting balances.
            if existing is None and sat == 0 and nonce == 0:
                continue
            code = existing.get("code") if existing else None
            storage = existing.get("storage") if existing else None
            if hasattr(self.storage, "save_account"):
                self.storage.save_account(
                    addr, balance=bal_abs, nonce=nonce, code=code, storage=storage
                )
            else:
                self.storage.set_balance(addr, bal_abs)
                while self.storage.get_nonce(addr) < nonce:
                    if hasattr(self.storage, "nonce_increment"):
                        self.storage.nonce_increment(addr)
                    else:
                        self.storage.increment_nonce(addr)


    def _apply_simple_block_native(self, block: "Block") -> int:
        """Apply simple transfers via abs_native; returns burned satoshi."""
        from runtime.amount import from_satoshi_float, plan_transfer_fees_sat, to_satoshi

        addrs = self._collect_addrs_for_simple_block(block)
        snap = self._accounts_sat_snapshot(addrs)
        txs = []
        for tx in block.transactions:
            txs.append(
                {
                    "from": tx.from_addr,
                    "to": tx.to_addr,
                    "value": float(tx.value),
                    "gas": int(tx.gas or 21000),
                    "nonce": int(tx.nonce),
                    "data": getattr(tx, "data", "") or "",
                }
            )
        supply_sat = 0
        if hasattr(self.storage, "get_total_supply"):
            supply_sat = int(to_satoshi(self.storage.get_total_supply()))
        else:
            supply_sat = sum(int(v["balance"]) for v in snap.values())
        max_supply_sat = int(to_satoshi(float(getattr(self.config, "max_supply", MAX_SUPPLY_ABS))))
        raw = native.blockchain_apply_simple_block(
            json.dumps(snap, separators=(",", ":"), ensure_ascii=False),
            json.dumps(txs, separators=(",", ":"), ensure_ascii=False),
            float(self.config.gas_price_wei),
            float(self.config.burn_rate),
            str(block.miner or ""),
            str(getattr(self.config, "burn_address", "") or ""),
            float(self.config.block_reward),
            supply_sat,
            max_supply_sat,
        )
        result = json.loads(raw)
        accounts = result.get("accounts") or {}
        self._writeback_accounts_sat(accounts)
        burned_sat = int(result.get("total_burned_sat", 0) or 0)
        # Mirror fee/burn display fields onto tx objects for persistence/wire.
        for tx in block.transactions:
            plan = plan_transfer_fees_sat(
                tx.gas,
                self.config.gas_price_wei,
                self.config.burn_rate,
                tx.value,
            )
            tx.fee = from_satoshi_float(plan["fee_sat"])
            tx.burned = from_satoshi_float(plan["burned_sat"])
            tx.gas_used = tx.gas
            tx.block_height = block.height
            tx.status = 1
        return burned_sat


    def _run_evm_host_only(self, tx: "Transaction", block_height: int) -> Dict:
        """Execute EVM call/deploy (storage/code/value) without fee/nonce writes."""
        from execution.evm_precompiles import is_evm_call_target

        if not getattr(self, "evm", None):
            return {"success": False, "error": "evm_unavailable"}
        target_acct = self.storage.get_account(tx.to_addr) if tx.to_addr else None
        if is_evm_call_target(
            tx.to_addr or "", (target_acct or {}).get("code") if target_acct else None
        ):
            evm_res = self.evm.call_contract(
                tx.from_addr,
                tx.to_addr,
                tx.data,
                tx.value,
                gas_limit=tx.gas or self.config.evm_gas_limit,
            )
            if not evm_res.success:
                return {"success": False, "error": evm_res.error or "evm_call_failed"}
            return {
                "success": True,
                "gas_used": int(evm_res.gas_used or tx.gas or 0),
                "contract_address": None,
            }
        deploy_data = (tx.data or "").strip()
        hex_body = deploy_data.replace("0x", "")
        if deploy_data and len(hex_body) >= 4 and len(hex_body) % 2 == 0:
            deploy_salt = f"{block_height}:{tx.nonce}:{tx.hash}"
            evm_res = self.evm.deploy_contract(
                tx.from_addr,
                deploy_data,
                tx.value,
                gas_limit=tx.gas or self.config.evm_gas_limit,
                salt=deploy_salt,
                block_number=block_height,
            )
            if not evm_res.success:
                return {"success": False, "error": evm_res.error or "evm_deploy_failed"}
            return {
                "success": True,
                "gas_used": int(evm_res.gas_used or tx.gas or 0),
                "contract_address": evm_res.return_value,
            }
        return {"success": False, "error": "evm_unsupported_tx"}


    def _apply_evm_host_block_native(self, block: "Block") -> int:
        """Run EVM host per tx, then native fee/nonce/reward apply. Returns burned satoshi."""
        from runtime.amount import from_satoshi_float, plan_transfer_fees_sat, to_satoshi

        effects = []
        addrs = self._collect_addrs_for_simple_block(block)
        for tx in block.transactions:
            host = self._run_evm_host_only(tx, block.height)
            if not host.get("success"):
                raise RuntimeError(host.get("error") or "evm_host_failed")
            gas_used = int(host.get("gas_used") or tx.gas or 0)
            effects.append(
                {
                    "from": tx.from_addr,
                    "to": tx.to_addr or "",
                    "value": float(tx.value or 0),
                    "apply_value": False,
                    "gas": int(tx.gas or 21000),
                    "gas_used": gas_used,
                    "nonce": int(tx.nonce),
                }
            )
            if host.get("contract_address"):
                addrs.add(str(host["contract_address"]))
            plan = plan_transfer_fees_sat(
                tx.gas,
                self.config.gas_price_wei,
                self.config.burn_rate,
                0.0,
                gas_used=gas_used,
            )
            tx.fee = from_satoshi_float(plan["fee_sat"])
            tx.burned = from_satoshi_float(plan["burned_sat"])
            tx.gas_used = gas_used
            tx.block_height = block.height
            tx.status = 1

        snap = self._accounts_sat_snapshot(addrs)
        supply_sat = 0
        if hasattr(self.storage, "get_total_supply"):
            supply_sat = int(to_satoshi(self.storage.get_total_supply()))
        else:
            supply_sat = sum(int(v["balance"]) for v in snap.values())
        max_supply_sat = int(to_satoshi(float(getattr(self.config, "max_supply", MAX_SUPPLY_ABS))))
        raw = native.blockchain_apply_host_effects(
            json.dumps(snap, separators=(",", ":"), ensure_ascii=False),
            json.dumps(effects, separators=(",", ":"), ensure_ascii=False),
            float(self.config.gas_price_wei),
            float(self.config.burn_rate),
            str(block.miner or ""),
            str(getattr(self.config, "burn_address", "") or ""),
            float(self.config.block_reward),
            supply_sat,
            max_supply_sat,
        )
        result = json.loads(raw)
        self._writeback_accounts_sat(result.get("accounts") or {})
        return int(result.get("total_burned_sat", 0) or 0)


    def _apply_mixed_block_native(self, block: "Block") -> int:
        """Apply mixed simple+EVM block via host_effects with block-scoped sat session (v1.3.69).

        EVM calldata txs still run the Python host first (code/storage on DB).
        Fee/nonce/value sat rows stay in an in-memory session and write back once
        at the end (plus final reward). Avoids per-tx full-account DB rewrite and
        repeated get_total_supply scans.
        """
        from runtime.amount import from_satoshi_float, plan_transfer_fees_sat, to_satoshi

        if not getattr(self, "evm", None):
            raise RuntimeError("evm_unavailable")

        total_burned_sat = 0
        miner = str(block.miner or "")
        burn_addr = str(getattr(self.config, "burn_address", "") or "")
        max_supply_sat = int(to_satoshi(float(getattr(self.config, "max_supply", MAX_SUPPLY_ABS))))

        # Prefetch all addresses touched by the block (block-scoped session).
        session_addrs = {miner, burn_addr}
        session_addrs.discard("")
        for tx in block.transactions:
            if tx.from_addr:
                session_addrs.add(tx.from_addr)
            if tx.to_addr:
                session_addrs.add(tx.to_addr)
        session = self._accounts_sat_snapshot(session_addrs)
        if hasattr(self.storage, "get_total_supply"):
            supply_sat = int(to_satoshi(self.storage.get_total_supply()))
        else:
            supply_sat = sum(int(v["balance"]) for v in session.values())

        for tx in block.transactions:
            addrs = {miner, burn_addr, tx.from_addr or "", tx.to_addr or ""}
            addrs.discard("")
            if self._tx_is_simple(tx):
                gas_used = int(tx.gas or 21000)
                effect = {
                    "from": tx.from_addr,
                    "to": tx.to_addr or "",
                    "value": float(tx.value or 0),
                    "apply_value": True,
                    "gas": int(tx.gas or 21000),
                    "gas_used": gas_used,
                    "nonce": int(tx.nonce),
                }
                plan = plan_transfer_fees_sat(
                    tx.gas,
                    self.config.gas_price_wei,
                    self.config.burn_rate,
                    tx.value,
                )
            else:
                host = self._run_evm_host_only(tx, block.height)
                if not host.get("success"):
                    raise RuntimeError(host.get("error") or "evm_host_failed")
                gas_used = int(host.get("gas_used") or tx.gas or 0)
                if host.get("contract_address"):
                    caddr = str(host["contract_address"])
                    addrs.add(caddr)
                    session_addrs.add(caddr)
                # EVM host may have mutated DB balances/code — refresh session rows.
                refreshed = self._accounts_sat_snapshot(addrs)
                session.update(refreshed)
                effect = {
                    "from": tx.from_addr,
                    "to": tx.to_addr or "",
                    "value": float(tx.value or 0),
                    "apply_value": False,
                    "gas": int(tx.gas or 21000),
                    "gas_used": gas_used,
                    "nonce": int(tx.nonce),
                }
                plan = plan_transfer_fees_sat(
                    tx.gas,
                    self.config.gas_price_wei,
                    self.config.burn_rate,
                    0.0,
                    gas_used=gas_used,
                )

            # Ensure effect addresses exist in session.
            for a in addrs:
                if a not in session:
                    session.update(self._accounts_sat_snapshot([a]))

            snap = {a: dict(session[a]) for a in addrs if a in session}
            raw = native.blockchain_apply_host_effects(
                json.dumps(snap, separators=(",", ":"), ensure_ascii=False),
                json.dumps([effect], separators=(",", ":"), ensure_ascii=False),
                float(self.config.gas_price_wei),
                float(self.config.burn_rate),
                miner,
                burn_addr,
                0.0,
                supply_sat,
                max_supply_sat,
            )
            result = json.loads(raw)
            for addr, row in dict(result.get("accounts") or {}).items():
                session[addr] = {
                    "balance": int(row.get("balance", 0) or 0),
                    "nonce": int(row.get("nonce", 0) or 0),
                }
            burned = int(result.get("total_burned_sat", 0) or 0)
            total_burned_sat += burned
            supply_sat = max(0, supply_sat - burned)
            tx.fee = from_satoshi_float(plan["fee_sat"])
            tx.burned = from_satoshi_float(plan["burned_sat"])
            tx.gas_used = gas_used
            tx.block_height = block.height
            tx.status = 1

        # Final block reward against session, then one writeback.
        reward_addrs = {miner}
        reward_addrs.discard("")
        for a in reward_addrs:
            if a not in session:
                session.update(self._accounts_sat_snapshot([a]))
        snap = {a: dict(session[a]) for a in reward_addrs if a in session}
        raw = native.blockchain_apply_host_effects(
            json.dumps(snap, separators=(",", ":"), ensure_ascii=False),
            "[]",
            float(self.config.gas_price_wei),
            float(self.config.burn_rate),
            miner,
            burn_addr,
            float(self.config.block_reward),
            supply_sat,
            max_supply_sat,
        )
        for addr, row in dict(json.loads(raw).get("accounts") or {}).items():
            session[addr] = {
                "balance": int(row.get("balance", 0) or 0),
                "nonce": int(row.get("nonce", 0) or 0),
            }
        self._writeback_accounts_sat(session)
        return int(total_burned_sat)


    def _blocks_range_are_simple(self, from_h: int, to_h: int) -> bool:
        for h in range(from_h, to_h + 1):
            block_dict = self.storage.get_block(h)
            if not block_dict:
                return False
            for tx in block_dict.get("transactions") or []:
                data = str(tx.get("data") or tx.get("input") or "").strip()
                if data and data not in ("0x", "0X"):
                    return False
        return True


    def _replay_simple_range_native(self, ancestor_height: int, alloc: Dict[str, Any]) -> float:
        """Native reorg/tip replay for simple-transfer chains. Returns total burned ABS."""
        from runtime.amount import from_satoshi_float, to_satoshi

        accounts = {
            str(addr): {"balance": int(to_satoshi(amt)), "nonce": 0}
            for addr, amt in (alloc or {}).items()
        }
        supply_sat = sum(int(v["balance"]) for v in accounts.values())
        max_supply_sat = int(to_satoshi(float(getattr(self.config, "max_supply", MAX_SUPPLY_ABS))))
        blocks = []
        for h in range(1, ancestor_height + 1):
            block_dict = self.storage.get_block(h)
            if not block_dict:
                raise RuntimeError(f"missing_block_at_replay_{h}")
            blocks.append(
                {
                    "miner": block_dict.get("miner") or block_dict.get("proposer") or "",
                    "transactions": block_dict.get("transactions") or [],
                }
            )
        raw = native.blockchain_replay_simple_blocks(
            json.dumps(accounts, separators=(",", ":"), ensure_ascii=False),
            json.dumps(blocks, separators=(",", ":"), ensure_ascii=False),
            float(self.config.gas_price_wei),
            float(self.config.burn_rate),
            str(getattr(self.config, "burn_address", "") or ""),
            float(self.config.block_reward),
            supply_sat,
            max_supply_sat,
        )
        result = json.loads(raw)
        self._writeback_accounts_sat(result.get("accounts") or {})
        return float(from_satoshi_float(int(result.get("total_burned_sat", 0) or 0)))


    def _credit_sat(self, address: str, delta_sat: int, *, in_atomic: bool) -> None:
        """Apply integer satoshi delta via storage (Wave C)."""
        if not delta_sat:
            return
        if hasattr(self.storage, "balance_delta_satoshi"):
            if in_atomic:
                self.storage.balance_delta_satoshi(address, int(delta_sat))
            else:
                # Non-atomic path: satoshi delta then commit via update_balance(0) if needed.
                self.storage.balance_delta_satoshi(address, int(delta_sat))
                if hasattr(self.storage, "conn") and hasattr(self.storage, "lock"):
                    with self.storage.lock:
                        self.storage.conn.commit()
            return
        from runtime.amount import from_satoshi_float

        abs_delta = from_satoshi_float(int(delta_sat))
        if in_atomic:
            self.storage.balance_delta(address, abs_delta)
        else:
            self.storage.update_balance(address, abs_delta)

    def apply_transaction(
        self, tx: Transaction, block_height: int, proposer: str = None, in_atomic: bool = False
    ) -> Dict:
        """
        Apply one transaction using integer satoshi fee/value math (Wave C).
        Display fields on tx (fee/burned) remain ABS floats for wire/UI only.
        """
        proposer = proposer or self.config.miner_address or "genesis"
        from runtime.amount import (
            can_afford_transfer_sat,
            from_satoshi_float,
            plan_transfer_fees_sat,
            to_satoshi,
        )

        plan = plan_transfer_fees_sat(
            tx.gas,
            self.config.gas_price_wei,
            self.config.burn_rate,
            tx.value,
        )
        fee_sat = plan["fee_sat"]
        burn_sat = plan["burned_sat"]
        miner_fee_sat = plan["miner_fee_sat"]
        value_sat = plan["value_sat"]
        total_cost_sat = plan["total_cost_sat"]
        fee = from_satoshi_float(fee_sat)
        burn_amount = from_satoshi_float(burn_sat)
        miner_fee = from_satoshi_float(miner_fee_sat)
        total_cost = from_satoshi_float(total_cost_sat)

        expected_nonce = self.storage.get_nonce(tx.from_addr)
        if tx.nonce != expected_nonce:
            return {"success": False, "error": "nonce_mismatch"}

        sender_sat = self.storage.get_balance_satoshi(tx.from_addr)
        if not can_afford_transfer_sat(sender_sat, total_cost_sat):
            return {"success": False, "error": "insufficient_funds"}
        sender_balance = from_satoshi_float(sender_sat)

        if self.pool_locks:
            allowed, reason = self.pool_locks.is_outgoing_allowed(
                tx.from_addr, total_cost, sender_balance
            )
            if not allowed:
                return {"success": False, "error": reason}

        sig_check = self._verify_tx_signature(tx)
        if not sig_check.get("valid"):
            return {"success": False, "error": sig_check.get("error", "invalid_signature")}

        # EVM: contract call or deploy when calldata present
        if tx.data and getattr(self, "evm", None):
            from execution.evm_precompiles import is_evm_call_target

            target_acct = self.storage.get_account(tx.to_addr)
            if is_evm_call_target(
                tx.to_addr or "",
                (target_acct or {}).get("code") if target_acct else None,
            ):
                evm_res = self.evm.call_contract(
                    tx.from_addr,
                    tx.to_addr,
                    tx.data,
                    tx.value,
                    gas_limit=tx.gas or self.config.evm_gas_limit,
                )
                if not evm_res.success:
                    return {"success": False, "error": evm_res.error or "evm_call_failed"}
                plan = plan_transfer_fees_sat(
                    tx.gas,
                    self.config.gas_price_wei,
                    self.config.burn_rate,
                    tx.value,
                    gas_used=evm_res.gas_used,
                )
                fee_sat = plan["fee_sat"]
                burn_sat = plan["burned_sat"]
                miner_fee_sat = plan["miner_fee_sat"]
                total_cost_sat = plan["total_cost_sat"]
                fee = from_satoshi_float(fee_sat)
                burn_amount = from_satoshi_float(burn_sat)
                miner_fee = from_satoshi_float(miner_fee_sat)
                if not can_afford_transfer_sat(sender_sat, total_cost_sat):
                    return {"success": False, "error": "insufficient_funds"}
                self._credit_sat(tx.from_addr, -fee_sat, in_atomic=in_atomic)
                self._credit_sat(proposer, miner_fee_sat, in_atomic=in_atomic)
                if burn_sat > 0 and self.config.burn_address:
                    self._credit_sat(self.config.burn_address, burn_sat, in_atomic=in_atomic)
                if in_atomic:
                    self.storage.nonce_increment(tx.from_addr)
                else:
                    self.storage.increment_nonce(tx.from_addr)
                if self.pool_locks:
                    self.pool_locks.record_outgoing(tx.from_addr, fee + tx.value)
                tx.fee = fee
                tx.burned = burn_amount
                tx.gas_used = evm_res.gas_used or tx.gas
                tx.block_height = block_height
                tx.status = 1
                if self.bus:
                    self.bus.emit("tx.applied", tx.to_dict())
                return {
                    "success": True,
                    "fee": fee,
                    "burned": burn_amount,
                    "miner_fee": miner_fee,
                    "fee_sat": fee_sat,
                    "burned_sat": burn_sat,
                    "evm": True,
                }

            deploy_data = (tx.data or "").strip()
            hex_body = deploy_data.replace("0x", "")
            if deploy_data and len(hex_body) >= 4 and len(hex_body) % 2 == 0:
                deploy_salt = f"{block_height}:{tx.nonce}:{tx.hash}"
                evm_res = self.evm.deploy_contract(
                    tx.from_addr,
                    deploy_data,
                    tx.value,
                    gas_limit=tx.gas or self.config.evm_gas_limit,
                    salt=deploy_salt,
                    block_number=block_height,
                )
                if not evm_res.success:
                    return {"success": False, "error": evm_res.error or "evm_deploy_failed"}
                plan = plan_transfer_fees_sat(
                    tx.gas,
                    self.config.gas_price_wei,
                    self.config.burn_rate,
                    tx.value,
                    gas_used=evm_res.gas_used,
                )
                fee_sat = plan["fee_sat"]
                burn_sat = plan["burned_sat"]
                miner_fee_sat = plan["miner_fee_sat"]
                deploy_cost_sat = plan["total_cost_sat"]
                fee = from_satoshi_float(fee_sat)
                burn_amount = from_satoshi_float(burn_sat)
                miner_fee = from_satoshi_float(miner_fee_sat)
                deploy_cost = from_satoshi_float(deploy_cost_sat)
                if sender_sat < deploy_cost_sat:
                    return {"success": False, "error": "insufficient_funds_for_deploy"}
                self._credit_sat(tx.from_addr, -fee_sat, in_atomic=in_atomic)
                self._credit_sat(proposer, miner_fee_sat, in_atomic=in_atomic)
                if burn_sat > 0 and self.config.burn_address:
                    self._credit_sat(self.config.burn_address, burn_sat, in_atomic=in_atomic)
                if in_atomic:
                    self.storage.nonce_increment(tx.from_addr)
                else:
                    self.storage.increment_nonce(tx.from_addr)
                if self.pool_locks:
                    self.pool_locks.record_outgoing(tx.from_addr, deploy_cost)
                tx.fee = fee
                tx.burned = burn_amount
                tx.gas_used = evm_res.gas_used or tx.gas
                tx.block_height = block_height
                tx.status = 1
                if self.bus:
                    self.bus.emit("tx.applied", tx.to_dict())
                return {
                    "success": True,
                    "fee": fee,
                    "burned": burn_amount,
                    "miner_fee": miner_fee,
                    "fee_sat": fee_sat,
                    "burned_sat": burn_sat,
                    "evm": True,
                    "contract_address": evm_res.return_value,
                }

        self._credit_sat(tx.from_addr, -total_cost_sat, in_atomic=in_atomic)
        self._credit_sat(tx.to_addr, value_sat, in_atomic=in_atomic)
        self._credit_sat(proposer, miner_fee_sat, in_atomic=in_atomic)
        if burn_sat > 0 and self.config.burn_address:
            self._credit_sat(self.config.burn_address, burn_sat, in_atomic=in_atomic)
        if in_atomic:
            self.storage.nonce_increment(tx.from_addr)
        else:
            self.storage.increment_nonce(tx.from_addr)

        if self.pool_locks:
            self.pool_locks.record_outgoing(tx.from_addr, total_cost)

        tx.fee = fee
        tx.burned = burn_amount
        tx.gas_used = tx.gas
        tx.block_height = block_height
        tx.status = 1

        if self.bus:
            self.bus.emit("tx.applied", tx.to_dict())

        return {
            "success": True,
            "fee": fee,
            "burned": burn_amount,
            "miner_fee": miner_fee,
            "fee_sat": fee_sat,
            "burned_sat": burn_sat,
            "value_sat": value_sat,
        }


    def apply_block_reward(self, proposer: str, in_atomic: bool = False) -> float:
        from runtime.amount import from_satoshi_float, to_satoshi

        current_supply_sat = 0
        if hasattr(self.storage, "get_total_supply_satoshi"):
            current_supply_sat = int(self.storage.get_total_supply_satoshi())
        else:
            current_supply_sat = to_satoshi(self.storage.get_total_supply())
        max_supply_sat = to_satoshi(getattr(self.config, "max_supply", MAX_SUPPLY_ABS))
        reward_sat = to_satoshi(self.config.block_reward)
        if current_supply_sat + reward_sat > max_supply_sat:
            reward_sat = max(0, max_supply_sat - current_supply_sat)
        if reward_sat > 0:
            self._credit_sat(proposer, reward_sat, in_atomic=in_atomic)
        return from_satoshi_float(reward_sat)


    def compute_state_root(self) -> str:
        if hasattr(self.storage, "compute_state_root"):
            return self.storage.compute_state_root()
        return compute_db_state_root(self.storage.get_all_accounts())

