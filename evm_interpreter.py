#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EVM interpreter — bytecode execution with real execution context."""

import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any

from crypto import native
from execution.evm_host_bridge import make_evm_runtime_bridge


def _native_crypto_required() -> bool:
    return os.getenv("ABS_REQUIRE_NATIVE_CRYPTO", "").lower() in {
        "1", "true", "yes", "on",
    }


@dataclass
class EVMContext:
    """Runtime environment for contract execution."""
    caller: str = ""
    origin: str = ""
    address: str = ""
    calldata: bytes = b""
    value: int = 0
    block_number: int = 0
    timestamp: int = 0
    chain_id: int = 77777
    base_fee: int = 0
    gas_price: int = 0
    difficulty: int = 0
    coinbase: str = ""
    blob_base_fee: int = 0
    blob_hashes: Optional[List[int]] = None
    balance_of: Optional[Callable[[str], int]] = None
    code_size_of: Optional[Callable[[str], int]] = None
    code_copy_of: Optional[Callable[[str, int, int], bytes]] = None
    block_hash_of: Optional[Callable[[int], int]] = None
    emit_log: Optional[Callable[[int, List[int], bytes], None]] = None
    selfdestruct: Optional[Callable[[str], None]] = None
    contract_call: Optional[Callable[..., Dict[str, Any]]] = None
    contract_create: Optional[Callable[..., Dict[str, Any]]] = None

    def addr_int(self, who: str) -> int:
        raw = (who or "").replace("0x", "").lower()
        if not raw:
            return 0
        try:
            return int(raw[:40], 16)
        except ValueError:
            return int(native.sha256_hex(who.encode())[:16], 16)


