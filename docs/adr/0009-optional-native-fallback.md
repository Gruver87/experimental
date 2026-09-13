# ADR 0009 — Optional Native Fallback (Capability Registry)

- **Status:** Accepted
- **Date:** 2026-07-30
- **Deciders:** Absolute Blockchain maintainers

## Context

`abs_native` (PyO3) accelerates hot kernels, but a missing wheel or import
failure must not prevent node boot. Dual-stack wire codec v2 (ADR 0008) and
hash/Merkle/sig paths already have partial Python fallbacks in `crypto.native`,
yet `network.wire_codec.encode_wire_v2` raised without Rust, and there was no
per-family capability surface for `/health`.

## Decision

1. **`NativeCapabilityRegistry`** (`runtime/native_capabilities.py`) bootstraps
   once, imports `abs_native` when allowed, runs per-family self-tests, and
   selects `rust` | `python` backends.
2. **Families:** `crypto_hash`, `crypto_sig`, `merkle`, `wire_codec`, `ghost`,
   `evm_kernel`, `block_apply`, `p2p_transport`, `p2p_ingress`, `mempool_kernel`
   (ADR 0021 phase 1/3), `mempool_store` (ADR 0021 phase 2).
3. **Policy env `ABS_NATIVE_MODE`:**
   - `auto` (default) — import + self-test; fail → Python, WARNING
   - `off` — force Python (`ABS_DISABLE_NATIVE_CRYPTO=1` alias)
   - `require` — missing/failed native → refuse start (`ABS_REQUIRE_NATIVE_CRYPTO=1` alias)
4. **`ABS_NATIVE_FAMILIES`** — comma list of families forced to Python even when
   Rust is loaded.
5. **Ports** in `crypto/kernels/ports.py` (`WireCodecPort`, `HashKernelPort`,
   `MerklePort`, `SigPort`, `P2PTransportCapability`). Call sites keep
   `crypto.native.*` / `network.wire_codec.*` signatures; internals consult the
   registry.
6. **Pure-Python Borsh** subset for `WireEnvelopeV2` so AB2 framing works without
   a wheel (byte-compatible with Rust Borsh).
7. **Runtime demote:** Rust exceptions on a family call can demote that family
   to Python for the process lifetime.

## Honesty

- «Runs everywhere» ≠ same TPS as Rust.
- GhostForest / GIL-releasing batch APIs are **not** fully emulated in Python;
  `ghost=python` means JSON-GHOST / per-item paths.
- P2P transport without Rust uses the asyncio socket path, not `P2PNativeConn`.

## Definition of Done

- Boot without `abs_native` succeeds under `auto`/`off`
- `require` without wheel fails fast
- Golden vectors: Python Borsh encode/decode == Rust when both available
- `/health`-shaped `registry.status()` exposes per-family backend
