# runtime/native_capabilities.py — ADR 0009 optional Rust capability registry
"""Per-family rust|python backend selection for abs_native kernels."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

_logger = logging.getLogger(__name__)

Backend = Literal["rust", "python"]


class NativeFamily(str, Enum):
    CRYPTO_HASH = "crypto_hash"
    CRYPTO_SIG = "crypto_sig"
    MERKLE = "merkle"
    WIRE_CODEC = "wire_codec"
    GHOST = "ghost"
    EVM_KERNEL = "evm_kernel"
    BLOCK_APPLY = "block_apply"
    P2P_TRANSPORT = "p2p_transport"
    P2P_INGRESS = "p2p_ingress"
    MEMPOOL_KERNEL = "mempool_kernel"
    MEMPOOL_STORE = "mempool_store"


# Symbols that must exist on abs_native for a family to pass probe.
_FAMILY_ATTRS: Dict[NativeFamily, List[str]] = {
    NativeFamily.CRYPTO_HASH: ["sha256_hex", "hash_text"],
    NativeFamily.CRYPTO_SIG: ["verify_secp256k1_sha256"],
    NativeFamily.MERKLE: ["merkle_root"],
    NativeFamily.WIRE_CODEC: ["encode_wire_v2", "decode_wire_v2"],
    NativeFamily.GHOST: ["ghost_select_head"],
    NativeFamily.EVM_KERNEL: ["evm_run_until_halt"],
    NativeFamily.BLOCK_APPLY: ["blockchain_apply_simple_block"],
    NativeFamily.P2P_TRANSPORT: ["P2PNativeConn"],
    NativeFamily.P2P_INGRESS: ["p2p_ingress_admit"],
    NativeFamily.MEMPOOL_KERNEL: ["mempool_validate_post_sig", "mempool_admit_evm_deploy"],
    NativeFamily.MEMPOOL_STORE: ["MempoolStore"],
}


@dataclass(frozen=True)
class FamilyStatus:
    family: NativeFamily
    backend: Backend
    available: bool
    error: str
    self_test_ok: bool


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_native_mode(default: str = "auto") -> str:
    """Return ``auto`` | ``off`` | ``require``.

    Aliases: ``ABS_DISABLE_NATIVE_CRYPTO`` → off, ``ABS_REQUIRE_NATIVE_CRYPTO`` → require.
    """
    explicit = os.getenv("ABS_NATIVE_MODE", "").strip().lower()
    if explicit in {"auto", "off", "require", "force_off", "disabled"}:
        if explicit in {"force_off", "disabled"}:
            return "off"
        return explicit
    if _truthy(os.getenv("ABS_DISABLE_NATIVE_CRYPTO", "")):
        return "off"
    if _truthy(os.getenv("ABS_REQUIRE_NATIVE_CRYPTO", "")):
        return "require"
    return (default or "auto").strip().lower() or "auto"


def _forced_python_families() -> set:
    raw = os.getenv("ABS_NATIVE_FAMILIES", "").strip()
    if not raw:
        return set()
    out = set()
    for part in raw.split(","):
        key = part.strip().lower()
        if not key:
            continue
        try:
            out.add(NativeFamily(key))
        except ValueError:
            _logger.warning("[native] unknown ABS_NATIVE_FAMILIES entry: %s", key)
    return out


class NativeCapabilityRegistry:
    """Process-wide capability map. Thread-safe after ``bootstrap()``."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._bootstrapped = False
        self._mode = "auto"
        self._module: Any = None
        self._import_error: str = ""
        self._backends: Dict[NativeFamily, Backend] = {
            f: "python" for f in NativeFamily
        }
        self._errors: Dict[NativeFamily, str] = {}
        self._self_test: Dict[NativeFamily, bool] = {f: False for f in NativeFamily}

    def bootstrap(self) -> None:
        with self._lock:
            if self._bootstrapped:
                return
            self._mode = resolve_native_mode()
            forced_py = _forced_python_families()

            if self._mode == "off":
                self._import_error = "ABS_NATIVE_MODE=off"
                self._finalize_python_only("forced_off")
                self._bootstrapped = True
                return

            try:
                import abs_native as mod  # type: ignore
                self._module = mod
            except Exception as exc:
                self._import_error = str(exc)
                self._module = None
                if self._mode == "require":
                    raise RuntimeError(
                        "ABS_NATIVE_MODE=require but abs_native is not available"
                    ) from exc
                _logger.warning(
                    "[native] abs_native unavailable — Python backends (%s)",
                    self._import_error,
                )
                self._finalize_python_only(self._import_error)
                self._bootstrapped = True
                return

            for family in NativeFamily:
                if family in forced_py:
                    self._backends[family] = "python"
                    self._errors[family] = "forced_by_ABS_NATIVE_FAMILIES"
                    self._self_test[family] = False
                    continue
                ok, err = self._probe_family(family)
                if ok:
                    self._backends[family] = "rust"
                    self._errors[family] = ""
                    self._self_test[family] = True
                else:
                    self._backends[family] = "python"
                    self._errors[family] = err
                    self._self_test[family] = False
                    if self._mode == "require":
                        raise RuntimeError(
                            f"ABS_NATIVE_MODE=require: family {family.value} failed: {err}"
                        )
                    _logger.warning(
                        "[native] demote %s → python (%s)", family.value, err
                    )

            self._bootstrapped = True

    def _finalize_python_only(self, reason: str) -> None:
        for family in NativeFamily:
            self._backends[family] = "python"
            self._errors[family] = reason
            self._self_test[family] = False

    def _probe_family(self, family: NativeFamily) -> tuple[bool, str]:
        mod = self._module
        if mod is None:
            return False, "no_module"
        for attr in _FAMILY_ATTRS.get(family, []):
            if not hasattr(mod, attr):
                return False, f"missing_attr:{attr}"
        try:
            if family == NativeFamily.CRYPTO_HASH:
                got = str(mod.sha256_hex(b"absolute"))
                expect = (
                    "747355bdc2a224032fd405b1b9e8985bfca47e45b34668f7d0a70ee4789bd855"
                )
                if got != expect:
                    return False, "sha256_self_test_mismatch"
            elif family == NativeFamily.WIRE_CODEC:
                frame = bytes(mod.encode_wire_v2("ping", b"{}"))
                decoded = mod.decode_wire_v2(frame)
                if str(decoded.get("type") or decoded.get("msg_type") or "") != "ping":
                    return False, "wire_roundtrip_failed"
            elif family == NativeFamily.MERKLE:
                # smoke: non-empty root
                root = str(mod.merkle_root(["a", "b"]))
                if not root or len(root) < 32:
                    return False, "merkle_smoke_failed"
            elif family == NativeFamily.MEMPOOL_KERNEL:
                snap = {"nonce": 0, "balance_sat": 5_000_000}
                tx = {
                    "from_addr": "0x1111111111111111111111111111111111111111",
                    "to_addr": "0x2222222222222222222222222222222222222222",
                    "nonce": 0,
                    "value_sat": 1_000_000,
                    "fee_sat": 50_000,
                    "gas_limit": 21_000,
                }
                out = mod.mempool_validate_post_sig(snap, tx)
                if not isinstance(out, dict) or not out.get("accept"):
                    return False, "mempool_kernel_accept_smoke_failed"
                bad = dict(tx)
                bad["nonce"] = 9
                refuse = mod.mempool_validate_post_sig(snap, bad)
                if not isinstance(refuse, dict) or refuse.get("accept"):
                    return False, "mempool_kernel_refuse_smoke_failed"
                if refuse.get("reason") != "nonce_mismatch":
                    return False, "mempool_kernel_reason_mismatch"
                eof = mod.mempool_admit_evm_deploy("0xEF0000")
                if not isinstance(eof, dict) or eof.get("accept"):
                    return False, "mempool_admit_eof_smoke_failed"
                if eof.get("reason") != "unsupported_evm_bytecode:eof_container_not_supported":
                    return False, "mempool_admit_eof_reason_mismatch"
                bad_op = mod.mempool_admit_evm_deploy("0x5C")
                if not isinstance(bad_op, dict) or bad_op.get("accept"):
                    return False, "mempool_admit_opcode_smoke_failed"
                if bad_op.get("reason") != "unsupported_evm_bytecode:0x5C":
                    return False, "mempool_admit_opcode_reason_mismatch"
            elif family == NativeFamily.MEMPOOL_STORE:
                store = mod.MempoolStore(8, 0)
                ok = bool(
                    store.insert(
                        {
                            "tx_hash": "h_high",
                            "from_addr": "0xa",
                            "to_addr": "0xb",
                            "amount": 1.0,
                            "amount_satoshi": 1_000_000,
                            "fee": 9.0,
                            "fee_satoshi": 9_000_000,
                            "nonce": 0,
                            "signature": "",
                            "public_key": "",
                            "data": "",
                            "gas": 21_000,
                            "timestamp": 1.0,
                        }
                    )
                )
                if not ok:
                    return False, "mempool_store_insert_failed"
                ok2 = bool(
                    store.insert(
                        {
                            "tx_hash": "h_low",
                            "from_addr": "0xa",
                            "to_addr": "0xb",
                            "amount": 1.0,
                            "amount_satoshi": 1_000_000,
                            "fee": 1.0,
                            "fee_satoshi": 1_000_000,
                            "nonce": 1,
                            "signature": "",
                            "public_key": "",
                            "data": "",
                            "gas": 21_000,
                            "timestamp": 1.0,
                        }
                    )
                )
                if not ok2:
                    return False, "mempool_store_insert2_failed"
                ranked = list(store.get_sorted(10, 0))
                if len(ranked) != 2 or str(ranked[0].get("tx_hash")) != "h_high":
                    return False, "mempool_store_sort_failed"
                if not store.contains("h_high") or not store.remove("h_low"):
                    return False, "mempool_store_remove_failed"
                if int(store.size()) != 1:
                    return False, "mempool_store_size_mismatch"
        except Exception as exc:
            return False, f"self_test:{exc}"
        return True, ""

    def ensure_bootstrapped(self) -> None:
        if not self._bootstrapped:
            self.bootstrap()

    def module(self) -> Any:
        self.ensure_bootstrapped()
        return self._module

    def backend(self, family: NativeFamily) -> Backend:
        self.ensure_bootstrapped()
        with self._lock:
            return self._backends.get(family, "python")

    def use_rust(self, family: NativeFamily) -> bool:
        return self.backend(family) == "rust" and self._module is not None

    def demote(self, family: NativeFamily, reason: str) -> None:
        """Demote a family to Python. Forbidden under ABS_NATIVE_MODE=require (Wave H)."""
        self.ensure_bootstrapped()
        with self._lock:
            prev = self._backends.get(family, "python")
            mode = self._mode
            if prev == "rust" and mode == "require":
                raise RuntimeError(
                    f"ABS_NATIVE_MODE=require forbids demote of {family.value}: "
                    f"{reason or 'demoted'}"
                )
            self._backends[family] = "python"
            self._errors[family] = str(reason or "demoted")
            self._self_test[family] = False
            if prev == "rust":
                _logger.warning(
                    "[native] runtime demote %s → python (%s)",
                    family.value,
                    reason,
                )

    def status(self) -> dict:
        self.ensure_bootstrapped()
        with self._lock:
            families = {}
            for family in NativeFamily:
                families[family.value] = {
                    "backend": self._backends[family],
                    "available": self._backends[family] == "rust",
                    "error": self._errors.get(family, ""),
                    "self_test_ok": self._self_test.get(family, False),
                }
            return {
                "mode": self._mode,
                "module_loaded": self._module is not None,
                "import_error": self._import_error,
                "families": families,
            }

    def reset_for_tests(self) -> None:
        """Test helper: clear bootstrap so env changes take effect."""
        with self._lock:
            self._bootstrapped = False
            self._module = None
            self._import_error = ""
            self._backends = {f: "python" for f in NativeFamily}
            self._errors = {}
            self._self_test = {f: False for f in NativeFamily}


_REGISTRY = NativeCapabilityRegistry()


def get_registry() -> NativeCapabilityRegistry:
    return _REGISTRY


def bootstrap_native_capabilities() -> NativeCapabilityRegistry:
    _REGISTRY.bootstrap()
    return _REGISTRY