class EVM:
    """Stack-machine EVM with storage, memory, calldata and environment opcodes."""

    CALL_STIPEND = 2300

    GAS_COSTS = {
        "STOP": 0, "ADD": 3, "MUL": 5, "SUB": 3, "DIV": 5, "MOD": 5,
        "SDIV": 5, "SMOD": 5, "ADDMOD": 8, "MULMOD": 8, "EXP": 10, "SIGNEXTEND": 5,
        "POP": 2, "MLOAD": 3, "MSTORE": 3, "MSTORE8": 3,
        "SLOAD": 200, "SSTORE": 5000, "JUMP": 8, "JUMPI": 10,
        "BALANCE": 400, "CALLER": 2, "ORIGIN": 2, "ADDRESS": 2,
        "TIMESTAMP": 2, "NUMBER": 2, "CALLVALUE": 2,
        "CALLDATALOAD": 3, "CALLDATASIZE": 2, "RETURNDATASIZE": 2, "RETURNDATACOPY": 3,
        "CODESIZE": 2, "CODECOPY": 3, "CHAINID": 2, "GASLIMIT": 2, "GAS": 2, "PUSH0": 2,
        "SHA3": 30, "RETURN": 0, "REVERT": 0, "JUMPDEST": 1,
        "AND": 3, "OR": 3, "XOR": 3, "NOT": 3, "LT": 3, "GT": 3,
        "EQ": 3, "ISZERO": 3, "BYTE": 3, "SHL": 3, "SHR": 3, "SLT": 3, "SGT": 3, "SAR": 3,
        "GASPRICE": 2, "EXTCODEHASH": 700, "COINBASE": 2, "DIFFICULTY": 2,
        "SELFBALANCE": 5, "BASEFEE": 2, "PC": 2, "MSIZE": 2,
        "TLOAD": 100, "TSTORE": 100, "MCOPY": 3,
        "BLOBHASH": 3, "BLOBBASEFEE": 2,
        "CALL": 700, "CALLCODE": 700, "DELEGATECALL": 700, "STATICCALL": 700,
        "BLOCKHASH": 20,
        "CREATE": 32000, "CREATE2": 32000,
        "EXTCODESIZE": 700, "EXTCODECOPY": 700,
        "LOG": 375, "SELFDESTRUCT": 5000,
    }

    def __init__(self, gas_limit: int = 1_000_000, context: Optional[EVMContext] = None):
        self.stack: List[int] = []
        self.memory = bytearray()
        self.storage: Dict[int, int] = {}
        self.transient_storage: Dict[int, int] = {}
        self.gas_used = 0
        self.gas_limit = gas_limit
        self.pc = 0
        self.running = True
        self.reverted = False
        self.return_data = b""
        self.trace: List[Dict] = []
        self.ctx = context or EVMContext()
        self.bytecode = b""
        self.logs: List[Dict[str, Any]] = []

    def _consume_gas(self, op: str, extra: int = 0):
        cost = self.GAS_COSTS.get(op, 3) + extra
        if self.gas_used + cost > self.gas_limit:
            raise RuntimeError(f"out_of_gas (used={self.gas_used}, need={cost})")
        self.gas_used += cost

    def _push(self, value: int):
        self.stack.append(value & ((1 << 256) - 1))

    def _pop(self) -> int:
        if not self.stack:
            raise RuntimeError("stack underflow")
        return self.stack.pop()

    def _mem_extend(self, offset: int, size: int):
        need = offset + size
        if need > len(self.memory):
            self.memory.extend(b"\x00" * (need - len(self.memory)))

    def _read_word(self, offset: int) -> int:
        self._mem_extend(offset, 32)
        return native.evm_memory_read_word(bytes(self.memory), offset)

    def _write_word(self, offset: int, value: int):
        self._mem_extend(offset, 32)
        native.evm_memory_write_word(self.memory, offset, value)

    def _read_push(self, bytecode: bytes, n: int) -> int:
        return native.evm_read_push(bytecode, self.pc, n)

    def _is_jumpdest(self, bytecode: bytes, dest: int, table: bytes) -> bool:
        return native.evm_is_jumpdest(table, dest, len(bytecode))

    @staticmethod
    def _word_to_addr(word: int) -> str:
        return native.evm_word_to_address(word)

    def _write_return_to_memory(self, ret_offset: int, ret_size: int, data: bytes) -> None:
        self._mem_extend(ret_offset, ret_size)
        native.evm_memory_copy(self.memory, ret_offset, data, 0, ret_size)

    def _available_gas(self, requested: int) -> int:
        remaining = max(0, self.gas_limit - self.gas_used)
        if requested <= 0 or requested > remaining:
            return remaining
        return requested

    def _call_gas_cap(self, requested: int) -> int:
        """EIP-150: at most 63/64 of remaining gas may be forwarded."""
        remaining = max(0, self.gas_limit - self.gas_used)
        return native.evm_call_gas_cap(remaining, requested)

    def _charge_subcall_gas(self, sub_gas: int) -> None:
        if sub_gas > 0:
            self.gas_used += sub_gas
            if self.gas_used > self.gas_limit:
                raise RuntimeError(
                    f"out_of_gas (used={self.gas_used}, limit={self.gas_limit})"
                )

    def _execute_call(self, to_word: int, value: int, args_offset: int, args_size: int,
                      ret_offset: int, ret_size: int, gas: int,
                      delegate: bool, static: bool, callcode: bool = False) -> int:
        sticky_static = bool(static) or self._in_static_context()
        if self._in_static_context() and int(value or 0) != 0:
            self.return_data = b""
            self.reverted = True
            self.running = False
            return 0
        if not self.ctx.contract_call:
            self.return_data = b""
            return 0
        self._mem_extend(args_offset, args_size)
        call_data = native.evm_memory_slice(bytes(self.memory), args_offset, args_size)
        to_addr = self._word_to_addr(to_word)
        kind = (
            "staticcall"
            if sticky_static
            else "delegatecall"
            if delegate
            else "callcode"
            if callcode
            else "call"
        )
        remaining = max(0, self.gas_limit - self.gas_used)
        gas_plan = native.evm_plan_nested_call_gas(remaining, gas, value, kind)
        call_gas = int(gas_plan.get("call_gas", 0) or 0)
        if callcode:
            out = self.ctx.contract_call(
                to_addr, call_data, value, call_gas, delegate, sticky_static, callcode
            )
        else:
            out = self.ctx.contract_call(
                to_addr, call_data, value, call_gas, delegate, sticky_static
            )
        sub_gas = min(int(out.get("gas_used", 0) or 0), call_gas)
        self._charge_subcall_gas(sub_gas)
        self.return_data = out.get("return_data", b"") or b""
        if (
            (delegate or callcode)
            and isinstance(out.get("storage"), dict)
            and not self._in_static_context()
        ):
            self.storage = dict(out["storage"])
        self._write_return_to_memory(ret_offset, ret_size, self.return_data)
        return 1 if out.get("success") and not out.get("reverted") else 0

    def _in_static_context(self) -> bool:
        return bool(getattr(self.ctx, "_abs_read_only", False))

    def _revert_static_write(self) -> bool:
        """EIP-214: SSTORE/LOG/CREATE/SELFDESTRUCT in static context revert this frame."""
        if not self._in_static_context():
            return False
        self.reverted = True
        self.running = False
        return True

    def _execute_create(self, value: int, offset: int, size: int,
                      salt: Optional[int] = None) -> int:
        if not self.ctx.contract_create:
            return 0
        self._mem_extend(offset, size)
        init_code = native.evm_memory_slice(bytes(self.memory), offset, size)
        out = self.ctx.contract_create(init_code, value, self.ctx, salt)
        sub_gas = int(out.get("gas_used", 0) or 0)
        self._charge_subcall_gas(sub_gas)
        if not out.get("success") or out.get("reverted"):
            return 0
        addr = out.get("address") or ""
        return self.ctx.addr_int(addr) if addr else 0

    def _native_pure_available(self) -> bool:
        return hasattr(native, "evm_run_pure_until_host") and hasattr(native, "evm_opcode_is_host")

    def _apply_native_segment(self, seg: Dict[str, Any]) -> str:
        self.pc = int(seg["pc"])
        self.gas_used = int(seg["gas_used"])
        self.running = bool(seg["running"])
        self.reverted = bool(seg["reverted"])
        self.return_data = bytes(seg["return_data"])
        self.stack = [int(x) for x in seg["stack"]]
        self.memory = bytearray(seg["memory"])
        # v1.3.57: LOG body collected in Rust — merge into interpreter logs.
        for entry in list(seg.get("logs") or []):
            self.logs.append({
                "topics": list(entry.get("topics") or []),
                "data": str(entry.get("data") or ""),
            })
        return str(seg["stop_reason"])

    def _handle_native_segment(self, seg: Dict[str, Any]) -> str:
        reason = self._apply_native_segment(seg)
        if reason == "error":
            err = seg.get("error") or "evm error"
            if err == "invalid_jump" or "invalid_jump" in str(err):
                raise RuntimeError(f"invalid jump destination: {self.pc}")
            raise RuntimeError(str(err))
        if reason == "out_of_gas":
            raise RuntimeError(f"out_of_gas (used={self.gas_used}, limit={self.gas_limit})")
        return reason

    def _run_native_until_halt(self, bytecode: bytes, jumpdest_table: bytes) -> Optional[str]:
        if not hasattr(native, "evm_run_until_halt"):
            return None
        bridge = make_evm_runtime_bridge(self)
        if bridge is None:
            return None
        seg = native.evm_run_until_halt(
            bytecode,
            self.pc,
            self.gas_limit,
            self.gas_used,
            self.stack,
            self.memory,
            jumpdest_table,
            self.ctx.calldata,
            self.return_data,
            native.evm_host_context_from_evm(self.ctx),
            self.storage,
            bridge,
        )
        return self._handle_native_segment(seg)

    def _try_native_pure_segment(self, bytecode: bytes, jumpdest_table: bytes) -> Optional[str]:
        if not self._native_pure_available():
            return None
        if native.evm_opcode_is_host(bytecode[self.pc]):
            return None
        seg = native.evm_run_pure_until_host(
            bytecode,
            self.pc,
            self.gas_limit,
            self.gas_used,
            self.stack,
            self.memory,
            jumpdest_table,
            self.ctx.calldata,
            self.return_data,
            native.evm_host_context_from_evm(self.ctx),
            self.storage,
            make_evm_runtime_bridge(self),
        )
        return self._handle_native_segment(seg)

    def _fail_on_native_handoff(self, bytecode: bytes) -> None:
        if not _native_crypto_required():
            return
        op = bytecode[self.pc] if self.pc < len(bytecode) else 0
        raise RuntimeError(
            f"native EVM handoff at pc={self.pc} opcode=0x{op:02x} "
            "(ABS_REQUIRE_NATIVE_CRYPTO forbids Python fallback)"
        )

    def _take_host_storage_snap(self) -> dict:
        if hasattr(native, "evm_host_snapshot_storage"):
            try:
                return native.evm_host_snapshot_storage(self.storage)
            except Exception:
                pass
        return dict(self.storage)

    def _restore_host_storage_snap(self, snap: dict) -> None:
        if hasattr(native, "evm_host_restore_storage"):
            try:
                native.evm_host_restore_storage(self.storage, snap)
                return
            except Exception:
                pass
        self.storage.clear()
        self.storage.update(snap)

    def execute_bytecode(self, bytecode: bytes) -> Dict[str, Any]:
        host_snap = self._take_host_storage_snap()
        try:
            result = self._execute_bytecode_impl(bytecode)
            if result.get("reverted"):
                self._restore_host_storage_snap(host_snap)
                result["storage"] = self.storage.copy()
            return result
        except Exception:
            self._restore_host_storage_snap(host_snap)
            raise

    def _execute_bytecode_impl(self, bytecode: bytes) -> Dict[str, Any]:
        self.pc = 0
        self.stack = []
        self.gas_used = 0
        self.running = True
        self.reverted = False
        self.return_data = b""
        self.trace = []
        self.logs = []
        self.bytecode = bytecode
        jumpdest_table = native.evm_build_jumpdest_table(bytecode)

        native_reason = self._run_native_until_halt(bytecode, jumpdest_table)
        if native_reason is not None and native_reason != "handoff":
            return {
                "success": self.running or (not self.reverted and bool(self.return_data or self.stack)),
                "reverted": self.reverted,
                "stack": self.stack.copy(),
                "memory": bytes(self.memory),
                "storage": self.storage.copy(),
                "gas_used": self.gas_used,
                "return_data": self.return_data,
                "trace": self.trace,
                "logs": self.logs.copy(),
            }

        if native_reason == "handoff":
            self._fail_on_native_handoff(bytecode)

        while self.pc < len(bytecode) and self.running:
            native_reason = self._try_native_pure_segment(bytecode, jumpdest_table)
            if native_reason is not None:
                if native_reason in ("halt", "return", "revert"):
                    break
                if native_reason == "handoff":
                    self._fail_on_native_handoff(bytecode)
                if native_reason not in ("host", "handoff"):
                    continue

            op_byte = bytecode[self.pc]
            op_name = self._opcode_name(op_byte)
            if not (0xA0 <= op_byte <= 0xA4):
                self._consume_gas(op_name)
            self.trace.append({"pc": self.pc, "op": op_name, "stack_depth": len(self.stack)})

            if op_byte == 0x00:  # STOP
                self.running = False
                break

            if 0x60 <= op_byte <= 0x7F:  # PUSH1..PUSH32
                n = op_byte - 0x5F
                self._push(self._read_push(bytecode, n))
                self.pc += n
            elif op_byte == 0x01:
                self._push(native.evm_u256_add(self._pop(), self._pop()))
            elif op_byte == 0x02:
                self._push(native.evm_u256_mul(self._pop(), self._pop()))
            elif op_byte == 0x03:
                a, b = self._pop(), self._pop()
                self._push(native.evm_u256_sub(a, b))
            elif op_byte == 0x04:
                a, b = self._pop(), self._pop()
                self._push(native.evm_u256_div(a, b))
            elif op_byte == 0x05:
                a, b = self._pop(), self._pop()
                self._push(native.evm_u256_sdiv(a, b))
            elif op_byte == 0x06:
                a, b = self._pop(), self._pop()
                self._push(native.evm_u256_mod(a, b))
            elif op_byte == 0x07:
                a, b = self._pop(), self._pop()
                self._push(native.evm_u256_smod(a, b))
            elif op_byte == 0x08:
                mod_, b, a = self._pop(), self._pop(), self._pop()
                self._push(native.evm_u256_addmod(a, b, mod_))
            elif op_byte == 0x09:
                mod_, b, a = self._pop(), self._pop(), self._pop()
                self._push(native.evm_u256_mulmod(a, b, mod_))
            elif op_byte == 0x0A:
                exp, base = self._pop(), self._pop()
                self._push(native.evm_u256_exp(base, exp))
            elif op_byte == 0x0B:
                k, x = self._pop(), self._pop()
                self._push(native.evm_u256_signextend(k, x))
            elif op_byte == 0x10:
                a, b = self._pop(), self._pop()
                self._push(native.evm_u256_and(a, b))
            elif op_byte == 0x11:
                a, b = self._pop(), self._pop()
                self._push(native.evm_u256_or(a, b))
            elif op_byte == 0x12:
                a, b = self._pop(), self._pop()
                self._push(native.evm_u256_xor(a, b))
            elif op_byte == 0x13:
                a, b = self._pop(), self._pop()
                self._push(native.evm_u256_sgt(a, b))
            elif op_byte == 0x14:
                a, b = self._pop(), self._pop()
                self._push(native.evm_u256_eq(a, b))
            elif op_byte == 0x15:
                self._push(native.evm_u256_iszero(self._pop()))
            elif op_byte == 0x16:
                a, b = self._pop(), self._pop()
                self._push(native.evm_u256_lt(a, b))
            elif op_byte == 0x17:
                a, b = self._pop(), self._pop()
                self._push(native.evm_u256_gt(a, b))
            elif op_byte == 0x18:
                a, b = self._pop(), self._pop()
                self._push(native.evm_u256_slt(a, b))
            elif op_byte == 0x19:
                self._push(native.evm_u256_not(self._pop()))
            elif op_byte == 0x1A:
                i, x = self._pop(), self._pop()
                self._push(native.evm_u256_byte(i, x))
            elif op_byte == 0x1B:
                shift, v = self._pop(), self._pop()
                self._push(native.evm_u256_shl(v, shift))
            elif op_byte == 0x1C:
                shift, v = self._pop(), self._pop()
                self._push(native.evm_u256_shr(v, shift))
            elif op_byte == 0x1D:
                shift, v = self._pop(), self._pop()
                self._push(native.evm_u256_sar(v, shift))
            elif op_byte == 0x20:  # SHA3
                offset, size = self._pop(), self._pop()
                self._mem_extend(offset, size)
                digest = native.evm_keccak256_memory(bytes(self.memory), offset, size)
                self._push(int.from_bytes(digest, "big"))
            elif op_byte == 0x30:  # ADDRESS
                self._push(self.ctx.addr_int(self.ctx.address))
            elif op_byte == 0x31:  # BALANCE
                who = self._pop()
                addr = hex(who)[2:].rjust(40, "0")
                bal = 0
                if self.ctx.balance_of:
                    bal = int(self.ctx.balance_of("0x" + addr[-40:]))
                self._push(bal)
            elif op_byte == 0x32:  # ORIGIN
                self._push(self.ctx.addr_int(self.ctx.origin))
            elif op_byte == 0x33:  # CALLER
                self._push(self.ctx.addr_int(self.ctx.caller))
            elif op_byte == 0x34:  # CALLVALUE
                self._push(self.ctx.value)
            elif op_byte == 0x35:  # CALLDATALOAD
                i = self._pop()
                self._push(native.evm_calldataload(self.ctx.calldata, i))
            elif op_byte == 0x36:  # CALLDATASIZE
                self._push(len(self.ctx.calldata))
            elif op_byte == 0x37:  # CALLDATACOPY
                dest, offset, size = self._pop(), self._pop(), self._pop()
                self._mem_extend(dest, size)
                native.evm_memory_copy(self.memory, dest, self.ctx.calldata, offset, size)
            elif op_byte == 0x38:  # CODESIZE
                self._push(len(self.bytecode))
            elif op_byte == 0x39:  # CODECOPY
                dest, offset, size = self._pop(), self._pop(), self._pop()
                self._mem_extend(dest, size)
                native.evm_memory_copy(self.memory, dest, self.bytecode, offset, size)
            elif op_byte == 0x3A:  # GASPRICE
                self._push(int(self.ctx.gas_price))
            elif op_byte == 0x3F:  # EXTCODEHASH
                who = self._pop()
                addr = self._word_to_addr(who)
                code_hash = 0
                if self.ctx.code_size_of and self.ctx.code_copy_of:
                    size = int(self.ctx.code_size_of(addr))
                    if size > 0:
                        code = self.ctx.code_copy_of(addr, 0, size)
                        if code:
                            code_hash = int.from_bytes(native.keccak256_digest(code), "big")
                self._push(code_hash)
            elif op_byte == 0x3D:  # RETURNDATASIZE
                self._push(len(self.return_data))
            elif op_byte == 0x3E:  # RETURNDATACOPY
                dest, offset, size = self._pop(), self._pop(), self._pop()
                self._mem_extend(dest, size)
                native.evm_memory_copy(self.memory, dest, self.return_data, offset, size)
            elif op_byte == 0x3B:  # EXTCODESIZE
                who = self._pop()
                addr = self._word_to_addr(who)
                size = 0
                if self.ctx.code_size_of:
                    size = int(self.ctx.code_size_of(addr))
                self._push(size)
            elif op_byte == 0x3C:  # EXTCODECOPY
                code_offset = self._pop()
                mem_offset = self._pop()
                size = self._pop()
                who = self._pop()
                addr = self._word_to_addr(who)
                chunk = b""
                if self.ctx.code_copy_of:
                    chunk = self.ctx.code_copy_of(addr, code_offset, size)
                self._mem_extend(mem_offset, size)
                native.evm_memory_copy(self.memory, mem_offset, chunk, 0, size)
            elif 0xA0 <= op_byte <= 0xA4:  # LOG0..LOG4
                if self._revert_static_write():
                    break
                n_topics = op_byte - 0xA0
                topics = [self._pop() for _ in range(n_topics)]
                topics.reverse()
                size = self._pop()
                offset = self._pop()
                self._consume_gas("LOG", extra=n_topics * 375 + size)
                self._mem_extend(offset, size)
                data = native.evm_memory_slice(bytes(self.memory), offset, size)
                if self.ctx.emit_log:
                    self.ctx.emit_log(n_topics, topics, data)
                self.logs.append({
                    "topics": [hex(t) for t in topics],
                    "data": data.hex(),
                })
            elif op_byte == 0x40:  # BLOCKHASH
                block_num = self._pop()
                h = 0
                if self.ctx.block_hash_of:
                    h = int(self.ctx.block_hash_of(block_num))
                self._push(h)
            elif op_byte == 0x42:  # TIMESTAMP
                self._push(self.ctx.timestamp)
            elif op_byte == 0x43:  # NUMBER
                self._push(self.ctx.block_number)
            elif op_byte == 0x41:  # COINBASE
                self._push(self.ctx.addr_int(self.ctx.coinbase))
            elif op_byte == 0x44:  # DIFFICULTY / PREVRANDAO
                self._push(int(self.ctx.difficulty))
            elif op_byte == 0x45:  # GASLIMIT
                self._push(self.gas_limit)
            elif op_byte == 0x46:  # CHAINID
                self._push(self.ctx.chain_id)
            elif op_byte == 0x47:  # SELFBALANCE
                bal = 0
                if self.ctx.balance_of and self.ctx.address:
                    bal = int(self.ctx.balance_of(self.ctx.address))
                self._push(bal)
            elif op_byte == 0x48:  # BASEFEE
                self._push(int(self.ctx.base_fee))
            elif op_byte == 0x49:  # BLOBHASH
                index = int(self._pop())
                hashes = list(getattr(self.ctx, "blob_hashes", None) or [])
                val = 0
                if 0 <= index < len(hashes):
                    val = int(hashes[index]) & ((1 << 256) - 1)
                self._push(val)
            elif op_byte == 0x4A:  # BLOBBASEFEE
                self._push(int(getattr(self.ctx, "blob_base_fee", 0) or 0))
            elif op_byte == 0x50:  # POP
                self._pop()
            elif op_byte == 0x51:
                offset = self._pop()
                self._push(self._read_word(offset))
            elif op_byte == 0x52:
                offset, value = self._pop(), self._pop()
                self._write_word(offset, value)
            elif op_byte == 0x53:
                offset, value = self._pop(), self._pop()
                self._mem_extend(offset, 1)
                native.evm_memory_write_byte(self.memory, offset, value)
            elif op_byte == 0x54:
                key = self._pop()
                self._push(self.storage.get(key, 0))
            elif op_byte == 0x55:
                if self._revert_static_write():
                    break
                key, value = self._pop(), self._pop()
                if native.evm_u256_iszero(value):
                    if key in self.storage:
                        del self.storage[key]
                else:
                    self.storage[key] = value
            elif op_byte == 0x56:
                dest = self._pop()
                if not self._is_jumpdest(bytecode, dest, jumpdest_table):
                    raise RuntimeError(f"invalid jump destination: {dest}")
                self.pc = dest
                continue
            elif op_byte == 0x57:
                dest, cond = self._pop(), self._pop()
                if cond != 0:
                    if not self._is_jumpdest(bytecode, dest, jumpdest_table):
                        raise RuntimeError(f"invalid jump destination: {dest}")
                    self.pc = dest
                    continue
            elif op_byte == 0x5A:  # GAS
                self._push(native.evm_gas_remaining(self.gas_limit, self.gas_used))
            elif op_byte == 0x5B:  # JUMPDEST
                pass
            elif op_byte == 0x5C:  # TLOAD
                key = self._pop()
                self._push(self.transient_storage.get(key, 0))
            elif op_byte == 0x5D:  # TSTORE
                if self._revert_static_write():
                    break
                key, value = self._pop(), self._pop()
                if native.evm_u256_iszero(value):
                    self.transient_storage.pop(key, None)
                else:
                    self.transient_storage[key] = value
            elif op_byte == 0x5E:  # MCOPY
                length = self._pop()
                src = self._pop()
                dest = self._pop()
                size = int(length)
                self._consume_gas("MCOPY", extra=3 * ((size + 31) // 32))
                self._mem_extend(dest, size)
                self._mem_extend(src, size)
                chunk = bytes(self.memory[src:src + size])
                native.evm_memory_copy(self.memory, dest, chunk, 0, size)
            elif op_byte == 0x58:  # PC
                self._push(self.pc)
            elif op_byte == 0x59:  # MSIZE
                ln = len(self.memory)
                self._push(0 if ln == 0 else ((ln + 31) // 32) * 32)
            elif op_byte == 0x5F:  # PUSH0
                self._push(0)
            elif 0x80 <= op_byte <= 0x8F:  # DUP1..DUP16
                n = op_byte - 0x7F
                native.evm_stack_dup(self.stack, n)
            elif 0x90 <= op_byte <= 0x9F:  # SWAP1..SWAP16
                n = op_byte - 0x8F
                native.evm_stack_swap(self.stack, n)
            elif op_byte == 0xF0:  # CREATE
                if self._revert_static_write():
                    break
                size = self._pop()
                offset = self._pop()
                value = self._pop()
                self._push(self._execute_create(value, offset, size))
            elif op_byte == 0xF5:  # CREATE2
                if self._revert_static_write():
                    break
                salt = self._pop()
                size = self._pop()
                offset = self._pop()
                value = self._pop()
                self._push(self._execute_create(value, offset, size, salt))
            elif op_byte == 0xF2:  # CALLCODE
                gas = self._pop()
                to_word = self._pop()
                value = self._pop()
                args_offset = self._pop()
                args_size = self._pop()
                ret_offset = self._pop()
                ret_size = self._pop()
                self._push(self._execute_call(
                    to_word, value, args_offset, args_size, ret_offset, ret_size,
                    gas, False, False, True
                ))
            elif op_byte == 0xF1:  # CALL
                gas = self._pop()
                to_word = self._pop()
                value = self._pop()
                args_offset = self._pop()
                args_size = self._pop()
                ret_offset = self._pop()
                ret_size = self._pop()
                self._push(self._execute_call(
                    to_word, value, args_offset, args_size, ret_offset, ret_size,
                    gas, False, False
                ))
            elif op_byte == 0xF4:  # DELEGATECALL
                gas = self._pop()
                to_word = self._pop()
                args_offset = self._pop()
                args_size = self._pop()
                ret_offset = self._pop()
                ret_size = self._pop()
                self._push(self._execute_call(
                    to_word, 0, args_offset, args_size, ret_offset, ret_size,
                    gas, True, False
                ))
            elif op_byte == 0xFA:  # STATICCALL
                gas = self._pop()
                to_word = self._pop()
                args_offset = self._pop()
                args_size = self._pop()
                ret_offset = self._pop()
                ret_size = self._pop()
                self._push(self._execute_call(
                    to_word, 0, args_offset, args_size, ret_offset, ret_size,
                    gas, False, True
                ))
            elif op_byte == 0xF3:  # RETURN
                offset, size = self._pop(), self._pop()
                self._mem_extend(offset, size)
                self.return_data = native.evm_memory_slice(bytes(self.memory), offset, size)
                self.running = False
                break
            elif op_byte == 0xFD:  # REVERT
                offset, size = self._pop(), self._pop()
                self._mem_extend(offset, size)
                self.return_data = native.evm_memory_slice(bytes(self.memory), offset, size)
                self.reverted = True
                self.running = False
                break
            elif op_byte == 0xFE:  # INVALID
                raise RuntimeError("invalid opcode")
            elif op_byte == 0xFF:  # SELFDESTRUCT
                if self._revert_static_write():
                    break
                beneficiary = self._pop()
                if self.ctx.selfdestruct:
                    self.ctx.selfdestruct(self._word_to_addr(beneficiary))
                self.running = False
                break
            else:
                raise RuntimeError(f"unsupported opcode 0x{op_byte:02x}")

            self.pc += 1

        return {
            "success": self.running or (not self.reverted and bool(self.return_data or self.stack)),
            "reverted": self.reverted,
            "stack": self.stack.copy(),
            "memory": bytes(self.memory),
            "storage": self.storage.copy(),
            "gas_used": self.gas_used,
            "return_data": self.return_data,
            "trace": self.trace,
            "logs": self.logs.copy(),
        }

    @staticmethod
    def _opcode_name(op: int) -> str:
        names = {
            0x00: "STOP", 0x01: "ADD", 0x02: "MUL", 0x03: "SUB", 0x04: "DIV",
            0x05: "SDIV", 0x06: "MOD", 0x07: "SMOD", 0x08: "ADDMOD", 0x09: "MULMOD",
            0x0A: "EXP", 0x0B: "SIGNEXTEND",
            0x10: "AND", 0x11: "OR", 0x12: "XOR", 0x13: "SGT", 0x14: "EQ",
            0x15: "ISZERO", 0x16: "LT", 0x17: "GT", 0x18: "SLT", 0x19: "NOT", 0x1A: "BYTE",
            0x1B: "SHL", 0x1C: "SHR", 0x1D: "SAR", 0x20: "SHA3", 0x30: "ADDRESS",
            0x31: "BALANCE", 0x32: "ORIGIN", 0x33: "CALLER", 0x34: "CALLVALUE",
            0x35: "CALLDATALOAD", 0x36: "CALLDATASIZE", 0x37: "CALLDATACOPY",
            0x38: "CODESIZE", 0x39: "CODECOPY", 0x3A: "GASPRICE", 0x3B: "EXTCODESIZE", 0x3C: "EXTCODECOPY",
            0x3F: "EXTCODEHASH",
            0x40: "BLOCKHASH",
            0x3D: "RETURNDATASIZE", 0x3E: "RETURNDATACOPY",
            0x42: "TIMESTAMP", 0x43: "NUMBER", 0x41: "COINBASE", 0x44: "DIFFICULTY",
            0x45: "GASLIMIT", 0x46: "CHAINID",
            0x47: "SELFBALANCE", 0x48: "BASEFEE", 0x49: "BLOBHASH", 0x4A: "BLOBBASEFEE",
            0x50: "POP", 0x51: "MLOAD",
            0x52: "MSTORE", 0x53: "MSTORE8", 0x54: "SLOAD", 0x55: "SSTORE",
            0x56: "JUMP", 0x57: "JUMPI", 0x58: "PC", 0x59: "MSIZE", 0x5A: "GAS", 0x5B: "JUMPDEST",
            0x5C: "TLOAD", 0x5D: "TSTORE", 0x5E: "MCOPY", 0x5F: "PUSH0",
            0xA0: "LOG0", 0xFF: "SELFDESTRUCT",
            0xF0: "CREATE", 0xF5: "CREATE2",
            0xF1: "CALL", 0xF2: "CALLCODE", 0xF4: "DELEGATECALL", 0xFA: "STATICCALL",
            0xF3: "RETURN", 0xFD: "REVERT", 0xFE: "INVALID",
        }
        if 0x60 <= op <= 0x7F:
            return f"PUSH{op - 0x5F}"
        if 0x80 <= op <= 0x8F:
            return f"DUP{op - 0x7F}"
        if 0x90 <= op <= 0x9F:
            return f"SWAP{op - 0x8F}"
        return names.get(op, f"UNKNOWN_{op:02x}")


def test_evm():
    ctx = EVMContext(caller="0x00000000000000000000000000000000000000ab")
    evm = EVM(context=ctx)
    bytecode = bytes([0x60, 0x05, 0x60, 0x07, 0x01, 0x00])
    result = evm.execute_bytecode(bytecode)
    assert result["stack"][-1] == 12
    evm2 = EVM(context=ctx)
    r2 = evm2.execute_bytecode(bytes([0x33, 0x00]))
    assert r2["stack"][-1] == ctx.addr_int(ctx.caller)
    print("EVM interpreter OK")


if __name__ == "__main__":
    test_evm()
